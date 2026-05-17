"""
rag.py — Clustering and RAG retrieval logic.

Handles:
  - k-means clustering on working set embeddings
  - Cluster-aware retrieval (max 2 papers per cluster, k=4 total)
  - Flat top-k retrieval fallback (when working set < 40)
  - Pruning candidate selection
"""

import json
import logging
from math import sqrt
from typing import Optional

import numpy as np
from sklearn.cluster import KMeans

from src import db, embed
from src.config import load_config

logger = logging.getLogger(__name__)
_CONFIG = load_config()


# ──────────────────────────────────────────────
# Clustering
# ──────────────────────────────────────────────

CLUSTER_MINIMUM = _CONFIG.int("retrieval.cluster_minimum", 40)


def compute_dynamic_k(n_papers: int) -> int:
    """
    Compute dynamic number of clusters:
        k = max(3, min(int(sqrt(n / 2)), 10))
    Returns 0 if below CLUSTER_MINIMUM (signals skip).
    """
    if n_papers < CLUSTER_MINIMUM:
        return 0
    k = int(sqrt(n_papers / 2))
    return max(3, min(k, 10))


def cluster_working_set(conn, embeddings_by_id: dict[str, np.ndarray]) -> dict[str, int]:
    """
    Run k-means on working set embeddings and update cluster assignments.
    
    Args:
        conn: database connection
        embeddings_by_id: dict mapping paper_id → embedding vector
    
    Returns:
        dict mapping paper_id → cluster_id, or empty dict if clustering skipped
    """
    db.clear_cluster_assignments(conn, working_set=False)
    ws_papers = db.get_working_set_papers(conn)
    n = len(ws_papers)

    k = compute_dynamic_k(n)
    if k == 0:
        logger.info(f"Working set has {n} papers (< {CLUSTER_MINIMUM}), skipping clustering")
        db.clear_cluster_assignments(conn, working_set=True)
        return {}

    logger.info(f"Clustering {n} working set papers into k={k} clusters")

    # Collect embeddings in order
    paper_ids = []
    vectors = []
    for paper in ws_papers:
        pid = paper["id"]
        if pid in embeddings_by_id:
            paper_ids.append(pid)
            vectors.append(embeddings_by_id[pid])

    if len(vectors) < k:
        logger.warning(f"Not enough embeddings ({len(vectors)}) for k={k} clusters")
        db.clear_cluster_assignments(conn, working_set=True)
        return {}

    X = np.stack(vectors)

    # Run k-means
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)

    # Replace cluster assignments atomically at the workflow level. Papers missing
    # embeddings remain unclustered instead of retaining stale assignments.
    db.clear_cluster_assignments(conn, working_set=True)
    assignments = {}
    for pid, label in zip(paper_ids, labels):
        cluster_id = int(label)
        assignments[pid] = cluster_id
        db.update_paper_cluster(conn, pid, cluster_id)

    logger.info(f"Clustering complete. Distribution: {_cluster_distribution(labels, k)}")
    return assignments


def _cluster_distribution(labels, k: int) -> str:
    """Human-readable cluster size distribution."""
    counts = {}
    for label in labels:
        counts[int(label)] = counts.get(int(label), 0) + 1
    parts = [f"c{i}:{counts.get(i, 0)}" for i in range(k)]
    return " ".join(parts)


# ──────────────────────────────────────────────
# RAG Retrieval
# ──────────────────────────────────────────────

MAX_PER_CLUSTER = _CONFIG.int("retrieval.max_per_cluster", 2)
DEFAULT_RETRIEVAL_K = _CONFIG.int("retrieval.default_retrieval_k", 4)


def retrieve_context(
    conn,
    new_paper_embedding: np.ndarray,
    index_ws,
    ws_id_map: dict[int, str],
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
    exclude_id: Optional[str] = None,
) -> list[dict]:
    """
    Retrieve the most relevant working set papers for RAG context.
    
    Uses cluster-aware retrieval if clustering is active:
      - Find nearest cluster centroid
      - Retrieve top papers from that cluster + adjacent clusters
      - Cap papers per cluster, total k papers
    
    Falls back to flat top-k if clustering is not active.
    
    Args:
        conn: database connection
        new_paper_embedding: embedding of the new paper
        index_ws: FAISS working set index
        ws_id_map: FAISS position → paper_id mapping
        retrieval_k: number of papers to retrieve (default 4)
    
    Returns:
        List of dicts with keys: id, title, contributions, method, key_terms,
        domain, cluster_id, similarity
    """
    ws_count = db.get_working_set_count(conn)

    if ws_count == 0 or index_ws.ntotal == 0:
        logger.warning("Working set is empty — no context to retrieve")
        return []

    if ws_count < CLUSTER_MINIMUM or not _has_cluster_assignments(conn):
        # Flat top-k retrieval
        return _flat_retrieval(conn, new_paper_embedding, index_ws, ws_id_map, retrieval_k, exclude_id)
    else:
        # Cluster-aware retrieval
        return _cluster_retrieval(conn, new_paper_embedding, index_ws, ws_id_map, retrieval_k, exclude_id)


