"""Paper row normalization shared by REST, graph, and tag services."""

from __future__ import annotations

import re

from src.profile import canonicalize_tags, load_research_profile
from src.services.json_utils import json_load_safe
from src.services.recommendation_policy import effective_recommendation


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def match_paper_title(title: str, paper_title_to_id: dict[str, str]) -> str | None:
    normalized = normalize_title(title)
    if not normalized:
        return None
    if normalized in paper_title_to_id:
        return paper_title_to_id[normalized]
    candidates: list[tuple[int, str]] = []
    for paper_title, paper_id in paper_title_to_id.items():
        if normalized in paper_title or paper_title in normalized:
            candidates.append((len(paper_title), paper_id))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return None


def _authors(value: str | None) -> list[str]:
    raw = json_load_safe(value, [])
    authors = []
    for item in raw:
        if isinstance(item, dict):
            authors.append(item.get("name", ""))
        else:
            authors.append(str(item))
    return [a for a in authors if a]


def _sentence_snippet(text: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cutoff = text[:limit]
    sentence_end = max(cutoff.rfind("."), cutoff.rfind("?"), cutoff.rfind("!"))
    if sentence_end >= 80:
        return cutoff[:sentence_end + 1]
    return cutoff.rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."


def _preview_text(row: dict) -> str:
    summary = row.get("summary")
    if summary:
        return str(summary)

    contributions = json_load_safe(row.get("contributions"), [])
    if contributions:
        return " ".join(str(item).strip() for item in contributions if str(item).strip())

    method = row.get("method")
    if method:
        return str(method)

    abstract = row.get("abstract")
    if abstract:
        return str(abstract)

    return "No preview text available."


def paper_row_to_card(row: dict) -> dict:
    key_terms = canonicalize_tags(json_load_safe(row.get("key_terms"), []), load_research_profile().get("tags", []))
    contributions = json_load_safe(row.get("contributions"), [])
    summary_source = _preview_text(row)
    recommendation = effective_recommendation(row.get("recommendation"), row.get("relevance_score"))
    return {
        "id": row["id"],
        "title": row["title"],
        "authors": _authors(row.get("authors")),
        "source": row.get("source"),
        "url": row.get("url"),
        "published_date": row.get("published_date"),
        "ingested_at": row.get("ingested_at"),
        "relevance_score": row.get("relevance_score"),
        "paper_type": row.get("paper_type"),
        "matching_topics": json_load_safe(row.get("matching_topics"), []),
        "in_working_set": bool(row.get("in_working_set")),
        "cluster_id": row.get("cluster_id"),
        "read": bool(row.get("read")),
        "reading_status": row.get("reading_status") or "",
        "recommendation": recommendation,
        "confidence": row.get("confidence"),
        "summary": row.get("summary"),
        "summary_snippet": _sentence_snippet(summary_source),
        "key_terms": key_terms,
        "tags": key_terms,
        "folders": json_load_safe(row.get("folders"), []),
        "contributions": contributions,
        "domain": row.get("domain"),
        "run_id": row.get("run_id"),
        "run_type": row.get("run_type"),
        "semantic_score": row.get("hybrid_score") if row.get("hybrid_score") is not None else row.get("semantic_score"),
        "semantic_reason": row.get("semantic_reason"),
        "semantic_unavailable": bool(row.get("semantic_unavailable")),
    }
