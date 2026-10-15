"""DB 種別ごとの差異を吸収する方言（Dialect）の基底クラス。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator

from ..schemas import ColumnInfo, ConnectionInput, TableExportSpec, TableInfo


class DbError(Exception):
    """利用者に表示してよい DB 関連エラー。"""


_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_FORBIDDEN_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COMMIT|ROLLBACK|EXEC|EXECUTE|CALL)\b",
    re.I,
)


def validate_fragment(fragment: str | None, label: str) -> str | None:
    """WHERE / ORDER BY に入力された SQL 断片の簡易チェック。

    接続自体を読み取り専用にしているが、誤操作防止のため
    文の区切り（;）やコメント、更新系キーワードを含むものは拒否する。
    文字列リテラル内（'...'）の記号・単語は対象外。
    """
    if fragment is None:
        return None
    text = fragment.strip().rstrip(";").strip()
    if not text:
        return None
    stripped = _STRING_LITERAL.sub("''", text)
    if ";" in stripped or "--" in stripped or "/*" in stripped:
        raise DbError(f"{label}に「;」やコメントは使用できません。")
    if _FORBIDDEN_WORDS.search(stripped):
        raise DbError(f"{label}に更新系のキーワードは使用できません。")
    return text


class Dialect(ABC):
    """DB 方言の共通インターフェース。"""

    db_type: str
    default_port: int

    # ---- 接続 ----------------------------------------------------------

    @abstractmethod
    def connect(self, profile: ConnectionInput, password: str) -> Any:
        """DB-API 互換の接続を返す（読み取り専用に設定済みであること）。"""

    @contextmanager
    def session(self, profile: ConnectionInput, password: str) -> Iterator[Any]:
        conn = self.connect(profile, password)
        try:
            yield conn
        finally:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            conn.close()

    @abstractmethod
    def server_version(self, conn: Any) -> str: ...

    # ---- メタデータ ----------------------------------------------------

    @abstractmethod
    def default_schema(self, conn: Any, profile: ConnectionInput) -> str: ...

    @abstractmethod
    def list_schemas(self, conn: Any) -> list[str]: ...

    @abstractmethod
    def list_tables(self, conn: Any, schema: str) -> list[TableInfo]: ...

    @abstractmethod
    def list_columns(self, conn: Any, schema: str, table: str) -> list[ColumnInfo]: ...

    # ---- SQL 生成 ------------------------------------------------------

    def quote_ident(self, name: str) -> str:
        """識別子をダブルクォートで囲む。メタデータから取得した名前のみを渡すこと。"""
        if '"' in name or "\x00" in name:
            raise DbError(f"不正な識別子です: {name}")
        return f'"{name}"'

    def _from_clause(self, spec: TableExportSpec) -> str:
        return f"{self.quote_ident(spec.schema_name)}.{self.quote_ident(spec.table)}"

    def _where_order(self, spec: TableExportSpec) -> tuple[str, str]:
        where = validate_fragment(spec.where, "抽出条件(WHERE)")
        order = validate_fragment(spec.order_by, "並び順(ORDER BY)")
        return (f" WHERE {where}" if where else "", f" ORDER BY {order}" if order else "")

    def build_select(self, spec: TableExportSpec, limit: int | None = None) -> str:
        cols = ", ".join(self.quote_ident(c.name) for c in spec.columns)
        where, order = self._where_order(spec)
        sql = f"SELECT {cols} FROM {self._from_clause(spec)}{where}{order}"
        # プレビュー件数と最大出力件数のうち小さい方を採用する
        limits = [x for x in (limit, spec.max_rows) if x]
        return self.apply_limit(sql, min(limits)) if limits else sql

    def build_count(self, spec: TableExportSpec) -> str:
        where, _ = self._where_order(spec)
        return f"SELECT COUNT(*) FROM {self._from_clause(spec)}{where}"

    @abstractmethod
    def apply_limit(self, sql: str, limit: int) -> str: ...

    # ---- データ取得 ----------------------------------------------------

    @abstractmethod
    def open_stream(self, conn: Any, sql: str) -> Any:
        """大量件数を少しずつ取得するためのカーソルを返す（fetchmany で読む）。"""
