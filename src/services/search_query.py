"""SQL expression builders for paper search and ranking."""

from __future__ import annotations

from typing import Any
import re

from src.config import load_config
from src.profile import load_research_profile

QUERY_ALIASES = load_config().get("search.query_aliases", {
    "gpu": ["cuda", "hbm", "l2 cache", "gpu-architecture", "accelerator"],
    "memory": ["hbm", "l2 cache", "memory-management", "cxl", "cache"],
    "rdma": ["kernel-bypass", "rpc", "smartnic", "nic", "networking"],
    "dataplane": ["data plane", "kernel-bypass", "networking", "smartnic"],
    "pipeline": ["pipelining", "parallelism", "distributed-training", "collective"],
    "pipelined": ["pipeline", "pipelining", "parallelism", "distributed-training", "collective"],
    "sharding": ["tensor parallelism", "model parallelism", "distributed-training", "collective communications"],
    "collective": ["nccl", "all-reduce", "allreduce", "distributed-training"],
    "collectives": ["nccl", "all-reduce", "allreduce", "distributed-training"],
    "serving": ["inference", "llm serving", "prefill", "decoding"],
})


def search_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9][a-z0-9.+#-]*", query.lower()) if len(term) > 1][:8]


def expanded_search_terms(query: str) -> list[str]:
    terms = search_terms(query)
    expanded = list(terms)
    for term in terms:
        expanded.extend(QUERY_ALIASES.get(term, []))
    deduped: list[str] = []
    seen = set()
    for term in expanded:
        normalized = term.lower().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped[:20]


def lowered_search_fields() -> str:
    return (
        "LOWER(COALESCE(p.title, '') || ' ' || COALESCE(p.authors, '') || ' ' || COALESCE(p.abstract, '') || ' '"
        " || COALESCE(p.matching_topics, '') || ' ' || COALESCE(p.paper_type, '') || ' '"
        " || COALESCE(cs.key_terms, '') || ' ' || COALESCE(cs.contributions, '') || ' '"
        " || COALESCE(cs.method, '') || ' ' || COALESCE(cs.domain, '') || ' '"
        " || COALESCE(a.summary, '') || ' ' || COALESCE(a.key_contributions, '') || ' '"
        " || COALESCE(a.relation_to_research, '') || ' ' || COALESCE(a.recommendation_reason, ''))"
    )


def search_score_sql(query: str) -> tuple[str, list[Any]]:
    phrase = f"%{query.lower().strip()}%"
    terms = expanded_search_terms(query)
    if not terms:
        return "0", []

    params: list[Any] = []
    parts = [
        "CASE WHEN LOWER(COALESCE(p.title, '')) LIKE ? THEN 120 ELSE 0 END",
        "CASE WHEN LOWER(COALESCE(p.matching_topics, '')) LIKE ? THEN 55 ELSE 0 END",
        "CASE WHEN LOWER(COALESCE(cs.key_terms, '')) LIKE ? THEN 50 ELSE 0 END",
        "CASE WHEN LOWER(COALESCE(cs.domain, '')) LIKE ? THEN 45 ELSE 0 END",
        "CASE WHEN LOWER(COALESCE(a.summary, '')) LIKE ? THEN 28 ELSE 0 END",
    ]
    params.extend([phrase, phrase, phrase, phrase, phrase])
    for term in terms:
        like = f"%{term}%"
        parts.extend([
            "CASE WHEN LOWER(COALESCE(p.title, '')) LIKE ? THEN 22 ELSE 0 END",
            "CASE WHEN LOWER(COALESCE(p.matching_topics, '')) LIKE ? THEN 14 ELSE 0 END",
            "CASE WHEN LOWER(COALESCE(cs.key_terms, '')) LIKE ? THEN 13 ELSE 0 END",
            "CASE WHEN LOWER(COALESCE(cs.contributions, '')) LIKE ? THEN 9 ELSE 0 END",
            "CASE WHEN LOWER(COALESCE(a.relation_to_research, '')) LIKE ? THEN 9 ELSE 0 END",
            "CASE WHEN LOWER(COALESCE(p.abstract, '')) LIKE ? THEN 4 ELSE 0 END",
        ])
        params.extend([like, like, like, like, like, like])
    return " + ".join(parts), params


def exact_query_match_sql(query: str) -> tuple[str, list[Any]]:
    phrase = f"%{query.lower().strip()}%"
    terms = search_terms(query)
    fields = lowered_search_fields()
    params: list[Any] = [phrase]
    if not terms:
        return "CASE WHEN LOWER(COALESCE(p.title, '')) LIKE ? THEN 1 ELSE 0 END", params
    term_checks = []
    for term in terms:
        term_checks.append(f"{fields} LIKE ?")
        params.append(f"%{term}%")
    return f"CASE WHEN LOWER(COALESCE(p.title, '')) LIKE ? OR ({' AND '.join(term_checks)}) THEN 1 ELSE 0 END", params


def semantic_profile_sql() -> tuple[str, list[Any]]:
    profile = load_research_profile()
    values = list(profile.get("tags", [])) + list(profile.get("topics", []))
    parts: list[str] = []
    params: list[Any] = []
    for value in values:
        normalized = str(value).strip().lower()
        if not normalized:
            continue
        parts.append(
            "CASE WHEN LOWER(COALESCE(cs.key_terms, '') || ' ' || COALESCE(p.matching_topics, '') || ' '"
            " || COALESCE(cs.domain, '')) LIKE ? THEN 1 ELSE 0 END"
        )
        params.append(f"%{normalized}%")
    return (" + ".join(parts) if parts else "0"), params
