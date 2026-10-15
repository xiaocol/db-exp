"""API の結合テスト。

DB を使うテストは、以下の環境変数が設定されている場合のみ実行する。
  DBEXP_TEST_PG     例: localhost:5432/postgres/postgres/password
  DBEXP_TEST_ORACLE 例: localhost:1521/FREEPDB1/appuser/password
（ホスト:ポート/DB名またはサービス名/ユーザー/パスワード）
"""

import os
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DBEXP_DATA_DIR", str(tmp_path))
    from app.main import create_app

    return TestClient(create_app(), headers={"x-dbexp": "1"})


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_post_without_csrf_header_is_rejected(client):
    raw = TestClient(client.app)
    assert raw.post("/api/connections", json={"name": "x"}).status_code == 403


def test_unknown_host_is_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_masking_rules_and_test(client):
    rules = client.get("/api/masking/rules").json()
    assert {"none", "name", "address", "digits"} <= {r["type"] for r in rules}
    res = client.post("/api/masking/test", json={"rule": {"type": "name", "params": {}}, "value": "山田 太郎"})
    assert res.json()["result"] == "山田 ＊＊"


def test_connection_crud_does_not_return_password(client):
    saved = client.post(
        "/api/connections",
        json={"name": "テスト", "db_type": "postgresql", "host": "h", "database": "d", "username": "u",
              "password": "secret", "save_password": True},
    ).json()
    assert saved["has_saved_password"] is True
    listed = client.get("/api/connections").json()
    assert "secret" not in str(listed)
    client.delete(f"/api/connections/{saved['id']}")
    assert client.get("/api/connections").json() == []


def _db_params(env: str):
    value = os.environ.get(env)
    if not value:
        pytest.skip(f"{env} が未設定のため DB テストをスキップします")
    hostport, db, user, pw = value.split("/", 3)
    host, port = hostport.split(":")
    return host, int(port), db, user, pw


@pytest.mark.parametrize("env,db_type", [("DBEXP_TEST_PG", "postgresql"), ("DBEXP_TEST_ORACLE", "oracle")])
def test_export_roundtrip(client, env, db_type):
    host, port, db, user, pw = _db_params(env)
    conn = client.post(
        "/api/connections",
        json={"name": db_type, "db_type": db_type, "host": host, "port": port, "database": db, "username": user},
    ).json()
    assert client.post(f"/api/connections/{conn['id']}/connect", json={"password": pw}).status_code == 200
    schemas = client.get(f"/api/connections/{conn['id']}/schemas").json()
    tables = client.get(f"/api/connections/{conn['id']}/tables", params={"schema": schemas["default"]}).json()
    if not tables:
        pytest.skip("既定スキーマに表がありません")
    t = tables[0]
    cols = client.get(f"/api/connections/{conn['id']}/columns", params={"schema": t["schema_name"], "table": t["name"]}).json()
    spec = {"schema_name": t["schema_name"], "table": t["name"], "max_rows": 100,
            "columns": [{"name": c["name"], "mask": c["suggested_mask"]} for c in cols]}
    job = client.post("/api/export", json={"connection_id": conn["id"], "tables": [spec]}).json()
    for _ in range(100):
        st = client.get(f"/api/export/{job['job_id']}").json()
        if st["status"] not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    res = client.get(f"/api/export/{job['job_id']}/download")
    assert res.status_code == 200 and res.content[:2] == b"PK"
