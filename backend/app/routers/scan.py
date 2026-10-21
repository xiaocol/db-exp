"""自動判定（DB の一括スキャン・ドキュメントのスキャン）と判定結果一覧の API。"""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, Response

from .. import dbscan, documents, store
from ..categories import category_list
from ..report import build_report_xlsx
from ..schemas import DbScanRequest, DbScanStatus, DocExportRequest, DocScanResult, ReportRequest

router = APIRouter(prefix="/api", tags=["自動判定"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(name: str) -> dict[str, str]:
    # 日本語のファイル名は RFC 5987 形式で送る
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}


@router.get("/masking/categories")
def categories() -> list[dict]:
    return category_list()


# ---- DB ----


@router.post("/connections/{conn_id}/scan", response_model=DbScanStatus)
def start_db_scan(conn_id: str, req: DbScanRequest) -> DbScanStatus:
    store.get_input(conn_id)
    return dbscan.start_scan(conn_id, req).to_status()


@router.get("/scan/{job_id}", response_model=DbScanStatus)
def db_scan_status(job_id: str) -> DbScanStatus:
    return dbscan.get_job(job_id).to_status()


@router.post("/scan/{job_id}/cancel", response_model=DbScanStatus)
def db_scan_cancel(job_id: str) -> DbScanStatus:
    return dbscan.cancel(job_id).to_status()


# ---- ドキュメント ----


@router.post("/documents/scan", response_model=DocScanResult)
async def scan_documents(files: list[UploadFile] = File(...)) -> DocScanResult:
    payload = [(f.filename or "file", await f.read()) for f in files]
    # 判定は CPU 処理のため、イベントループを止めないようスレッドで実行する
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(documents.scan_files, payload)


@router.post("/documents/{scan_id}/export")
def export_documents(scan_id: str, req: DocExportRequest) -> FileResponse:
    path = documents.export_zip(scan_id, req.decisions, req.hash_salt)
    name = f"マスキング済み_{dt.datetime.now():%Y%m%d_%H%M%S}.zip"
    return FileResponse(path, media_type="application/zip", filename=name)


@router.delete("/documents/{scan_id}")
def delete_documents(scan_id: str) -> dict:
    documents.delete_scan(scan_id)
    return {"ok": True}


# ---- 判定結果一覧 ----


@router.post("/report")
def report(req: ReportRequest) -> Response:
    data = build_report_xlsx(req.title, req.findings, req.decisions, req.source_label)
    name = f"{req.title}_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return Response(data, media_type=XLSX, headers=_attachment(name))
