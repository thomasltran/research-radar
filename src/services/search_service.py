"""
search_service.py - Paper card fetching plus text and semantic search.

Extracted verbatim from web_server.py with private helpers made module-level functions.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from src import db, embed
from src.config import load_config
from src.pipeline_policy import WORKING_SET_ENTRY_THRESHOLD
from src.services.paper_mapping import paper_row_to_card
from src.services.search_query import (
    exact_query_match_sql,
    lowered_search_fields,
    search_score_sql,
    search_terms,
    semantic_profile_sql,
)

logger = logging.getLogger(__name__)
_CONFIG = load_config()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEMANTIC_MATCH_FLOOR = _CONFIG.float("search.semantic_match_floor", 0.48)
SEMANTIC_CANDIDATE_K = _CONFIG.int("search.semantic_candidate_k", 80)
SEMANTIC_MAX_RESULTS = _CONFIG.int("search.semantic_max_results", 16)
SEMANTIC_BROAD_QUERY_MAX_RESULTS = _CONFIG.int("search.semantic_broad_query_max_results", 12)
NORMALIZED_TEXT_MATCH_LIMIT = _CONFIG.int("search.normalized_text_match_limit", 20)

# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

def _plain_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _normalized_text_matches(conn, query: str, limit: int = NORMALIZED_TEXT_MATCH_LIMIT) -> list[tuple[str, float]]:
    """Return accent-insensitive exact matches that semantic search can miss."""
    query_text = _plain_text(query).strip()
    terms = [_plain_text(term) for term in search_terms(query)]
    if not query_text and not terms:
        return []

    rows = conn.execute("""
        SELECT p.id, p.title, p.abstract, p.matching_topics, p.paper_type,
               cs.key_terms, cs.contributions, cs.method, cs.domain,
               a.summary, a.key_contributions, a.relation_to_research, a.recommendation_reason
        FROM papers p
        LEFT JOIN compressed_summaries cs ON cs.paper_id = p.id
        LEFT JOIN analyses a ON a.paper_id = p.id
    """).fetchall()

    matches: list[tuple[str, float]] = []
    for row in rows:
        title = _plain_text(row["title"])
        fields = _plain_text(" ".join(str(row[key] or "") for key in row.keys()))
        if query_text and query_text in title:
            matches.append((row["id"], 1.0))
        elif terms and all(term in fields for term in terms):
            matches.append((row["id"], 0.84))

    return matches[:limit]


def _merge_ranked_results(*groups: list[tuple[str, float]]) -> list[tuple[str, float]]:
    merged: dict[str, float] = {}
    for group in groups:
        for paper_id, score in group:
            merged[paper_id] = max(score, merged.get(paper_id, 0.0))
    return sorted(merged.items(), key=lambda item: item[1], reverse=True)


def semantic_library_results(conn, query: str, k: int = SEMANTIC_CANDIDATE_K) -> list[tuple[str, float]] | None:
    query = (query or "").strip()
    if not query:
        return []
    text_matches = _normalized_text_matches(conn, query)
    try:
        index_all = db.load_index("index_all")
        if index_all.ntotal == 0:
            return text_matches or None
        id_rows = conn.execute("SELECT id, faiss_id FROM papers WHERE faiss_id IS NOT NULL").fetchall()
        id_map = {int(row["faiss_id"]): row["id"] for row in id_rows}
        if not id_map:
            return text_matches or None
        query_vec = embed.embed_query(query)
        distances, indices = db.search_index(index_all, query_vec, k=min(k, index_all.ntotal))
    except Exception:
        logger.exception("Semantic search failed")
        return text_matches or None

    results: list[tuple[str, float]] = []
    for distance, idx in zip(distances[0], indices[0]):
        idx = int(idx)
        score = float(distance)
        if score < SEMANTIC_MATCH_FLOOR:
            continue
        if idx >= 0 and idx in id_map:
            results.append((id_map[idx], round(score, 4)))
    return _merge_ranked_results(text_matches, results)


def _filter_semantic_rows(rows: list[Any], query: str) -> list[Any]:
    if not rows:
        return []
    max_results = SEMANTIC_BROAD_QUERY_MAX_RESULTS if len(search_terms(query)) <= 1 else SEMANTIC_MAX_RESULTS
    top_score = max(float(row["hybrid_score"] or 0) for row in rows)
    if top_score <= 0:
        return rows[:max_results]
    floor = max(0.56, min(top_score - 0.12, 0.72))
    filtered = [row for row in rows if float(row["hybrid_score"] or 0) >= floor]
    return filtered[:max_results]


# ---------------------------------------------------------------------------
# Main paper card fetch
# ---------------------------------------------------------------------------

def fetch_paper_cards(
    conn,
    *,
    q: str | None = None,
    read: bool | None = None,
    reading_status: str | None = None,
    recommendation: str | None = None,
    tag: str | None = None,
    cluster: str | None = None,
    working_set: bool | None = None,
    run_id: str | None = None,
    folder_id: int | None = None,
    semantic: bool = False,
    sort: str = "relevance",
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    score_sql = "0"
    score_params: list[Any] = []
    semantic_results: list[tuple[str, float]] = []
    semantic_unavailable = False
    semantic_score_sql = "NULL"
    semantic_score_params: list[Any] = []
    semantic_rank_sql = "0"
    semantic_rank_params: list[Any] = []
    profile_sql = "0"
    profile_params: list[Any] = []
    hybrid_score_sql = "NULL"
    hybrid_score_params: list[Any] = []
    exact_match_sql = "0"
    exact_match_params: list[Any] = []

    if q:
        score_sql, score_params = search_score_sql(q)
        exact_match_sql, exact_match_params = exact_query_match_sql(q)
        if semantic:
            semantic_results = semantic_library_results(conn, q)
            if semantic_results is None:
                semantic = False
                semantic_unavailable = True
            else:
                if semantic_results:
                    semantic_score_sql = "CASE p.id " + " ".join("WHEN ? THEN ?" for _ in semantic_results) + " ELSE 0 END"
                    for paper_id, score in semantic_results:
                        semantic_score_params.extend([paper_id, score])
                    semantic_rank_sql = semantic_score_sql
                    semantic_rank_params = list(semantic_score_params)
                profile_sql, profile_params = semantic_profile_sql()
                recommendation_boost_sql = """
                    CASE
                        WHEN LOWER(COALESCE(a.recommendation, '')) = 'read' THEN 0.04
                        WHEN LOWER(COALESCE(a.recommendation, '')) = 'track' THEN 0.03
                        ELSE 0
                    END
                """
                hybrid_score_sql = f"""
                    MIN(1.0,
                        ({semantic_rank_sql}) * 0.52
                        + (MIN(({score_sql}), 180) / 180.0) * 0.26
                        + (MIN(({profile_sql}), 3) / 3.0) * 0.10
                        + (COALESCE(p.relevance_score, 0) / 10.0) * 0.08
                        + {recommendation_boost_sql}
                    )
                """
                hybrid_score_params = semantic_rank_params + score_params + profile_params
                fields = lowered_search_fields()
                terms = search_terms(q)
                if terms:
                    exact_clauses = []
                    for term in terms:
                        exact_clauses.append(f"{fields} LIKE ?")
                        params.append(f"%{term}%")
                    semantic_ids = [pid for pid, _ in semantic_results]
                    if semantic_ids:
                        placeholders = ", ".join("?" for _ in semantic_ids)
                        clauses.append(f"(p.id IN ({placeholders}) OR ({' AND '.join(exact_clauses)}))")
                        params = semantic_ids + params
                    else:
                        clauses.append(f"({' AND '.join(exact_clauses)})")
        if not semantic:
            fields = lowered_search_fields()
            terms = search_terms(q)
            if terms:
                for term in terms:
                    clauses.append(f"{fields} LIKE ?")
                    params.append(f"%{term}%")

    if read is not None:
        clauses.append("COALESCE(prs.read, 0) = ?")
        params.append(1 if read else 0)
    if reading_status:
        clauses.append("COALESCE(prs.reading_status, '') = ?")
        params.append(reading_status)
    if recommendation:
        normalized_recommendation = recommendation.lower()
        if normalized_recommendation == "read":
            clauses.append(
                "LOWER(COALESCE(a.recommendation, '')) = ? AND COALESCE(p.relevance_score, 0) >= ?"
            )
            params.extend(["read", WORKING_SET_ENTRY_THRESHOLD])
        elif normalized_recommendation == "track":
            clauses.append("""(
                LOWER(COALESCE(a.recommendation, '')) = ?
                OR (
                    LOWER(COALESCE(a.recommendation, '')) = 'read'
                    AND COALESCE(p.relevance_score, 0) < ?
                )
            )""")
            params.extend(["track", WORKING_SET_ENTRY_THRESHOLD])
        else:
            clauses.append("LOWER(COALESCE(a.recommendation, '')) = ?")
            params.append(normalized_recommendation)
    if tag:
        clauses.append("LOWER(COALESCE(cs.key_terms, '')) LIKE ?")
        params.append(f"%{tag.lower()}%")
    if cluster not in (None, ""):
        clauses.append("p.cluster_id = ?")
        params.append(int(cluster))
    if working_set is not None:
        clauses.append("p.in_working_set = ?")
        params.append(1 if working_set else 0)
    if run_id:
        if run_id == "seed":
            clauses.append("(p.source = 'bootstrap' OR pr.run_type = 'bootstrap')")
        else:
            clauses.append("p.run_id = ?")
            params.append(int(run_id))
    if folder_id is not None:
        clauses.append("""
            EXISTS (
                SELECT 1 FROM paper_folder_memberships pfm
                WHERE pfm.paper_id = p.id AND pfm.folder_id = ?
            )
        """)
        params.append(folder_id)

    order_by = {
        "new": "p.ingested_at DESC",
        "published": "p.published_date DESC",
        "title": "p.title COLLATE NOCASE ASC",
        "unread": "COALESCE(prs.read, 0) ASC, p.relevance_score DESC",
        "relevance": "p.relevance_score DESC, p.ingested_at DESC",
    }.get(sort, "p.relevance_score DESC, p.ingested_at DESC")
    if q and semantic and semantic_results and sort == "relevance":
        order_by = "hybrid_score DESC, p.relevance_score DESC, p.title COLLATE NOCASE ASC"
    elif q and not semantic:
        order_by = f"search_score DESC, {order_by}"

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"""
        SELECT p.*, COALESCE(prs.read, 0) AS read, COALESCE(prs.reading_status, '') AS reading_status,
               pr.run_type AS run_type,
               cs.contributions, cs.method, cs.key_terms, cs.domain,
               a.summary, a.recommendation, a.recommendation_reason, a.relation_to_research, a.confidence,
               ({score_sql}) AS search_score,
               ({semantic_score_sql}) AS semantic_score,
               ({hybrid_score_sql}) AS hybrid_score,
               ({exact_match_sql}) AS exact_query_match,
               {1 if semantic_unavailable else 0} AS semantic_unavailable,
               (
                   SELECT COALESCE(json_group_array(json_object('id', pf.id, 'name', pf.name)), '[]')
                   FROM paper_folder_memberships pfm
                   JOIN paper_folders pf ON pf.id = pfm.folder_id
                   WHERE pfm.paper_id = p.id
               ) AS folders
        FROM papers p
        LEFT JOIN pipeline_runs pr ON pr.id = p.run_id
        LEFT JOIN paper_read_state prs ON prs.paper_id = p.id
        LEFT JOIN compressed_summaries cs ON cs.paper_id = p.id
        LEFT JOIN analyses a ON a.paper_id = p.id
        {where}
        ORDER BY {order_by}
    """, score_params + semantic_score_params + hybrid_score_params + exact_match_params + params).fetchall()
    if q and semantic and semantic_results:
        rows = _filter_semantic_rows(rows, q)
        rows = [dict(row) for row in rows]
    return [paper_row_to_card(dict(row)) for row in rows]
