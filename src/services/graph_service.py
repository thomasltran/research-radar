"""
graph_service.py - Knowledge graph construction and pipeline stage snapshot logic.

Extracted verbatim from web_server.py.
"""

from __future__ import annotations

from pathlib import Path

from src import db
from src.output import OUTPUT_DIR
from src.pipeline_policy import GRAPH_WORKING_SET_RELEVANCE_FLOOR
from src.services.json_utils import json_load_safe
from src.services.paper_mapping import (
    match_paper_title,
    normalize_title,
)
from src.services.recommendation_policy import effective_recommendation
from src.services.search_service import fetch_paper_cards

# ---------------------------------------------------------------------------
# Stage snapshot
# ---------------------------------------------------------------------------

def stage_snapshot(run: dict) -> list[dict]:
    status = run.get("status")
    failed = status == "failed"
    cancelled = status == "cancelled"
    complete = status == "success"

    if run.get("run_type") == "relink":
        stages = [
            ("rescore", "Rescore", bool(run.get("papers_fetched"))),
            ("index", "Index", bool(run.get("papers_passed_s1"))),
            ("organize", "Organize", bool(run.get("papers_passed_s2"))),
            ("relationships", "Relations", bool(run.get("papers_analyzed"))),
            ("output", "Done", bool(run.get("completed_at"))),
        ]
    elif run.get("run_type") == "bootstrap":
        stages = [
            ("seeds", "Seeds", bool(run.get("papers_fetched"))),
            ("embed", "Embed", bool(run.get("papers_added_ws"))),
            ("index", "Index", bool(run.get("completed_at"))),
            ("output", "Done", bool(run.get("completed_at"))),
        ]
    elif run.get("run_type") == "reanalyze":
        target = run.get("papers_fetched") or 0
        compressed = run.get("papers_passed_s2") or 0
        analyzed = run.get("papers_analyzed") or 0
        completed = bool(run.get("completed_at"))
        stages = [
            ("index", "Index", bool(target or run.get("papers_passed_s1") or compressed or analyzed or completed)),
            ("compress", "Compress", bool(compressed or analyzed or completed)),
            ("analyze", "Analyze", bool(analyzed or completed)),
            ("verify", "Verify", bool(run.get("papers_verified")) or analyzed >= target > 0 or completed),
            ("output", "Notes", completed),
        ]
    else:
        stages = [
            ("fetch", "Fetch", bool(run.get("papers_fetched"))),
            ("filter", "Similarity", bool(run.get("papers_passed_s1"))),
            ("score", "Score", bool(run.get("papers_passed_s2"))),
            ("summarize", "Summarize", bool(run.get("papers_added_ws")) or bool(run.get("papers_analyzed"))),
            ("analyze", "Analyze", bool(run.get("papers_analyzed"))),
            ("verify", "Verify", bool(run.get("papers_verified")) or bool(run.get("completed_at"))),
            ("output", "Output", bool(run.get("completed_at"))),
        ]

    first_pending = next((i for i, (_, _, done) in enumerate(stages) if not done), len(stages))
    result = []
    for i, (key, label, done) in enumerate(stages):
        stage_status = "done" if done or complete else "pending"
        if status == "running" and i == first_pending:
            stage_status = "active"
        if (failed or cancelled) and i == first_pending:
            stage_status = status
        result.append({"key": key, "label": label, "status": stage_status})
    return result


# ---------------------------------------------------------------------------
# Digest helper
# ---------------------------------------------------------------------------

def digest_for_run(run: dict) -> tuple[str | None, str | None]:
    date_source = run.get("completed_at") or run.get("started_at")
    if not date_source:
        return None, None
    date = date_source[:10]
    path = OUTPUT_DIR / "digests" / f"{date}.md"
    if path.exists():
        return date, path.read_text(encoding="utf-8")
    return date, None


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _graph_recommendation(paper: dict) -> str | None:
    recommendation = effective_recommendation(paper.get("recommendation"), paper.get("relevance_score"))
    if recommendation in {"read", "track"}:
        return recommendation
    if paper.get("in_working_set") and (paper.get("relevance_score") or 0) >= GRAPH_WORKING_SET_RELEVANCE_FLOOR:
        return "track"
    return None


def build_graph(conn) -> dict:
    papers = []
    for paper in fetch_paper_cards(conn, sort="relevance"):
        recommendation = _graph_recommendation(paper)
        if recommendation:
            papers.append({**paper, "recommendation": recommendation})

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()
    paper_title_to_id: dict[str, str] = {}
    paper_id_to_node_id: dict[str, str] = {}
    canonical_papers: list[dict] = []

    def add_edge(source: str, target: str, edge_type: str) -> None:
        if source == target:
            return
        key = (source, target, edge_type)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"source": source, "target": target, "type": edge_type})

    for paper in sorted(papers, key=lambda item: len(normalize_title(item["title"])), reverse=True):
        paper_node_id = f"paper:{paper['id']}"
        normalized_title = normalize_title(paper["title"])
        canonical_id = match_paper_title(paper["title"], paper_title_to_id)
        if canonical_id:
            paper_id_to_node_id[paper_node_id] = canonical_id
            paper_title_to_id[normalized_title] = canonical_id
            continue
        paper_id_to_node_id[paper_node_id] = paper_node_id
        paper_title_to_id[normalized_title] = paper_node_id
        canonical_papers.append(paper)

    for paper in canonical_papers:
        paper_id = f"paper:{paper['id']}"
        nodes[paper_id] = {
            "id": paper_id,
            "label": paper["title"],
            "type": "paper",
            "paper_id": paper["id"],
            "read": paper["read"],
            "relevance_score": paper["relevance_score"],
            "tags": paper.get("tags") or [],
            "run_id": paper.get("run_id"),
            "run_type": paper.get("run_type"),
            "source": paper.get("source"),
            "recommendation": paper.get("recommendation"),
            "reading_status": paper.get("reading_status"),
            "in_working_set": paper.get("in_working_set"),
        }

    for paper in papers:
        paper_id = paper_id_to_node_id[f"paper:{paper['id']}"]
        paper_node = nodes[paper_id]
        for tag in paper.get("tags") or []:
            tag_id = f"tag:{tag}"
            if tag not in paper_node["tags"]:
                paper_node["tags"].append(tag)
            nodes.setdefault(tag_id, {"id": tag_id, "label": tag, "type": "tag"})
            add_edge(paper_id, tag_id, "tagged")

        analysis = db.get_analysis(conn, paper["id"])
        if analysis:
            for rel_type, field in (("extends", "extends"), ("overlaps_with", "overlaps_with")):
                for title in json_load_safe(analysis.get(field), []):
                    related_id = match_paper_title(title, paper_title_to_id)
                    if related_id:
                        add_edge(paper_id, related_id, rel_type)

    return {"nodes": list(nodes.values()), "edges": edges}
