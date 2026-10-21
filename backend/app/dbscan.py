"""DB の一括スキャン。

スキーマ内の表（またはその一部）について、列情報と先頭のサンプル値を取得し、
列ごとにマスキング対象かどうかを判定する。表の数が多いと時間がかかるため、
エクスポートと同じくバックグラウンドで実行し、進捗をポーリングで取得する。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import store
from .db import DbError
from .detector import analyze_column, type_class
from .findings import column_finding
from .schemas import (
    ColumnInfo,
    ColumnSpec,
    DbScanRequest,
    DbScanStatus,
    Finding,
    ScannedTable,
    Suggestion,
    TableExportSpec,
)

log = logging.getLogger(__name__)


@dataclass
class ScanJob:
    job_id: str
    connection_id: str
    request: DbScanRequest
    status: str = "pending"
    message: str | None = None
    total_tables: int = 0
    done_tables: int = 0
    current_table: str | None = None
    tables: list[ScannedTable] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    finished_at: dt.datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_status(self) -> DbScanStatus:
        done = self.status == "done"
        return DbScanStatus(
            job_id=self.job_id,
            status=self.status,  # type: ignore[arg-type]
            message=self.message,
            schema_name=self.request.schema_name,
            total_tables=self.total_tables,
            done_tables=self.done_tables,
            current_table=self.current_table,
            # 結果は完了時のみ返す（ポーリングの通信量を抑えるため）
            tables=self.tables if done else [],
            findings=self.findings if done else [],
        )


_jobs: dict[str, ScanJob] = {}
_lock = threading.Lock()
_MAX_JOBS = 20


def get_job(job_id: str) -> ScanJob:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise DbError("指定されたスキャン処理が見つかりません。")
    return job


def start_scan(connection_id: str, req: DbScanRequest) -> ScanJob:
    job = ScanJob(job_id=uuid.uuid4().hex, connection_id=connection_id, request=req)
    with _lock:
        # 古い結果から捨てる（結果はメモリ上にのみ保持する）
        finished = sorted((j for j in _jobs.values() if j.finished_at), key=lambda j: j.finished_at)
        for old in finished[: max(0, len(_jobs) - _MAX_JOBS + 1)]:
            _jobs.pop(old.job_id, None)
        _jobs[job.job_id] = job
    threading.Thread(target=_run, args=(job,), name=f"scan-{job.job_id[:8]}", daemon=True).start()
    return job


def cancel(job_id: str) -> ScanJob:
    job = get_job(job_id)
    job.cancel_event.set()
    return job


def sample_rows(dialect: Any, conn: Any, schema: str, table: str, columns: list[ColumnInfo], limit: int) -> dict[str, list[Any]]:
    """先頭 limit 件のサンプル値を列ごとに取得する（バイナリ列は取得しない）。"""
    targets = [c for c in columns if type_class(c.data_type) != "binary"]
    if not targets:
        return {}
    spec = TableExportSpec(schema_name=schema, table=table, columns=[ColumnSpec(name=c.name) for c in targets])
    cur = dialect.open_stream(conn, dialect.build_select(spec, limit=limit))
    try:
        rows = cur.fetchmany(limit)
    finally:
        cur.close()
    return {c.name: [r[i] for r in rows] for i, c in enumerate(targets)}


def analyze_table(
    schema: str, table: str, columns: list[ColumnInfo], samples: dict[str, list[Any]]
) -> list[Finding]:
    """列ごとに判定し、ColumnInfo に判定結果を設定したうえで Finding を返す。"""
    findings: list[Finding] = []
    for col in columns:
        values = samples.get(col.name, [])
        verdict = analyze_column(col.name, col.comment, col.data_type, values, is_pk=col.is_pk)
        if verdict.level is None or verdict.rule is None:
            continue
        col.suggestion = Suggestion(
            category=verdict.category or "",
            label=verdict.label or "",
            score=verdict.score,
            level=verdict.level,
            rule=verdict.rule,
            reasons=verdict.reasons,
        )
        col.suggested_mask = verdict.rule if verdict.level == "auto" else None
        findings.append(
            column_finding(
                source="db",
                file=f"{schema}.{table}",
                column=col.name,
                comment=col.comment,
                data_type=col.data_type,
                is_pk=col.is_pk,
                verdict=verdict,
                samples=values,
            )
        )
    return findings


def _run(job: ScanJob) -> None:
    job.status = "running"
    req = job.request
    try:
        with store.open_session(job.connection_id) as (dialect, conn, _):
            tables = dialect.list_tables(conn, req.schema_name)
            if req.tables is not None:
                wanted = set(req.tables)
                tables = [t for t in tables if t.name in wanted]
            job.total_tables = len(tables)
            for t in tables:
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.message = "スキャンを中止しました。"
                    return
                job.current_table = t.name
                scanned = ScannedTable(schema_name=t.schema_name, table=t.name, table_type=t.table_type, comment=t.comment)
                try:
                    scanned.columns = dialect.list_columns(conn, t.schema_name, t.name)
                    samples = sample_rows(dialect, conn, t.schema_name, t.name, scanned.columns, req.sample_rows)
                    scanned.sampled_rows = max((len(v) for v in samples.values()), default=0)
                    job.findings.extend(analyze_table(t.schema_name, t.name, scanned.columns, samples))
                except DbError as exc:
                    scanned.error = str(exc)
                    dialect.recover(conn)
                except Exception as exc:  # noqa: BLE001 - 1 表の失敗で全体を止めない
                    log.exception("スキャン中にエラーが発生しました: %s.%s", t.schema_name, t.name)
                    scanned.error = f"予期しないエラー: {exc}"
                    dialect.recover(conn)
                job.tables.append(scanned)
                job.done_tables += 1
        auto = sum(1 for f in job.findings if f.level == "auto")
        review = len(job.findings) - auto
        errors = sum(1 for t in job.tables if t.error)
        job.message = f"{job.total_tables} 表をスキャンしました。マスキング対象 {auto} 列、要確認 {review} 列。"
        if errors:
            job.message += f"（{errors} 表は読み取れませんでした）"
        job.status = "done"
    except DbError as exc:
        job.status = "error"
        job.message = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("スキャン処理で予期しないエラーが発生しました")
        job.status = "error"
        job.message = f"予期しないエラーが発生しました: {exc}"
    finally:
        job.current_table = None
        job.finished_at = dt.datetime.now()
