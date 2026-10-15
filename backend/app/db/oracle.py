"""Oracle Database 用の方言。

python-oracledb を使用する。既定は Thin モード（Oracle Client 不要, DB 12.1 以降）。
settings.json の oracle_client_lib_dir を指定すると Thick モードとなり、
11g など古いバージョンにも接続できる。

文字コード: Thin モードでは常に UTF-8 で受信し、DB 側（JA16SJIS, JA16EUC 等）からの
変換は DB サーバーが行うため、日本語データも追加設定なしで扱える。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import oracledb

from ..schemas import ColumnInfo, ConnectionInput, TableInfo
from .base import DbError, Dialect

log = logging.getLogger(__name__)

# LOB は文字列 / バイト列として直接取得する（ストリーム処理が不要になり高速）
oracledb.defaults.fetch_lobs = False
# NUMBER は Decimal で取得し、桁落ちを防ぐ（Excel 出力時に変換する）
oracledb.defaults.fetch_decimals = True

_thick_lock = threading.Lock()
_thick_initialized = False


def init_thick_mode(lib_dir: str | None) -> bool:
    """Thick モードを初期化する。プロセス内で 1 回のみ有効。"""
    global _thick_initialized
    if not lib_dir:
        return False
    with _thick_lock:
        if _thick_initialized:
            return True
        try:
            oracledb.init_oracle_client(lib_dir=lib_dir)
            _thick_initialized = True
            log.info("Oracle Thick モードで初期化しました: %s", lib_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("Oracle Thick モードの初期化に失敗しました（Thin モードで続行）: %s", exc)
        return _thick_initialized


def _translate_error(exc: Exception) -> DbError:
    """よくある Oracle エラーを日本語の説明付きに変換する。"""
    text = str(exc)
    hints = {
        "ORA-01017": "ユーザー名またはパスワードが正しくありません。",
        "ORA-12514": "サービス名が見つかりません。サービス名/SIDを確認してください。",
        "ORA-12505": "SIDが見つかりません。SID/サービス名の指定方法を確認してください。",
        "ORA-12541": "リスナーに接続できません。ホスト名・ポートを確認してください。",
        "ORA-00942": "表またはビューが存在しないか、参照権限がありません。",
        "ORA-00904": "列名が正しくありません（抽出条件・並び順を確認してください）。",
        "DPY-6005": "DBに接続できません。ホスト名・ポート・ネットワークを確認してください。",
        "DPY-3010": "Thinモード非対応のDBバージョンです（11g等）。Instant Clientを設定しThickモードを使用してください。",
        "DPY-4011": "DBとの接続が切断されました。",
    }
    for code, hint in hints.items():
        if code in text:
            return DbError(f"{hint}\n({text})")
    return DbError(text)


class OracleDialect(Dialect):
    db_type = "oracle"
    default_port = 1521

    def make_dsn(self, profile: ConnectionInput) -> str:
        if profile.oracle_connect_type == "dsn":
            if not profile.dsn:
                raise DbError("DSN（TNS名 / 接続文字列）を入力してください。")
            return profile.dsn
        port = profile.port or self.default_port
        if not profile.host or not profile.database:
            raise DbError("ホスト名とサービス名/SIDを入力してください。")
        if profile.oracle_connect_type == "sid":
            return oracledb.makedsn(profile.host, port, sid=profile.database)
        return oracledb.makedsn(profile.host, port, service_name=profile.database)

    def connect(self, profile: ConnectionInput, password: str) -> Any:
        try:
            conn = oracledb.connect(
                user=profile.username,
                password=password,
                dsn=self.make_dsn(profile),
                tcp_connect_timeout=10,
            )
        except DbError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _translate_error(exc) from exc
        conn.module = "db-exp"
        conn.action = "export"
        with conn.cursor() as cur:
            # 誤更新を防ぐため読み取り専用トランザクションで開始する
            cur.execute("SET TRANSACTION READ ONLY")
        return conn

    def server_version(self, conn: Any) -> str:
        return f"Oracle {conn.version}"

    def default_schema(self, conn: Any, profile: ConnectionInput) -> str:
        with conn.cursor() as cur:
            cur.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
            row = cur.fetchone()
        return row[0] if row else profile.username.upper()

    def list_schemas(self, conn: Any) -> list[str]:
        with conn.cursor() as cur:
            try:
                # 12c 以降: Oracle 管理スキーマ（SYS, SYSTEM 等）を除外
                cur.execute(
                    "SELECT username FROM all_users WHERE oracle_maintained = 'N' ORDER BY username"
                )
            except oracledb.DatabaseError:
                cur.execute("SELECT username FROM all_users ORDER BY username")
            return [r[0] for r in cur.fetchall()]

    def list_tables(self, conn: Any, schema: str) -> list[TableInfo]:
        sql = """
            SELECT o.object_name,
                   CASE o.object_type WHEN 'MATERIALIZED VIEW' THEN 'MVIEW' ELSE o.object_type END,
                   c.comments,
                   t.num_rows
              FROM all_objects o
              LEFT JOIN all_tab_comments c
                ON c.owner = o.owner AND c.table_name = o.object_name
              LEFT JOIN all_tables t
                ON t.owner = o.owner AND t.table_name = o.object_name
             WHERE o.owner = :owner
               AND o.object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW')
               AND o.object_name NOT LIKE 'BIN$%'
               AND (t.nested IS NULL OR t.nested = 'NO')
             ORDER BY o.object_name
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql, owner=schema)
                rows = cur.fetchall()
        except oracledb.DatabaseError as exc:
            raise _translate_error(exc) from exc
        # マテリアライズド・ビューは all_objects に TABLE と MVIEW の 2 件出るため集約
        result: dict[str, TableInfo] = {}
        for name, otype, comment, num_rows in rows:
            if name in result and otype != "MVIEW":
                continue
            result[name] = TableInfo(
                schema_name=schema,
                name=name,
                table_type=otype,
                comment=comment,
                num_rows=int(num_rows) if num_rows is not None else None,
            )
        return list(result.values())

    def list_columns(self, conn: Any, schema: str, table: str) -> list[ColumnInfo]:
        sql = """
            SELECT c.column_name,
                   cc.comments,
                   c.data_type,
                   c.data_length,
                   c.char_length,
                   c.char_used,
                   c.data_precision,
                   c.data_scale,
                   c.nullable,
                   c.column_id,
                   CASE WHEN pk.column_name IS NOT NULL THEN 1 ELSE 0 END
              FROM all_tab_columns c
              LEFT JOIN all_col_comments cc
                ON cc.owner = c.owner AND cc.table_name = c.table_name AND cc.column_name = c.column_name
              LEFT JOIN (
                    SELECT acc.column_name
                      FROM all_constraints ac
                      JOIN all_cons_columns acc
                        ON acc.owner = ac.owner AND acc.constraint_name = ac.constraint_name
                     WHERE ac.owner = :owner AND ac.table_name = :tname AND ac.constraint_type = 'P'
                   ) pk
                ON pk.column_name = c.column_name
             WHERE c.owner = :owner AND c.table_name = :tname
             ORDER BY c.column_id
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql, owner=schema, tname=table)
                rows = cur.fetchall()
        except oracledb.DatabaseError as exc:
            raise _translate_error(exc) from exc
        if not rows:
            raise DbError(f"表 {schema}.{table} が見つからないか、列を参照する権限がありません。")
        columns = []
        for (name, comment, dtype, dlen, clen, cused, prec, scale, nullable, pos, is_pk) in rows:
            columns.append(
                ColumnInfo(
                    name=name,
                    comment=comment,
                    data_type=self._format_type(dtype, dlen, clen, cused, prec, scale),
                    nullable=nullable == "Y",
                    is_pk=bool(is_pk),
                    position=int(pos),
                )
            )
        return columns

    @staticmethod
    def _format_type(dtype: str, dlen: Any, clen: Any, cused: Any, prec: Any, scale: Any) -> str:
        if dtype in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):
            unit = " CHAR" if cused == "C" and dtype in ("VARCHAR2", "CHAR") else ""
            length = clen if cused == "C" or dtype.startswith("N") else dlen
            return f"{dtype}({length}{unit})"
        if dtype == "NUMBER" and prec is not None:
            return f"NUMBER({prec},{scale})" if scale else f"NUMBER({prec})"
        if dtype == "RAW":
            return f"RAW({dlen})"
        return dtype

    def apply_limit(self, sql: str, limit: int) -> str:
        # 11g でも動作するよう ROWNUM で件数制限する
        return f"SELECT * FROM ({sql}) WHERE ROWNUM <= {int(limit)}"

    def open_stream(self, conn: Any, sql: str) -> Any:
        cur = conn.cursor()
        cur.arraysize = 5000
        cur.prefetchrows = 5001
        try:
            cur.execute(sql)
        except oracledb.DatabaseError as exc:
            cur.close()
            raise _translate_error(exc) from exc
        return cur
