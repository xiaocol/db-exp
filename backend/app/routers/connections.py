"""接続プロファイル・メタデータ取得 API。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import dbscan, store
from ..db import DbError, get_dialect
from ..schemas import (
    ColumnInfo,
    ConnectionInput,
    ConnectionProfile,
    ConnectRequest,
    ConnectResult,
    TableInfo,
)

router = APIRouter(prefix="/api/connections", tags=["接続"])


@router.get("", response_model=list[ConnectionProfile])
def list_connections() -> list[ConnectionProfile]:
    return store.list_profiles()


@router.post("", response_model=ConnectionProfile)
def save_connection(inp: ConnectionInput) -> ConnectionProfile:
    return store.upsert(inp)


@router.delete("/{conn_id}")
def delete_connection(conn_id: str) -> dict:
    store.delete(conn_id)
    return {"ok": True}


@router.post("/test", response_model=ConnectResult)
def test_connection(inp: ConnectionInput) -> ConnectResult:
    """保存前の接続テスト。パスワード未入力時は保存済みのものを使う。"""
    if inp.id and not inp.password:
        saved = store.get_input(inp.id)
        inp.password = saved.password
    password = store.resolve_password(inp, None)
    dialect = get_dialect(inp.db_type)
    with dialect.session(inp, password) as conn:
        version = dialect.server_version(conn)
    return ConnectResult(ok=True, message="接続に成功しました。", server_version=version)


@router.post("/{conn_id}/connect", response_model=ConnectResult)
def connect(conn_id: str, req: ConnectRequest) -> ConnectResult:
    inp = store.get_input(conn_id)
    password = store.resolve_password(inp, req.password)
    dialect = get_dialect(inp.db_type)
    with dialect.session(inp, password) as conn:
        version = dialect.server_version(conn)
    store.mark_connected(conn_id, password)
    return ConnectResult(ok=True, message="接続しました。", server_version=version)


@router.post("/{conn_id}/disconnect")
def disconnect(conn_id: str) -> dict:
    store.disconnect(conn_id)
    return {"ok": True}


@router.get("/{conn_id}/schemas")
def list_schemas(conn_id: str) -> dict:
    with store.open_session(conn_id) as (dialect, conn, profile):
        return {
            "schemas": dialect.list_schemas(conn),
            "default": dialect.default_schema(conn, profile),
        }


@router.get("/{conn_id}/tables", response_model=list[TableInfo])
def list_tables(conn_id: str, schema: str) -> list[TableInfo]:
    with store.open_session(conn_id) as (dialect, conn, _):
        return dialect.list_tables(conn, schema)


@router.get("/{conn_id}/columns", response_model=list[ColumnInfo])
def list_columns(conn_id: str, schema: str, table: str, sample: int = 0) -> list[ColumnInfo]:
    """列情報と自動判定の結果。sample > 0 なら先頭の値も使って判定する。"""
    samples: dict = {}
    with store.open_session(conn_id) as (dialect, conn, _):
        columns = dialect.list_columns(conn, schema, table)
        if sample > 0:
            try:
                samples = dbscan.sample_rows(dialect, conn, schema, table, columns, min(sample, 5000))
            except DbError:
                # ビューの定義エラー等で値を取得できなくても、列名だけで判定する
                dialect.recover(conn)
    dbscan.analyze_table(schema, table, columns, samples)
    return columns
