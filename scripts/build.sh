#!/usr/bin/env bash
# ============================================================
#  DBエクスポートツール ビルドスクリプト（Linux / macOS 用）
#  実行すると dist/db-exp が生成されます。
#  ※ PyInstaller はクロスコンパイル非対応のため、
#    Windows 用 exe は Windows 上で scripts\build.bat を実行してください。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/3] フロントエンドをビルドしています..."
(cd frontend && npm ci && npm run build)

echo "[2/3] Python 仮想環境を準備しています..."
cd backend
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt

echo "[3/3] 実行ファイルを生成しています..."
.venv/bin/pyinstaller --noconfirm --distpath ../dist db_exp.spec

echo
echo "ビルドが完了しました: $(cd .. && pwd)/dist/db-exp"
