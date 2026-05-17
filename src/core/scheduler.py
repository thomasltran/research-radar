"""
scheduler.py - Pipeline schedule management and background polling loop.

Extracted from web_server.py startup/shutdown event handlers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from src.services.pipeline_service import (
    enabled_sources,
    scan_since,
    sources_for_mode,
    spawn_pipeline_run,
)

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PIPELINE_SCHEDULE_PATH = ROOT_DIR / "data" / "pipeline_schedule.json"


# ---------------------------------------------------------------------------
# Schedule persistence
# ---------------------------------------------------------------------------

def schedule_defaults() -> dict:
    return {"enabled": False, "time": "09:00", "source_mode": "both",
            "last_started_at": None, "skip_due_before": None}


def load_schedule() -> dict:
    if not PIPELINE_SCHEDULE_PATH.exists():
        return schedule_defaults()
    try:
        data = json.loads(PIPELINE_SCHEDULE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return schedule_defaults()
    return {**schedule_defaults(), **data}


def save_schedule(schedule: dict) -> dict:
    PIPELINE_SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = {**schedule_defaults(), **schedule}
    PIPELINE_SCHEDULE_PATH.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return normalized


def parse_schedule_time(value: str) -> dt_time:
    hour, minute = value.split(":", 1)
    return dt_time(hour=int(hour), minute=int(minute))


def last_due_time(schedule: dict, now: datetime) -> datetime | None:
    if not schedule.get("enabled"):
        return None
    local_now = now.astimezone()
    scheduled_time = parse_schedule_time(schedule.get("time") or "09:00")
    due_local = datetime.combine(local_now.date(), scheduled_time, tzinfo=local_now.tzinfo)
    if due_local > local_now:
        due_local -= timedelta(days=1)
    return due_local.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Scheduler tick
# ---------------------------------------------------------------------------

def maybe_start_due_schedule() -> None:
    try:
        from src.dependencies import get_conn  # noqa: PLC0415 (avoid circular at module load)
        conn = get_conn()
        running = conn.execute("SELECT id FROM pipeline_runs WHERE status = 'running' LIMIT 1").fetchone()
        if running:
            return
        schedule = load_schedule()
        now = datetime.now(timezone.utc)
        due = last_due_time(schedule, now)
        if not due:
            return
        for marker in (schedule.get("last_started_at"), schedule.get("skip_due_before")):
            if marker and datetime.fromisoformat(marker) >= due:
                return
        sources = sources_for_mode(schedule.get("source_mode") or "both")
        result = spawn_pipeline_run(
            conn,
            run_type="scheduled",
            source_mode=schedule.get("source_mode") or "both",
            scan_start=scan_since(conn, sources),
            scan_end=now.isoformat(),
        )
        save_schedule({**schedule, "last_started_at": now.isoformat(), "last_run_id": result["run_id"]})
    except Exception:
        logger.exception("Scheduled pipeline check failed")


# ---------------------------------------------------------------------------
# Lifespan helpers (called from web_server.py)
# ---------------------------------------------------------------------------

async def start_scheduler(app_state) -> None:
    maybe_start_due_schedule()

    async def _loop():
        while True:
            await asyncio.sleep(60)
            maybe_start_due_schedule()

    app_state.scheduler_task = asyncio.create_task(_loop())


async def stop_scheduler(app_state) -> None:
    task = getattr(app_state, "scheduler_task", None)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
