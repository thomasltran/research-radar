"""
db.py — SQLite and FAISS index management.

Handles:
  - SQLite schema initialization (6 tables)
  - CRUD operations for papers, summaries, analyses, verifications
  - FAISS dual-index (all_papers + working_set) lifecycle
  - Working set ID mapping persistence
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from src import db_schema
from src.pipeline_policy import WORKING_SET_ENTRY_THRESHOLD
from src.services.analysis_normalization import normalize_analysis_payload, normalize_corrected_recommendation
from src.vector_store import (
    add_to_index,
    create_empty_index,
    load_embeddings,
    load_index,
    load_ws_id_map,
    save_embeddings,
    save_index,
    save_ws_id_map,
    search_index,
)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ──────────────────────────────────────────────
# SQLite helpers
# ──────────────────────────────────────────────

def get_db_path() -> Path:
    return DATA_DIR / "research.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a connection with row_factory set for dict-like access."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indices if they don't exist."""
    db_schema.init_schema(conn)
    repair_recommendation_policy(conn)


def repair_recommendation_policy(conn: sqlite3.Connection) -> None:
    """Bring old analysis rows in line with current recommendation gates."""
    conn.execute("""
        UPDATE analyses
        SET recommendation = 'track',
            recommendation_reason = TRIM(
                COALESCE(recommendation_reason, '') || ' Demoted from Review because relevance score '
                || COALESCE((
                    SELECT p.relevance_score FROM papers p WHERE p.id = analyses.paper_id
                ), 0)
                || ' is below the working-set threshold ' || ? || '.'
            )
        WHERE LOWER(COALESCE(recommendation, '')) = 'read'
          AND COALESCE((
              SELECT p.relevance_score FROM papers p WHERE p.id = analyses.paper_id
          ), 0) < ?
          AND COALESCE(recommendation_reason, '') NOT LIKE '%Demoted from Review%'
    """, (WORKING_SET_ENTRY_THRESHOLD, WORKING_SET_ENTRY_THRESHOLD))
    conn.commit()


def list_folders(conn: sqlite3.Connection) -> list[dict]:
    """Return user-created folders with paper counts."""
    init_schema(conn)
    rows = conn.execute("""
        SELECT pf.id, pf.name, pf.created_at, COUNT(pfm.paper_id) AS paper_count
        FROM paper_folders pf
        LEFT JOIN paper_folder_memberships pfm ON pfm.folder_id = pf.id
        GROUP BY pf.id
        ORDER BY pf.name COLLATE NOCASE ASC
    """).fetchall()
    return [dict(row) for row in rows]


def create_folder(conn: sqlite3.Connection, name: str) -> dict:
    """Create a paper folder or return the existing folder with the same name."""
    init_schema(conn)
    normalized = " ".join(name.strip().split())
    if not normalized:
        raise ValueError("Folder name is required")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO paper_folders (name, created_at) VALUES (?, ?)",
        (normalized, now),
    )
    conn.commit()
    row = conn.execute("""
        SELECT pf.id, pf.name, pf.created_at, COUNT(pfm.paper_id) AS paper_count
        FROM paper_folders pf
        LEFT JOIN paper_folder_memberships pfm ON pfm.folder_id = pf.id
        WHERE pf.name = ?
        GROUP BY pf.id
    """, (normalized,)).fetchone()
    return dict(row)


def get_paper_folders(conn: sqlite3.Connection, paper_id: str) -> list[dict]:
    """Return folders containing a paper."""
    init_schema(conn)
    rows = conn.execute("""
        SELECT pf.id, pf.name, pf.created_at
        FROM paper_folders pf
        JOIN paper_folder_memberships pfm ON pfm.folder_id = pf.id
        WHERE pfm.paper_id = ?
        ORDER BY pf.name COLLATE NOCASE ASC
    """, (paper_id,)).fetchall()
    return [dict(row) for row in rows]


def delete_folder(conn: sqlite3.Connection, folder_id: int) -> None:
    """Delete a user folder and its memberships."""
    init_schema(conn)
    conn.execute("DELETE FROM paper_folders WHERE id = ?", (folder_id,))
    conn.commit()


