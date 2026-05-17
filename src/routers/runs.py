"""routers/runs.py - Pipeline run list and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.dependencies import get_conn
from src.services.graph_service import digest_for_run, stage_snapshot
from src.services.pipeline_service import pipeline_log_path
from src.services.search_service import fetch_paper_cards

router = APIRouter()


def _run_paper_join_condition() -> str:
    return """
        (
            p.run_id = pr.id
            OR (
                pr.run_type = 'bootstrap'
                AND p.run_id IS NULL
                AND p.source = 'bootstrap'
            )
        )
    """


@router.get("/api/runs")
def list_runs():
    conn = get_conn()
    run_rows = conn.execute(f"""
        SELECT pr.*,
               COUNT(p.id) AS ingested_count,
               SUM(CASE WHEN p.id IS NOT NULL AND COALESCE(prs.read, 0) = 0 THEN 1 ELSE 0 END) AS unread_count
        FROM pipeline_runs pr
        LEFT JOIN papers p ON {_run_paper_join_condition()}
        LEFT JOIN paper_read_state prs ON prs.paper_id = p.id
        GROUP BY pr.id
        ORDER BY pr.started_at DESC
    """).fetchall()
    runs = []
    for row in run_rows:
        run = dict(row)
        digest_date, digest = digest_for_run(run) if run.get("status") == "success" else (None, None)
        runs.append({
            **run,
            "digest_date": digest_date,
            "digest_available": digest is not None,
            "log_available": pipeline_log_path(run["id"]).exists(),
            "stages": stage_snapshot(run),
        })

    return {"runs": runs}


@router.get("/api/runs/{run_id}")
def get_run(run_id: str):
    conn = get_conn()
    try:
        numeric_run_id = int(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid run id") from exc
    row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (numeric_run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    run_data = dict(row)
    digest_date, digest = digest_for_run(run_data) if run_data.get("status") == "success" else (None, None)
    run_number = run_data.get("run_number") or run_data['id']
    run_title = f"Pipeline Run {run_number}"
    if run_data.get("run_type") == "bootstrap":
        run_title = f"Bootstrap Job {run_number}"
    elif run_data.get("run_type") == "relink":
        run_title = f"Relink Job {run_number}"
    elif run_data.get("run_type") == "reanalyze":
        run_title = f"Reanalysis Job {run_number}"
    run_data.update({
        "title": run_title,
        "digest": digest or "",
        "digest_date": digest_date,
        "digest_available": digest is not None,
        "log_available": pipeline_log_path(run_data["id"]).exists(),
        "stages": stage_snapshot(run_data),
    })
    return {
        "report": run_data,
        "papers": fetch_paper_cards(conn, run_id="seed" if run_data.get("run_type") == "bootstrap" else run_id, sort="relevance"),
    }
