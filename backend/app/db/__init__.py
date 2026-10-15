"""DB 接続・メタデータ取得の方言レイヤー。"""

from __future__ import annotations

from .base import DbError, Dialect
from .oracle import OracleDialect
from .postgres import PostgresDialect

_DIALECTS: dict[str, Dialect] = {
    "oracle": OracleDialect(),
    "postgresql": PostgresDialect(),
}


def get_dialect(db_type: str) -> Dialect:
    try:
        return _DIALECTS[db_type]
    except KeyError as exc:
        raise DbError(f"未対応のDB種別です: {db_type}") from exc


__all__ = ["DbError", "Dialect", "get_dialect"]