def set_paper_folder_membership(conn: sqlite3.Connection, folder_id: int, paper_id: str, in_folder: bool) -> None:
    """Add or remove a paper from a user folder."""
    init_schema(conn)
    if in_folder:
        conn.execute("""
            INSERT OR IGNORE INTO paper_folder_memberships (folder_id, paper_id, added_at)
            VALUES (?, ?, ?)
        """, (folder_id, paper_id, datetime.now(timezone.utc).isoformat()))
    else:
        conn.execute(
            "DELETE FROM paper_folder_memberships WHERE folder_id = ? AND paper_id = ?",
            (folder_id, paper_id),
        )
    conn.commit()


# ──────────────────────────────────────────────
# Paper CRUD
# ──────────────────────────────────────────────

def insert_paper(conn: sqlite3.Connection, paper: dict) -> bool:
    """
    Insert a paper dict. Returns True if inserted, False if duplicate.
    Expected keys: id, title, authors, abstract, source, source_id, url,
                   doi, published_date, ingested_at, run_id, relevance_score,
                   paper_type, matching_topics, in_working_set, faiss_id
    """
    try:
        conn.execute("""
            INSERT INTO papers (
                id, title, authors, abstract, source, source_id, url, doi,
                published_date, ingested_at, run_id, relevance_score,
                paper_type, matching_topics, in_working_set, faiss_id,
                added_to_ws_at
            ) VALUES (
                :id, :title, :authors, :abstract, :source, :source_id, :url, :doi,
                :published_date, :ingested_at, :run_id, :relevance_score,
                :paper_type, :matching_topics, :in_working_set, :faiss_id,
                :added_to_ws_at
            )
        """, paper)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_paper(conn: sqlite3.Connection, paper_id: str) -> Optional[dict]:
    """Fetch a single paper by ID."""
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return dict(row) if row else None


