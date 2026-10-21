"""FastAPI アプリケーション本体。

/api/*      : REST API
/ （その他）: React でビルドしたフロントエンド（SPA）を配信
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import load_settings, static_dir
from .db import DbError
from .db.oracle import init_thick_mode
from .routers import connections, export, scan

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = load_settings()
    init_thick_mode(settings.get("oracle_client_lib_dir"))

    app = FastAPI(title="マスキング出力ツール", version=__version__)
    # DNS リバインディング対策: localhost 以外の Host ヘッダーは拒否する
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # 他サイトのページからの更新系リクエスト（CSRF）を防ぐため、
        # 画面が付与する独自ヘッダーが無い POST/PUT/DELETE は拒否する
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-dbexp") != "1":
                return JSONResponse(status_code=403, content={"detail": "不正なリクエストです。"})
        return await call_next(request)

    app.include_router(connections.router)
    app.include_router(export.router)
    app.include_router(scan.router)

    @app.exception_handler(DbError)
    async def db_error_handler(_: Request, exc: DbError) -> JSONResponse:
        # 利用者向けのエラーは 400 として日本語メッセージを返す
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = static_dir()
    index = dist / "index.html"
    if not index.exists():
        log.warning("フロントエンドのビルド成果物が見つかりません: %s", dist)
        return
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # 実在するファイル（favicon 等）はそのまま返し、それ以外は index.html を返す
        target = (dist / path).resolve()
        if path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(index)


app = create_app()
