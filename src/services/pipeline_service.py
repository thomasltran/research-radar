"""
pipeline_service.py - Subprocess spawning, process management, and pipeline
run lifecycle helpers extracted from web_server.py.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.config import load_config

logger = logging.getLogger(__name__)
_CONFIG = load_config()

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PIPELINE_LOG_DIR = ROOT_DIR / "data" / "pipeline_logs"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def pipeline_log_path(run_id: int | str) -> Path:
    return PIPELINE_LOG_DIR / f"{run_id}.log"


def pipeline_pid_path(run_id: int | str) -> Path:
    return PIPELINE_LOG_DIR / f"{run_id}.pid"


def get_running_pipeline_run(conn) -> dict | None:
    row = conn.execute(
        "SELECT id FROM pipeline_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def ensure_no_running_pipeline(conn) -> None:
    running = get_running_pipeline_run(conn)
    if running:
        raise RuntimeError(f"Pipeline run {running['id']} is already running")


# ---------------------------------------------------------------------------
# Source / scan helpers
# ---------------------------------------------------------------------------

def sources_for_mode(source_mode: str | None = None) -> list[str]:
    source_mode = (source_mode or os.getenv("FETCH_SOURCE", _CONFIG.str("pipeline.default_fetch_source", "both"))).lower()
    if source_mode == "arxiv":
        return ["arxiv"]
    if source_mode in ("s2", "semantic_scholar"):
        return ["semantic_scholar"]
    return ["arxiv", "semantic_scholar"]


def enabled_sources() -> list[str]:
    return sources_for_mode()


def scan_since(conn, sources: list[str] | None = None) -> str | None:
    last_runs = [
        ts for ts in (db.get_last_successful_run(conn, source) for source in (sources or enabled_sources()))
        if ts
    ]
    return min(last_runs) if last_runs else None


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reconcile_stale_pipeline_runs(conn) -> None:
    rows = conn.execute("SELECT id FROM pipeline_runs WHERE status = 'running'").fetchall()
    for row in rows:
        pid_path = pipeline_pid_path(row["id"])
        if not pid_path.exists():
            db.complete_pipeline_run(conn, row["id"], "cancelled",
                                     error_details="No pid file found during startup reconciliation")
            continue
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            db.complete_pipeline_run(conn, row["id"], "cancelled",
                                     error_details="Invalid pid file during startup reconciliation")
            continue
        if not _process_exists(pid):
            db.complete_pipeline_run(conn, row["id"], "cancelled",
                                     error_details=f"Process {pid} was not running during startup reconciliation")


# ---------------------------------------------------------------------------
# Run spawning
# ---------------------------------------------------------------------------

def spawn_pipeline_run(
    conn,
    *,
    run_type: str,
    source_mode: str,
    scan_start: str | None,
    scan_end: str | None,
) -> dict:
    if source_mode not in {"both", "arxiv", "semantic_scholar", "s2"}:
        raise ValueError("source_mode must be both, arxiv, or semantic_scholar")

    sources = sources_for_mode(source_mode)
    run_id = db.create_pipeline_run(conn, run_type)
    PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = pipeline_log_path(run_id)
    pid_path = pipeline_pid_path(run_id)
    effective_start = scan_start or scan_since(conn, sources)
    effective_end = scan_end or datetime.now(timezone.utc).isoformat()
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "FETCH_SOURCE": source_mode,
        "PIPELINE_SCAN_END": effective_end,
    }
    if effective_start:
        env["PIPELINE_SCAN_START"] = effective_start

    row = conn.execute("SELECT run_number FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    run_number = row["run_number"] if row else run_id

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"Starting pipeline run {run_number} ({run_type})\n")
        log_file.write(f"Sources: {', '.join(sources)}\n")
        log_file.write(f"Scan window: {effective_start or 'beginning'} -> {effective_end}\n")
        log_file.flush()
        process = subprocess.Popen(
            [sys.executable, "-m", "src.main", run_type, "--run-id", str(run_id)],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        pid_path.write_text(str(process.pid), encoding="utf-8")

    return {"run_id": run_id, "pid": process.pid, "log_path": str(log_path)}


def spawn_maintenance_run(conn, mode: str = "relink", working_set_only: bool = False, all_papers: bool = False) -> dict:
    mode = (mode or "relink").strip().lower()
    if mode not in {"relink", "reanalyze"}:
        raise ValueError("mode must be relink or reanalyze")

    run_id = db.create_pipeline_run(conn, mode)
    PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = pipeline_log_path(run_id)
    pid_path = pipeline_pid_path(run_id)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    stages = "rescore -> rebuild index -> organize workspace -> refresh relationships"
    if mode == "reanalyze":
        stages = "rebuild index -> recompress active papers -> rerun analysis -> verify -> regenerate notes"

    row = conn.execute("SELECT run_number FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    run_number = row["run_number"] if row else run_id

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"Starting {mode} run {run_number}\n")
        log_file.write(f"Stages: {stages}\n")
        log_file.flush()
        cmd = [sys.executable, "-m", "src.maintenance", mode, "--run-id", str(run_id)]
        if working_set_only:
            cmd.append("--working-set-only")
        if all_papers:
            cmd.append("--all-papers")
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        pid_path.write_text(str(process.pid), encoding="utf-8")

    return {"run_id": run_id, "pid": process.pid, "log_path": str(log_path)}


def spawn_bootstrap_run(conn) -> dict:
    run_type = "bootstrap"
    run_id = db.create_pipeline_run(conn, run_type)
    PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = pipeline_log_path(run_id)
    pid_path = pipeline_pid_path(run_id)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    row = conn.execute("SELECT run_number FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    run_number = row["run_number"] if row else run_id

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"Starting {run_type} run {run_number}\n")
        log_file.write(f"Stages: fetch seeds -> embed -> compress -> build indices\n")
        log_file.flush()
        process = subprocess.Popen(
            [sys.executable, "-m", "scripts.bootstrap", "--run-id", str(run_id)],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        pid_path.write_text(str(process.pid), encoding="utf-8")

    return {"run_id": run_id, "pid": process.pid, "log_path": str(log_path)}


def spawn_relink_run(conn) -> dict:
    return spawn_maintenance_run(conn, "relink")


def cancel_run(conn, run_id: int) -> dict:
    """Send SIGTERM to the process group and return a status dict."""
    row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return {"run_id": run_id, "status": "not_found"}
    if row["status"] != "running":
        return {"run_id": run_id, "status": row["status"]}

    pid_path = pipeline_pid_path(run_id)
    log_path = pipeline_log_path(run_id)
    if not pid_path.exists():
        db.complete_pipeline_run(conn, run_id, "cancelled")
        return {"run_id": run_id, "status": "cancelled", "detail": "No pid file found"}

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        db.complete_pipeline_run(conn, run_id, "cancelled", error_details="Invalid pid file during cancellation")
        return {"run_id": run_id, "status": "cancelled", "detail": "Invalid pid file"}

    try:
        if not _process_exists(pid):
            db.complete_pipeline_run(conn, run_id, "cancelled", error_details="Process was already stopped")
            return {"run_id": run_id, "status": "cancelled", "detail": "Process was already stopped"}
        os.killpg(pid, signal.SIGTERM)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("\nCancellation requested from frontend.\n")
        db.complete_pipeline_run(conn, run_id, "cancelled", error_details="Cancellation requested from frontend")
    except ProcessLookupError:
        db.complete_pipeline_run(conn, run_id, "cancelled", error_details="Process was already stopped")
    except PermissionError:
        logger.exception("Permission denied cancelling run %s", run_id)
        return {"run_id": run_id, "status": "running", "detail": "Permission denied cancelling process"}
    return {"run_id": run_id, "status": "cancelled"}
