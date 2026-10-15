"""アプリケーション全体の設定値とパス解決。

exe（PyInstaller）として実行された場合と、ソースから実行された場合で
静的ファイルの配置場所が異なるため、ここで吸収する。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def is_frozen() -> bool:
    """PyInstaller でビルドされた exe として実行中かどうか。"""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_dir() -> Path:
    """同梱リソース（フロントエンドのビルド成果物など）の基準ディレクトリ。"""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # ソース実行時は backend/ を基準とする
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    """フロントエンド（React）のビルド成果物ディレクトリ。"""
    if is_frozen():
        return resource_dir() / "static"
    return resource_dir().parent / "frontend" / "dist"


def data_dir() -> Path:
    """接続情報・設定・一時ファイルを保存するユーザー領域。

    Windows: %APPDATA%\\db-exp
    その他 : ~/.db-exp
    環境変数 DBEXP_DATA_DIR で上書き可能。
    """
    override = os.environ.get("DBEXP_DATA_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "db-exp"
    else:
        path = Path.home() / ".db-exp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_dir() -> Path:
    """エクスポート中・完了済みの Excel ファイルを一時保存するディレクトリ。"""
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# settings.json（任意）
# ---------------------------------------------------------------------------
# 例:
# {
#   "oracle_client_lib_dir": "C:\\oracle\\instantclient_19_20",
#   "port": 8765
# }

DEFAULT_SETTINGS: dict[str, Any] = {
    # Oracle Instant Client のパス。指定時は Thick モードで接続する
    # （Oracle 11g など Thin モード非対応の古い DB 向け）。
    "oracle_client_lib_dir": None,
    # 待ち受けポート（使用中の場合は自動で空きポートを探す）
    "port": 8765,
    # 完了済みエクスポートファイルを保持する時間（秒）
    "export_retention_seconds": 60 * 60 * 6,
}


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    """settings.json と環境変数を読み込み、既定値とマージして返す。"""
    settings = dict(DEFAULT_SETTINGS)
    path = settings_path()
    if path.exists():
        try:
            settings.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # 壊れた設定ファイルで起動不能にならないよう、既定値で続行する
            pass
    env_lib = os.environ.get("DBEXP_ORACLE_CLIENT_DIR")
    if env_lib:
        settings["oracle_client_lib_dir"] = env_lib
    env_port = os.environ.get("DBEXP_PORT")
    if env_port and env_port.isdigit():
        settings["port"] = int(env_port)
    return settings
