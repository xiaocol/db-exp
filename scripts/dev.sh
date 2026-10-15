#!/usr/bin/env bash
# 開発用: バックエンド（:8765）とフロントエンド開発サーバー（:5173）を同時に起動する
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload) &
BACK=$!
trap 'kill $BACK' EXIT
cd frontend && npm run dev
