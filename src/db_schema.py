"""
db_schema.py - SQLite schema DDL and lightweight migrations.

Keep CREATE/ALTER statements here so src.db can focus on database operations.
"""

from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_number      INTEGER,
            started_at      TEXT NOT NULL,
            completed_at    TEXT,
            status          TEXT NOT NULL DEFAULT 'running',
            papers_fetched  INTEGER DEFAULT 0,
            papers_passed_s1 INTEGER DEFAULT 0,
            papers_passed_s2 INTEGER DEFAULT 0,
            papers_analyzed INTEGER DEFAULT 0,
            papers_verified INTEGER DEFAULT 0,
            papers_added_ws INTEGER DEFAULT 0,
            prune_suggested TEXT,
            error_count     INTEGER DEFAULT 0,
            error_details   TEXT,
            run_type        TEXT DEFAULT 'scheduled'
        );

        CREATE TABLE IF NOT EXISTS papers (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            authors         TEXT NOT NULL,
            abstract        TEXT NOT NULL,
            source          TEXT NOT NULL,
            source_id       TEXT,
            url             TEXT,
            doi             TEXT,
            published_date  TEXT,
            ingested_at     TEXT NOT NULL,
            run_id          INTEGER,
            relevance_score INTEGER,
            paper_type      TEXT,
            matching_topics TEXT,
            in_working_set  INTEGER NOT NULL DEFAULT 0,
            feedback        TEXT,
            faiss_id        INTEGER,
            added_to_ws_at  TEXT,
            cluster_id      INTEGER,

            UNIQUE(source, source_id),
            FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
            ON papers(doi) WHERE doi IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_papers_working_set
            ON papers(in_working_set);
        CREATE INDEX IF NOT EXISTS idx_papers_relevance
            ON papers(relevance_score);
        CREATE INDEX IF NOT EXISTS idx_papers_published
            ON papers(published_date);
        CREATE INDEX IF NOT EXISTS idx_papers_cluster
            ON papers(cluster_id);

        CREATE TABLE IF NOT EXISTS compressed_summaries (
            paper_id        TEXT PRIMARY KEY,
            contributions   TEXT NOT NULL,
            method          TEXT NOT NULL,
            key_terms       TEXT NOT NULL,
            domain          TEXT,
            generated_at    TEXT NOT NULL,

            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS analyses (
            paper_id                TEXT PRIMARY KEY,
            summary                 TEXT NOT NULL,
            key_contributions       TEXT NOT NULL,
            is_novel                INTEGER,
            novelty_explanation     TEXT,
            extends                 TEXT,
            overlaps_with           TEXT,
            relation_to_research    TEXT,
            recommendation          TEXT NOT NULL,
            recommendation_reason   TEXT,
            confidence              TEXT,
            retrieved_paper_ids     TEXT,
            generated_at            TEXT NOT NULL,

            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS verifications (
            paper_id                TEXT PRIMARY KEY,
            verified                INTEGER NOT NULL,
            issues                  TEXT,
            corrected_recommendation TEXT,
            generated_at            TEXT NOT NULL,

            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS prune_actions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id        TEXT NOT NULL,
            pipeline_run_id INTEGER,
            title           TEXT NOT NULL,
            recommendation  TEXT NOT NULL,
            reason          TEXT,
            risk_if_removed TEXT,
            preview         TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL,
            reviewed_at     TEXT,
            applied_at      TEXT,

            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_prune_actions_status
            ON prune_actions(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_prune_actions_paper
            ON prune_actions(paper_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS ingestion_state (
            source              TEXT PRIMARY KEY,
            last_successful_run TEXT NOT NULL,
            last_query_params   TEXT
        );

        CREATE TABLE IF NOT EXISTS paper_read_state (
            paper_id    TEXT PRIMARY KEY,
            read        INTEGER NOT NULL DEFAULT 0,
            reading_status TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL,

            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS paper_folders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_folder_memberships (
            folder_id   INTEGER NOT NULL,
            paper_id    TEXT NOT NULL,
            added_at    TEXT NOT NULL,

            PRIMARY KEY (folder_id, paper_id),
            FOREIGN KEY (folder_id) REFERENCES paper_folders(id) ON DELETE CASCADE,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_paper_folder_memberships_paper
            ON paper_folder_memberships(paper_id);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indices, then apply idempotent migrations."""
    conn.executescript(SCHEMA_SQL)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_read_state)").fetchall()}
    if "reading_status" not in columns:
        conn.execute("ALTER TABLE paper_read_state ADD COLUMN reading_status TEXT NOT NULL DEFAULT ''")
        
    pipeline_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
    if "run_number" not in pipeline_cols:
        conn.execute("ALTER TABLE pipeline_runs ADD COLUMN run_number INTEGER")
        # Populate existing run numbers retroactively based on run_type and order
        conn.execute("""
            UPDATE pipeline_runs
            SET run_number = (
                SELECT COUNT(*)
                FROM pipeline_runs AS pr
                WHERE pr.run_type = pipeline_runs.run_type AND pr.id <= pipeline_runs.id
            )
        """)
    conn.commit()
