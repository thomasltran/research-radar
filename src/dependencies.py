"""
dependencies.py - Shared FastAPI dependency functions.
"""

from __future__ import annotations

from src import db


def get_conn():
    """Return a DB connection with schema initialised and stale runs reconciled.

    Import and call ``_reconcile_stale_pipeline_runs`` lazily to avoid a
    circular import with pipeline_service at module load time.
    """
    from src.services.pipeline_service import reconcile_stale_pipeline_runs  # noqa: PLC0415

    conn = db.get_connection()
    db.init_schema(conn)
    db.initialize_read_state(conn)
    reconcile_stale_pipeline_runs(conn)
    return conn