def _flat_retrieval(
    conn,
    query_embedding: np.ndarray,
    index_ws,
    ws_id_map: dict[int, str],
    k: int,
    exclude_id: Optional[str] = None,
) -> list[dict]:
    """Simple top-k nearest neighbor retrieval from working set."""
    search_k = k + 1 if exclude_id else k
    distances, indices = db.search_index(index_ws, query_embedding, k=search_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        idx = int(idx)
        if idx < 0 or idx not in ws_id_map:
            continue
        paper_id = ws_id_map[idx]
        if paper_id == exclude_id:
            continue
        item = _build_context_item(conn, paper_id, float(dist))
        if item:
            results.append(item)
            if len(results) >= k:
                break

    logger.info(f"Flat retrieval: {len(results)} papers returned")
    return results


def _cluster_retrieval(
    conn,
    query_embedding: np.ndarray,
    index_ws,
    ws_id_map: dict[int, str],
    k: int,
    exclude_id: Optional[str] = None,
) -> list[dict]:
    """
    Cluster-aware retrieval:
    1. Search for more candidates than needed
    2. Group by cluster
    3. Apply max-2-per-cluster constraint
    4. Backfill by similarity if diversity constraints under-fill
    """
    # Search for more candidates to allow cluster diversity
    search_k = min(max(k * 8, 24), index_ws.ntotal)
    distances, indices = db.search_index(index_ws, query_embedding, k=search_k)

    # Collect candidates with their cluster info
    candidates = []
    for dist, idx in zip(distances[0], indices[0]):
        idx = int(idx)
        if idx < 0 or idx not in ws_id_map:
            continue
        paper_id = ws_id_map[idx]
        if paper_id == exclude_id:
            continue
        item = _build_context_item(conn, paper_id, float(dist))
        if item:
            candidates.append(item)

    # Apply cluster diversity constraint
    cluster_counts: dict[int, int] = {}
    results = []

    for cand in candidates:
        cid = cand.get("cluster_id")
        if cid is not None:
            current = cluster_counts.get(cid, 0)
            if current >= MAX_PER_CLUSTER:
                continue
            cluster_counts[cid] = current + 1

        results.append(cand)

        if len(results) >= k:
            break

    if len(results) < k:
        seen = {r["id"] for r in results}
        for cand in candidates:
            if cand["id"] in seen:
                continue
            results.append(cand)
            seen.add(cand["id"])
            if len(results) >= k:
                break

    logger.info(f"Cluster-aware retrieval: {len(results)} papers "
                f"(clusters used: {list(cluster_counts.keys())})")
    return results


def _has_cluster_assignments(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM papers WHERE in_working_set = 1 AND cluster_id IS NOT NULL LIMIT 1"
    ).fetchone()
    return row is not None


def _build_context_item(conn, paper_id: str, similarity: float) -> Optional[dict]:
    summary = db.get_compressed_summary(conn, paper_id)
    paper = db.get_paper(conn, paper_id)
    if not paper:
        return None

    return {
        "id": paper_id,
        "title": paper["title"],
        "abstract": paper.get("abstract", ""),
        "source": paper.get("source"),
        "published_date": paper.get("published_date"),
        "relevance_score": paper.get("relevance_score"),
        "contributions": summary["contributions"] if summary else "[]",
        "method": summary["method"] if summary else "",
        "key_terms": summary["key_terms"] if summary else (paper.get("matching_topics") or "[]"),
        "domain": summary.get("domain", "") if summary else (paper.get("paper_type") or ""),
        "cluster_id": paper.get("cluster_id"),
        "similarity": round(similarity, 4),
    }


# ──────────────────────────────────────────────
# Pruning Candidate Selection
# ──────────────────────────────────────────────

PRUNE_TRIGGER = _CONFIG.int("pruning.trigger_working_set_size", 75)


def select_prune_candidate(conn, interest_vector: np.ndarray,
                           embeddings_by_id: dict[str, np.ndarray]) -> Optional[dict]:
    """
    Select the best candidate for pruning from the working set.
    
    Selection criteria: lowest relevance score AND lowest similarity to interest vector.
    Returns None if working set < PRUNE_TRIGGER.
    
    Args:
        conn: database connection
        interest_vector: current interest vector
        embeddings_by_id: dict mapping paper_id → embedding
    
    Returns:
        Paper dict of the best prune candidate, or None
    """
    ws_count = db.get_working_set_count(conn)
    if ws_count < PRUNE_TRIGGER:
        return None

    if interest_vector is None:
        logger.warning("No interest vector available — skipping prune candidate selection")
        return None

    ws_papers = db.get_working_set_papers(conn)

    # Compute composite score: relevance_score * interest_similarity
    candidates = []
    for paper in ws_papers:
        if paper.get("run_id") is None:
            continue
        pid = paper["id"]
        rel_score = paper.get("relevance_score") or 5  # default if missing

        if pid in embeddings_by_id:
            sim = embed.cosine_similarity(interest_vector, embeddings_by_id[pid])
        else:
            sim = 0.5  # neutral if embedding missing

        composite = rel_score * sim
        candidates.append((composite, paper))

    if not candidates:
        return None

    # Lowest composite = best prune candidate
    candidates.sort(key=lambda x: x[0])
    best = candidates[0][1]

    logger.info(f"Prune candidate: '{best['title']}' "
                f"(relevance={best.get('relevance_score')}, "
                f"composite={candidates[0][0]:.3f})")
    return best