def get_working_set_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return all papers in the working set."""
    rows = conn.execute(
        "SELECT * FROM papers WHERE in_working_set = 1 ORDER BY relevance_score DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_reanalyzable_working_set_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return working-set papers created by pipeline runs, excluding bootstrap seeds."""
    rows = conn.execute("""
        SELECT *
        FROM papers
        WHERE in_working_set = 1
          AND run_id IS NOT NULL
        ORDER BY relevance_score DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_refreshable_papers(conn: sqlite3.Connection) -> list[dict]:
    """
    Return papers that have generated notes or working-set state worth refreshing.

    This intentionally includes analyzed-but-not-working-set papers so relinking can
    keep existing notes aligned when tags or relationship prompts change.
    """
    rows = conn.execute("""
        SELECT DISTINCT p.*
        FROM papers p
        LEFT JOIN analyses a ON a.paper_id = p.id
        LEFT JOIN compressed_summaries cs ON cs.paper_id = p.id
        WHERE p.in_working_set = 1
           OR a.paper_id IS NOT NULL
           OR cs.paper_id IS NOT NULL
        ORDER BY p.in_working_set DESC, p.relevance_score DESC, p.ingested_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_reanalysis_target_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return papers whose analysis affects the active workspace UX.

    Reanalysis is expensive and rewrites recommendation state. Limit the default
    maintenance path to papers that can appear in the Review/Track workflow,
    graph, notes, or working-set context.
    """
    rows = conn.execute("""
        SELECT DISTINCT p.*
        FROM papers p
        LEFT JOIN analyses a ON a.paper_id = p.id
        WHERE p.run_id IS NOT NULL
          AND (
              p.in_working_set = 1
              OR LOWER(COALESCE(a.recommendation, '')) IN ('read', 'track')
          )
        ORDER BY p.in_working_set DESC,
                 CASE LOWER(COALESCE(a.recommendation, ''))
                     WHEN 'read' THEN 0
                     WHEN 'track' THEN 1
                     ELSE 2
                 END,
                 p.relevance_score DESC,
                 p.ingested_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_reanalyzable_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return all non-bootstrap papers in stable priority order."""
    rows = conn.execute("""
        SELECT *
        FROM papers
        WHERE run_id IS NOT NULL
        ORDER BY in_working_set DESC, relevance_score DESC, ingested_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_all_papers(conn: sqlite3.Connection) -> list[dict]:
    """Return every paper in stable priority order."""
    rows = conn.execute("""
        SELECT *
        FROM papers
        ORDER BY in_working_set DESC, relevance_score DESC, ingested_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_working_set_count(conn: sqlite3.Connection) -> int:
    """Return the number of papers in the working set."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM papers WHERE in_working_set = 1").fetchone()
    return row["cnt"]


def get_all_paper_ids(conn: sqlite3.Connection) -> list[str]:
    """Return IDs of every paper in the database."""
    rows = conn.execute("SELECT id FROM papers").fetchall()
    return [r["id"] for r in rows]


def get_paper_read_state(conn: sqlite3.Connection, paper_id: str) -> bool:
    """Return whether a paper has been marked read."""
    init_schema(conn)
    row = conn.execute(
        "SELECT read FROM paper_read_state WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    return bool(row["read"]) if row else False


def set_paper_read_state(conn: sqlite3.Connection, paper_id: str, read: bool) -> None:
    """Persist read/unread state for a paper."""
    init_schema(conn)
    conn.execute("""
        INSERT INTO paper_read_state (paper_id, read, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            read = excluded.read,
            updated_at = excluded.updated_at
    """, (paper_id, 1 if read else 0, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def set_paper_reading_status(conn: sqlite3.Connection, paper_id: str, reading_status: str) -> None:
    """Persist user reading-list/currently-reading state for a paper."""
    init_schema(conn)
    normalized = reading_status if reading_status in {"reading_list", "currently_reading"} else ""
    conn.execute("""
        INSERT INTO paper_read_state (paper_id, read, reading_status, updated_at)
        VALUES (?, 0, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            reading_status = excluded.reading_status,
            updated_at = excluded.updated_at
    """, (paper_id, normalized, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def initialize_read_state(conn: sqlite3.Connection) -> None:
    """Ensure every paper has an explicit read-state row."""
    init_schema(conn)
    missing = conn.execute("""
        SELECT 1
        FROM papers p
        LEFT JOIN paper_read_state prs ON prs.paper_id = p.id
        WHERE prs.paper_id IS NULL
        LIMIT 1
    """).fetchone()
    if not missing:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT OR IGNORE INTO paper_read_state (paper_id, read, updated_at)
        SELECT id, 0, ? FROM papers
    """, (now,))
    conn.commit()


def mark_working_set(conn: sqlite3.Connection, paper_id: str, in_ws: bool) -> None:
    """Add or remove a paper from the working set."""
    now = datetime.now(timezone.utc).isoformat()
    if in_ws:
        conn.execute(
            "UPDATE papers SET in_working_set = 1, added_to_ws_at = ? WHERE id = ?",
            (now, paper_id),
        )
    else:
        conn.execute(
            "UPDATE papers SET in_working_set = 0, added_to_ws_at = NULL, cluster_id = NULL WHERE id = ?",
            (paper_id,),
        )
    conn.commit()


def update_paper_cluster(conn: sqlite3.Connection, paper_id: str, cluster_id: int | None) -> None:
    """Update cluster assignment for a paper."""
    conn.execute("UPDATE papers SET cluster_id = ? WHERE id = ?", (cluster_id, paper_id))
    conn.commit()


def clear_cluster_assignments(conn: sqlite3.Connection, *, working_set: bool | None = None) -> None:
    """Clear cluster IDs, optionally scoped by working-set membership."""
    if working_set is None:
        conn.execute("UPDATE papers SET cluster_id = NULL WHERE cluster_id IS NOT NULL")
    else:
        conn.execute(
            "UPDATE papers SET cluster_id = NULL WHERE cluster_id IS NOT NULL AND in_working_set = ?",
            (1 if working_set else 0,),
        )
    conn.commit()


def update_paper_faiss_id(conn: sqlite3.Connection, paper_id: str, faiss_id: int) -> None:
    """Update the FAISS position for a paper in the all_papers index."""
    conn.execute("UPDATE papers SET faiss_id = ? WHERE id = ?", (faiss_id, paper_id))
    conn.commit()


def paper_exists_by_source(conn: sqlite3.Connection, source: str, source_id: str) -> bool:
    """Check if a paper from a given source already exists."""
    row = conn.execute(
        "SELECT 1 FROM papers WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    return row is not None


def paper_exists_by_doi(conn: sqlite3.Connection, doi: str) -> bool:
    """Check if a paper with the given DOI already exists."""
    if not doi:
        return False
    row = conn.execute(
        "SELECT 1 FROM papers WHERE doi = ?", (doi,)
    ).fetchone()
    return row is not None


# ──────────────────────────────────────────────
# Compressed Summaries
# ──────────────────────────────────────────────

def insert_compressed_summary(conn: sqlite3.Connection, summary: dict) -> None:
    """
    Insert a compressed summary.
    Expected keys: paper_id, contributions (JSON str), method, key_terms (JSON str), domain
    """
    conn.execute("""
        INSERT OR REPLACE INTO compressed_summaries
            (paper_id, contributions, method, key_terms, domain, generated_at)
        VALUES (:paper_id, :contributions, :method, :key_terms, :domain, :generated_at)
    """, {
        **summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    conn.commit()


def get_compressed_summary(conn: sqlite3.Connection, paper_id: str) -> Optional[dict]:
    """Fetch compressed summary for a paper."""
    row = conn.execute(
        "SELECT * FROM compressed_summaries WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    return dict(row) if row else None


def get_working_set_summaries(conn: sqlite3.Connection) -> list[dict]:
    """
    Return papers + their compressed summaries for the entire working set.
    Joins papers and compressed_summaries tables.
    """
    rows = conn.execute("""
        SELECT p.id, p.title, p.cluster_id,
               cs.contributions, cs.method, cs.key_terms, cs.domain
        FROM papers p
        JOIN compressed_summaries cs ON p.id = cs.paper_id
        WHERE p.in_working_set = 1
    """).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Analyses
# ──────────────────────────────────────────────

def insert_analysis(conn: sqlite3.Connection, analysis: dict) -> None:
    """Insert or replace a RAG analysis result."""
    normalized = normalize_analysis_payload(analysis)
    conn.execute("""
        INSERT OR REPLACE INTO analyses (
            paper_id, summary, key_contributions, is_novel,
            novelty_explanation, extends, overlaps_with,
            relation_to_research, recommendation, recommendation_reason,
            confidence, retrieved_paper_ids, generated_at
        ) VALUES (
            :paper_id, :summary, :key_contributions, :is_novel,
            :novelty_explanation, :extends, :overlaps_with,
            :relation_to_research, :recommendation, :recommendation_reason,
            :confidence, :retrieved_paper_ids, :generated_at
        )
    """, {
        **normalized,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    conn.commit()


def get_analysis(conn: sqlite3.Connection, paper_id: str) -> Optional[dict]:
    """Fetch the full analysis for a paper."""
    row = conn.execute(
        "SELECT * FROM analyses WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    return dict(row) if row else None


# ──────────────────────────────────────────────
# Verifications
# ──────────────────────────────────────────────

def insert_verification(conn: sqlite3.Connection, verification: dict) -> None:
    """Insert or replace a verification result."""
    normalized = {
        **verification,
        "corrected_recommendation": normalize_corrected_recommendation(verification.get("corrected_recommendation")),
    }
    conn.execute("""
        INSERT OR REPLACE INTO verifications
            (paper_id, verified, issues, corrected_recommendation, generated_at)
        VALUES (:paper_id, :verified, :issues, :corrected_recommendation, :generated_at)
    """, {
        **normalized,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    conn.commit()


# ──────────────────────────────────────────────
# Prune Actions
# ──────────────────────────────────────────────

def insert_prune_action(conn: sqlite3.Connection, action: dict) -> int:
    """Persist a prune suggestion for later human review."""
    preview = action.get("preview")
    if isinstance(preview, dict):
        preview = json.dumps(preview)
    cursor = conn.execute("""
        INSERT INTO prune_actions (
            paper_id, pipeline_run_id, title, recommendation, reason,
            risk_if_removed, preview, status, created_at
        ) VALUES (
            :paper_id, :pipeline_run_id, :title, :recommendation, :reason,
            :risk_if_removed, :preview, :status, :created_at
        )
    """, {
        **action,
        "preview": preview,
        "status": action.get("status", "pending"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    conn.commit()
    return cursor.lastrowid


def list_prune_actions(conn: sqlite3.Connection, status: str = "pending", limit: int = 10) -> list[dict]:
    """Return prune actions ordered newest-first."""
    rows = conn.execute("""
        SELECT *
        FROM prune_actions
        WHERE status = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (status, limit)).fetchall()
    actions = []
    for row in rows:
        action = dict(row)
        if action.get("preview"):
            try:
                action["preview"] = json.loads(action["preview"])
            except (TypeError, json.JSONDecodeError):
                pass
        actions.append(action)
    return actions


def get_prune_action(conn: sqlite3.Connection, action_id: int) -> Optional[dict]:
    """Fetch a single prune action by ID."""
    row = conn.execute("SELECT * FROM prune_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        return None
    action = dict(row)
    if action.get("preview"):
        try:
            action["preview"] = json.loads(action["preview"])
        except (TypeError, json.JSONDecodeError):
            pass
    return action


def update_prune_action_status(conn: sqlite3.Connection, action_id: int, status: str) -> None:
    """Mark a prune action as reviewed/applied/kept."""
    now = datetime.now(timezone.utc).isoformat()
    fields = {"status": status, "reviewed_at": now}
    if status == "applied":
        fields["applied_at"] = now
    set_clause = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [action_id]
    conn.execute(f"UPDATE prune_actions SET {set_clause} WHERE id = ?", values)
    conn.commit()


# ──────────────────────────────────────────────
# Pipeline Runs
# ──────────────────────────────────────────────

def create_pipeline_run(conn: sqlite3.Connection, run_type: str = "scheduled") -> int:
    """Create a new pipeline run record and return its ID."""
    run_number = conn.execute(
        "SELECT COUNT(*) as count FROM pipeline_runs WHERE run_type = ?", (run_type,)
    ).fetchone()["count"] + 1

    cursor = conn.execute(
        "INSERT INTO pipeline_runs (run_number, started_at, run_type) VALUES (?, ?, ?)",
        (run_number, datetime.now(timezone.utc).isoformat(), run_type),
    )
    conn.commit()
    return cursor.lastrowid


def update_pipeline_run(conn: sqlite3.Connection, run_id: int, **kwargs) -> None:
    """Update fields on a pipeline run record."""
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [run_id]
    conn.execute(f"UPDATE pipeline_runs SET {set_clause} WHERE id = ?", values)
    conn.commit()


def complete_pipeline_run(conn: sqlite3.Connection, run_id: int, status: str, **kwargs) -> None:
    """Mark a pipeline run as completed."""
    update_pipeline_run(
        conn, run_id,
        completed_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        **kwargs,
    )


# ──────────────────────────────────────────────
# Ingestion State
# ──────────────────────────────────────────────

def get_last_successful_run(conn: sqlite3.Connection, source: str) -> Optional[str]:
    """Get the ISO 8601 timestamp of the last successful fetch for a source."""
    row = conn.execute(
        "SELECT last_successful_run FROM ingestion_state WHERE source = ?", (source,)
    ).fetchone()
    return row["last_successful_run"] if row else None


def update_ingestion_state(conn: sqlite3.Connection, source: str,
                           timestamp: str, query_params: Optional[dict] = None) -> None:
    """Update the last successful run for a source."""
    conn.execute("""
        INSERT INTO ingestion_state (source, last_successful_run, last_query_params)
        VALUES (?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_successful_run = excluded.last_successful_run,
            last_query_params = excluded.last_query_params
    """, (source, timestamp, json.dumps(query_params) if query_params else None))
    conn.commit()


def rebuild_working_set_index(conn: sqlite3.Connection,
                              embeddings_by_id: dict[str, np.ndarray]):
    """
    Rebuild the working set FAISS index from scratch.
    
    Args:
        conn: database connection
        embeddings_by_id: dict mapping paper_id → embedding vector
    
    Returns:
        (index, ws_id_map) — the new index and position→paper_id mapping
    """
    ws_papers = get_working_set_papers(conn)
    index = create_empty_index()
    ws_map: dict[int, str] = {}

    for paper in ws_papers:
        pid = paper["id"]
        if pid in embeddings_by_id:
            pos = add_to_index(index, embeddings_by_id[pid])
            ws_map[pos] = pid

    save_index(index, "index_ws")
    save_ws_id_map(ws_map)
    return index, ws_map


def rebuild_all_papers_index(conn: sqlite3.Connection,
                             embeddings_by_id: dict[str, np.ndarray]):
    """
    Rebuild the all-paper FAISS index from persisted embeddings.

    The all-paper index uses papers.faiss_id as its position→paper_id mapping,
    so the database rows are updated during rebuild.
    """
    rows = conn.execute("SELECT id FROM papers ORDER BY ingested_at DESC, id ASC").fetchall()
    index = create_empty_index()

    conn.execute("UPDATE papers SET faiss_id = NULL")
    for row in rows:
        pid = row["id"]
        if pid not in embeddings_by_id:
            continue
        pos = add_to_index(index, embeddings_by_id[pid])
        conn.execute("UPDATE papers SET faiss_id = ? WHERE id = ?", (pos, pid))

    conn.commit()
    save_index(index, "index_all")
    return index
