"""PostgreSQL 用の方言（psycopg 3）。"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from ..schemas import ColumnInfo, ConnectionInput, TableInfo
from .base import DbError, Dialect


def _translate_error(exc: Exception) -> DbError:
    text = str(exc).strip()
    hints = {
        "password authentication failed": "ユーザー名またはパスワードが正しくありません。",
        "does not exist": "指定したデータベース・表・列が存在しません。",
        "permission denied": "参照権限がありません。",
        "Connection refused": "DBに接続できません。ホスト名・ポートを確認してください。",
        "timeout expired": "接続がタイムアウトしました。ホスト名・ポート・ネットワークを確認してください。",
    }
    for key, hint in hints.items():
        if key in text:
            return DbError(f"{hint}\n({text})")
    return DbError(text)


_TABLE_TYPES = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MVIEW", "f": "FOREIGN"}


class PostgresDialect(Dialect):
    db_type = "postgresql"
    default_port = 5432

    def connect(self, profile: ConnectionInput, password: str) -> Any:
        if not profile.host or not profile.database:
            raise DbError("ホスト名とデータベース名を入力してください。")
        try:
            conn = psycopg.connect(
                host=profile.host,
                port=profile.port or self.default_port,
                dbname=profile.database,
                user=profile.username,
                password=password,
                connect_timeout=10,
                # 日本語データを確実に UTF-8 で受け取る
                client_encoding="UTF8",
                application_name="db-exp",
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_error(exc) from exc
        # 誤更新を防ぐため読み取り専用セッションにする
        conn.read_only = True
        return conn

    def server_version(self, conn: Any) -> str:
        v = conn.info.server_version
        return f"PostgreSQL {v // 10000}.{v % 10000}"

    def default_schema(self, conn: Any, profile: ConnectionInput) -> str:
        with conn.cursor() as cur:
            cur.execute("SELECT current_schema()")
            row = cur.fetchone()
        return row[0] if row and row[0] else "public"

    def list_schemas(self, conn: Any) -> list[str]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nspname FROM pg_namespace
                 WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema'
                   AND has_schema_privilege(oid, 'USAGE')
                 ORDER BY nspname
                """
            )
            return [r[0] for r in cur.fetchall()]

    def list_tables(self, conn: Any, schema: str) -> list[TableInfo]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname, c.relkind, obj_description(c.oid, 'pg_class'),
                       CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = %s
                   AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                   AND NOT c.relispartition
                 ORDER BY c.relname
                """,
                (schema,),
            )
            return [
                TableInfo(
                    schema_name=schema,
                    name=name,
                    table_type=_TABLE_TYPES.get(kind, kind),
                    comment=comment,
                    num_rows=num_rows,
                )
                for name, kind, comment, num_rows in cur.fetchall()
            ]

    def list_columns(self, conn: Any, schema: str, table: str) -> list[ColumnInfo]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.attname,
                       col_description(c.oid, a.attnum),
                       format_type(a.atttypid, a.atttypmod),
                       NOT a.attnotnull,
                       a.attnum,
                       EXISTS (
                           SELECT 1 FROM pg_index i
                            WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY(i.indkey)
                       )
                  FROM pg_attribute a
                  JOIN pg_class c ON c.oid = a.attrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = %s AND c.relname = %s
                   AND a.attnum > 0 AND NOT a.attisdropped
                 ORDER BY a.attnum
                """,
                (schema, table),
            )
            rows = cur.fetchall()
        if not rows:
            raise DbError(f"表 {schema}.{table} が見つからないか、列を参照する権限がありません。")
        return [
            ColumnInfo(name=n, comment=cm, data_type=t, nullable=nl, is_pk=pk, position=p)
            for n, cm, t, nl, p, pk in rows
        ]

    def apply_limit(self, sql: str, limit: int) -> str:
        return f"{sql} LIMIT {int(limit)}"

    def open_stream(self, conn: Any, sql: str) -> Any:
        # サーバーサイドカーソル（名前付き）で少しずつ取得し、メモリ使用量を抑える
        cur = conn.cursor(name=f"dbexp_{uuid.uuid4().hex[:12]}")
        cur.itersize = 5000
        try:
            cur.execute(sql)
        except Exception as exc:  # noqa: BLE001
            cur.close()
            conn.rollback()
            raise _translate_error(exc) from exc
        return cur
