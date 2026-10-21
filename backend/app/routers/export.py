"""プレビュー・エクスポート・マスキング規則 API。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import exporter, store
from ..db import DbError
from ..masking import RULE_DEFINITIONS, build_masker
from ..schemas import (
    ExportJobStatus,
    ExportRequest,
    MaskTestRequest,
    PreviewRequest,
    PreviewResult,
)

router = APIRouter(prefix="/api", tags=["エクスポート"])



@router.get("/masking/rules")
def masking_rules() -> list[dict]:
    return RULE_DEFINITIONS


@router.post("/masking/test")
def masking_test(req: MaskTestRequest) -> dict:
    """マスキング規則の動作確認（画面上のサンプル表示用）。"""
    try:
        masker = build_masker(req.rule, req.hash_salt)
    except ValueError as exc:
        raise DbError(str(exc)) from exc
    result = masker(req.value) if masker else req.value
    return {"result": exporter.to_json_value(result)}


@router.post("/preview", response_model=PreviewResult)
def preview(req: PreviewRequest) -> PreviewResult:
    """マスキング適用後のデータを先頭から数十件取得する。"""
    spec = req.table
    with store.open_session(req.connection_id) as (dialect, conn, _):
        meta = dialect.list_columns(conn, spec.schema_name, spec.table)
        columns = exporter.prepare_columns(spec, meta, req.options)
        cur = dialect.open_stream(conn, dialect.build_select(spec, limit=req.limit))
        try:
            raw = cur.fetchmany(req.limit)
        finally:
            cur.close()
    rows = [[exporter.to_json_value(v) for v in exporter.transform_row(r, columns)] for r in raw]
    headers = exporter.header_rows(columns, "physical")[0]
    return PreviewResult(columns=headers, rows=rows)


@router.post("/export", response_model=ExportJobStatus)
def start_export(req: ExportRequest) -> ExportJobStatus:
    # 接続済みかどうかを先に確認し、ジョブ開始前にエラーを返す
    store.get_input(req.connection_id)
    return exporter.start_export(req).to_status()


@router.get("/export/{job_id}", response_model=ExportJobStatus)
def export_status(job_id: str) -> ExportJobStatus:
    return exporter.get_job(job_id).to_status()


@router.post("/export/{job_id}/cancel", response_model=ExportJobStatus)
def export_cancel(job_id: str) -> ExportJobStatus:
    return exporter.cancel_job(job_id).to_status()


@router.get("/export/{job_id}/download")
def export_download(job_id: str) -> FileResponse:
    job = exporter.get_job(job_id)
    if job.status != "done" or not job.path.exists():
        raise DbError("ダウンロードできるファイルがありません（未完了または保持期間切れ）。")
    # 日本語ファイル名は RFC 5987（filename*=UTF-8''...）形式で送られる
    media_type = exporter.MEDIA_TYPES.get(job.path.suffix, "application/octet-stream")
    return FileResponse(job.path, media_type=media_type, filename=job.file_name)
