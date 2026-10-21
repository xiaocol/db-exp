"""起動スクリプト（exe のエントリーポイント）。

ローカル（127.0.0.1）でサーバーを起動し、既定のブラウザで画面を開く。
コンソールウィンドウを閉じるとアプリケーションも終了する。

使い方:
    python run.py [--port 8765] [--no-browser]
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser


def _ensure_streams() -> None:
    """--noconsole でビルドされた場合でもログ出力で落ちないようにする。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _find_free_port(preferred: int) -> int:
    """希望ポートが使用中なら、空いているポートを探す。"""
    for port in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    _ensure_streams()
    import uvicorn

    from app.config import data_dir, load_settings
    from app.main import app

    parser = argparse.ArgumentParser(description="db-exp マスキング出力ツール")
    parser.add_argument("--port", type=int, default=None, help="待ち受けポート（既定: 8765）")
    parser.add_argument("--no-browser", action="store_true", help="起動時にブラウザを開かない")
    args = parser.parse_args()

    settings = load_settings()
    port = _find_free_port(args.port or int(settings.get("port") or 8765))
    url = f"http://127.0.0.1:{port}/"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("=" * 60)
    print(" db-exp マスキング出力ツール")
    print(f"   画面URL   : {url}")
    print(f"   データ保存: {data_dir()}")
    print("   終了するにはこのウィンドウを閉じるか Ctrl+C を押してください。")
    print("=" * 60)

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # 外部から接続されないよう 127.0.0.1 のみで待ち受ける
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
