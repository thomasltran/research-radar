"""routers/pipeline.py - Pipeline run, schedule, cancel, logs, and maintenance endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src import db
from src.core.scheduler import load_schedule, parse_schedule_time, save_schedule
from src.dependencies import get_conn
from src.schemas import MaintenanceRunRequest, PipelineRunRequest, PipelineScheduleUpdate
from src.services.pipeline_service import (
    cancel_run,
    ensure_no_running_pipeline,
    pipeline_log_path,
    scan_since,
    sources_for_mode,
    spawn_maintenance_run,
    spawn_pipeline_run,
    spawn_relink_run,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_idle(conn) -> None:
    try:
        ensure_no_running_pipeline(conn)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _server_error(exc: Exception, action: str) -> HTTPException:
    logger.exception("Failed to %s", action)
    return HTTPException(status_code=500, detail=f"Failed to {action}")


def _parse_iso_datetime(value: str | None, field_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be an ISO datetime") from exc


@router.get("/api/pipeline/preview")
def pipeline_preview(source_mode: str | None = None, scan_start: str | None = None, scan_end: str | None = None):
    conn = get_conn()
    sources = sources_for_mode(source_mode)
    return {
        "run_type": "manual",
        "source_mode": source_mode or "both",
        "sources": sources,
        "scan_since": scan_start or scan_since(conn, sources),
        "scan_until": scan_end or datetime.now(timezone.utc).isoformat(),
        "running": conn.execute("SELECT COUNT(*) AS count FROM pipeline_runs WHERE status = 'running'").fetchone()["count"],
        "schedule": load_schedule(),
    }


@router.post("/api/pipeline/run")
def start_pipeline(update: PipelineRunRequest):
    conn = get_conn()
    _ensure_idle(conn)
    run_type = update.run_type.strip() or "manual"
    scan_start = _parse_iso_datetime(update.scan_start, "scan_start")
    scan_end = _parse_iso_datetime(update.scan_end, "scan_end")
    if scan_start and scan_end and scan_start > scan_end:
        raise HTTPException(status_code=400, detail="scan_start must be before scan_end")
    try:
        result = spawn_pipeline_run(
            conn,
            run_type=run_type,
            source_mode=update.source_mode.strip().lower() or "both",
            scan_start=update.scan_start,
            scan_end=update.scan_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _server_error(exc, "start pipeline run") from exc
    return result


@router.get("/api/pipeline/schedule")
def get_pipeline_schedule():
    return {"schedule": load_schedule()}


@router.put("/api/pipeline/schedule")
def set_pipeline_schedule(update: PipelineScheduleUpdate):
    source_mode = update.source_mode.strip().lower() or "both"
    if source_mode not in {"both", "arxiv", "semantic_scholar", "s2"}:
        raise HTTPException(status_code=400, detail="source_mode must be both, arxiv, or semantic_scholar")
    try:
        parse_schedule_time(update.time)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="time must be HH:MM local time") from exc
    previous = load_schedule()
    now = datetime.now(timezone.utc)
    schedule = save_schedule({
        **previous,
        "enabled": update.enabled,
        "time": update.time,
        "source_mode": source_mode,
        "last_started_at": previous.get("last_started_at"),
        "skip_due_before": now.isoformat() if update.enabled else previous.get("skip_due_before"),
    })
    return {"schedule": schedule}


@router.post("/api/pipeline/runs/{run_id}/cancel")
def cancel_pipeline_run(run_id: int):
    conn = get_conn()
    result = cancel_run(conn, run_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@router.get("/api/pipeline/runs/{run_id}/logs")
def get_pipeline_logs(run_id: int, tail: int = 400):
    path = pipeline_log_path(run_id)
    if not path.exists():
        return {"run_id": run_id, "log": "", "exists": False}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"run_id": run_id, "log": "\n".join(lines[-tail:]), "exists": True}


@router.post("/api/workspace/relink")
def relink_workspace_endpoint():
    conn = get_conn()
    _ensure_idle(conn)
    try:
        return spawn_relink_run(conn)
    except Exception as exc:
        raise _server_error(exc, "start relink run") from exc


@router.post("/api/workspace/bootstrap")
def bootstrap_workspace_endpoint():
    conn = get_conn()
    _ensure_idle(conn)
    ws_count = conn.execute("SELECT COUNT(*) as count FROM papers WHERE in_working_set = 1").fetchone()["count"]
    if ws_count > 0:
        raise HTTPException(status_code=400, detail="Database already bootstrapped. Clear data to re-bootstrap.")
    try:
        from src.services.pipeline_service import spawn_bootstrap_run
        return spawn_bootstrap_run(conn)
    except Exception as exc:
        raise _server_error(exc, "start bootstrap run") from exc


@router.post("/api/workspace/maintenance")
def maintenance_workspace_endpoint(update: MaintenanceRunRequest):
    mode = update.mode
    conn = get_conn()
    _ensure_idle(conn)
    try:
        return spawn_maintenance_run(conn, mode, working_set_only=update.working_set_only, all_papers=update.all_papers)
    except Exception as exc:
        raise _server_error(exc, "start maintenance run") from exc
