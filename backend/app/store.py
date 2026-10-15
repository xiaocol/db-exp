"""接続プロファイルの保存と、接続中セッション（パスワード）の管理。

- プロファイルは data_dir()/connections.json に保存する。
- パスワードは「パスワードを保存」を選んだ場合のみファイルに保存する
  （Windows ではユーザー領域 %APPDATA% 配下。平文に近い形式のため共用PCでは非推奨）。
- 保存しない場合、接続時に入力されたパスワードはプロセスのメモリ上にのみ保持する。
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .config import data_dir
from .db import DbError, get_dialect
from .schemas import ConnectionInput, ConnectionProfile

_lock = threading.RLock()
# 接続ID → パスワード（「接続」操作済みのもののみ）
_session_passwords: dict[str, str] = {}


def _path():
    return data_dir() / "connections.json"


def _encode(pw: str) -> str:
    # 画面のぞき見・誤表示対策の難読化であり、暗号化ではない
    return base64.b64encode(pw.encode("utf-8")).decode("ascii")


def _decode(token: str) -> str:
    return base64.b64decode(token.encode("ascii")).decode("utf-8")


def _load_raw() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_raw(items: list[dict[str, Any]]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _to_profile(item: dict[str, Any]) -> ConnectionProfile:
    data = {k: v for k, v in item.items() if k != "password_enc"}
    return ConnectionProfile(
        **data,
        has_saved_password=bool(item.get("password_enc")),
        connected=item["id"] in _session_passwords,
    )


def list_profiles() -> list[ConnectionProfile]:
    with _lock:
        return [_to_profile(i) for i in _load_raw()]


def get_input(conn_id: str) -> ConnectionInput:
    """保存済みプロファイルを接続用の入力モデルとして取得する。"""
    with _lock:
        for item in _load_raw():
            if item["id"] == conn_id:
                data = {k: v for k, v in item.items() if k != "password_enc"}
                pw = _decode(item["password_enc"]) if item.get("password_enc") else None
                return ConnectionInput(**data, password=pw)
    raise DbError("接続情報が見つかりません。")


def upsert(inp: ConnectionInput) -> ConnectionProfile:
    with _lock:
        items = _load_raw()
        conn_id = inp.id or uuid.uuid4().hex
        existing = next((i for i in items if i["id"] == conn_id), None)
        data = inp.model_dump(exclude={"password"})
        data["id"] = conn_id
        if inp.save_password:
            if inp.password:
                data["password_enc"] = _encode(inp.password)
            elif existing and existing.get("password_enc"):
                # パスワード欄が空のまま更新された場合は既存の保存値を維持
                data["password_enc"] = existing["password_enc"]
        if existing:
            items[items.index(existing)] = data
        else:
            items.append(data)
        _save_raw(items)
        # 接続設定が変わった可能性があるため、セッションは破棄する
        _session_passwords.pop(conn_id, None)
        return _to_profile(data)


def delete(conn_id: str) -> None:
    with _lock:
        items = [i for i in _load_raw() if i["id"] != conn_id]
        _save_raw(items)
        _session_passwords.pop(conn_id, None)


def resolve_password(inp: ConnectionInput, password: str | None) -> str:
    if password:
        return password
    if inp.password:
        return inp.password
    raise DbError("パスワードを入力してください。")


def mark_connected(conn_id: str, password: str) -> None:
    with _lock:
        _session_passwords[conn_id] = password


def disconnect(conn_id: str) -> None:
    with _lock:
        _session_passwords.pop(conn_id, None)


@contextmanager
def open_session(conn_id: str) -> Iterator[tuple[Any, Any, ConnectionInput]]:
    """接続済みプロファイルで DB セッションを開く。(dialect, conn, profile) を返す。"""
    inp = get_input(conn_id)
    with _lock:
        password = _session_passwords.get(conn_id)
    if password is None:
        raise DbError("未接続です。先に「接続」を行ってください。")
    dialect = get_dialect(inp.db_type)
    with dialect.session(inp, password) as conn:
        yield dialect, conn, inp
