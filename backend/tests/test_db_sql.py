"""実 DB を使った一括スキャン・SQL 出力の結合テスト。

INSERT 文（Python でマスク）と UPDATE 文（DB の関数でマスク）を実際に実行し、
結果が一致すること（＝どちらの方法でも同じマスク結果になること）を確認する。
DBEXP_TEST_PG / DBEXP_TEST_ORACLE が未設定の場合はスキップする。
"""

import os
import time

import pytest
from fastapi.testclient import TestClient

from . import fixtures_jp as fx


def _params(env):
    value = os.environ.get(env)
    if not value:
        pytest.skip(f"{env} が未設定のため DB テストをスキップします")
    hostport, db, user, pw = value.split("/", 3)
    host, port = hostport.split(":")
    return host, int(port), db, user, pw


def _raw_connect(db_type, host, port, db, user, pw):
    if db_type == "oracle":
        import oracledb

        return oracledb.connect(user=user, password=pw, dsn=f"{host}:{port}/{db}")
    import psycopg

    return psycopg.connect(host=host, port=port, dbname=db, user=user, password=pw)


def split_oracle_script(sql: str) -> list[str]:
    """SQL*Plus 用のスクリプトを文ごとに分ける（テスト用の簡易版）。"""
    lines = [ln for ln in sql.splitlines() if not ln.startswith(("--", "SET ", "WHENEVER "))]
    text = "\n".join(lines)
    out, cur, in_quote = [], [], False
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
        if ch == ";" and not in_quote:
            stmt = "".join(cur).strip()
            if stmt:
                out.append(stmt)
            cur = []
            continue
        cur.append(ch)
    return out


def run_script(conn, db_type, sql: str) -> None:
    with conn.cursor() as cur:
        if db_type == "oracle":
            for stmt in split_oracle_script(sql):
                if stmt.upper() == "COMMIT":
                    conn.commit()
                else:
                    cur.execute(stmt)
        else:
            cur.execute(sql)
    conn.commit()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DBEXP_DATA_DIR", str(tmp_path))
    from app.main import create_app

    return TestClient(create_app(), headers={"x-dbexp": "1"})


def _wait(client, url):
    for _ in range(300):
        st = client.get(url).json()
        if st["status"] not in ("pending", "running"):
            return st
        time.sleep(0.05)
    raise AssertionError("タイムアウト")


@pytest.mark.parametrize("env,db_type", [("DBEXP_TEST_PG", "postgresql"), ("DBEXP_TEST_ORACLE", "oracle")])
def test_scan_dump_and_update_give_same_result(client, env, db_type):
    host, port, db, user, pw = _params(env)
    raw = _raw_connect(db_type, host, port, db, user, pw)
    fx.create(raw, db_type)
    if db_type == "oracle":
        # 作成直後の表を読み取り専用トランザクションで読むと ORA-01466 になるため少し待つ
        time.sleep(4)
    table = fx.TABLE if db_type == "oracle" else fx.TABLE.lower()

    conn = client.post("/api/connections", json={
        "name": db_type, "db_type": db_type, "host": host, "port": port, "database": db, "username": user,
    }).json()
    assert client.post(f"/api/connections/{conn['id']}/connect", json={"password": pw}).status_code == 200
    schema = client.get(f"/api/connections/{conn['id']}/schemas").json()["default"]

    # 1. 一括スキャン
    job = client.post(f"/api/connections/{conn['id']}/scan", json={"schema_name": schema, "tables": [table]}).json()
    st = _wait(client, f"/api/scan/{job['job_id']}")
    assert st["status"] == "done", st
    found = {f["column"].upper(): f for f in st["findings"]}
    assert {k for k, f in found.items() if f["level"] == "auto"} >= {
        "SHIMEI", "SHIMEI_KANA", "TEL_NO", "MAIL_ADDR", "ZIP_CD", "JUSHO", "BIRTH_DT", "BIKO",
    }
    assert found["KOKYAKU_ID"]["level"] == "review"
    assert "MAIL_HAISHIN_FLG" not in found and "TOROKU_DT" not in found

    # 要確認も含めて推奨規則でマスクする
    columns = st["tables"][0]["columns"]
    spec = {"schema_name": schema, "table": table,
            "columns": [{"name": c["name"], "mask": found[c["name"].upper()]["rule"] if c["name"].upper() in found else None}
                        for c in columns]}

    def export(fmt):
        j = client.post("/api/export", json={"connection_id": conn["id"], "tables": [spec],
                                             "options": {"format": fmt, "hash_salt": "salt"}}).json()
        st = _wait(client, f"/api/export/{j['job_id']}")
        assert st["status"] == "done", st
        return client.get(f"/api/export/{j['job_id']}/download").content.decode("utf-8")

    insert_sql, update_sql = export("sql_insert"), export("sql_update")
    assert "主キーの列のため" in insert_sql  # 数値の主キーにはハッシュ化を適用しない

    # 2. INSERT 文: 全件削除してマスク済みデータを投入
    with raw.cursor() as cur:
        cur.execute(f"DELETE FROM {fx.TABLE}")
    raw.commit()
    run_script(raw, db_type, insert_sql)
    dumped = fx.fetch_all(raw)

    # 3. UPDATE 文: 元のデータに戻してから、その場でマスク
    with raw.cursor() as cur:
        cur.execute(f"DELETE FROM {fx.TABLE}")
    fx.insert_rows(raw, db_type, fx.rows())
    raw.commit()
    run_script(raw, db_type, update_sql)
    updated = fx.fetch_all(raw)
    raw.close()

    names = [n for n, _, _, _ in fx.COLUMNS]
    original = fx.rows()
    assert len(dumped) == len(updated) == len(original)
    for d_row, u_row, o_row in zip(dumped, updated, original):
        for name, d, u, o in zip(names, d_row, u_row, o_row):
            if name == "BIKO":
                # 文中のマスクは UPDATE 文では簡易版のため一致しない。元の個人情報が残っていないことのみ確認
                for secret in ("090-1234-5678", "taro@"):
                    assert secret not in (u or "") and secret not in (d or "")
                continue
            assert d == u, f"{name}: dump={d!r} update={u!r}"
            if name in ("SHIMEI", "TEL_NO", "MAIL_ADDR", "JUSHO"):
                assert d != o
