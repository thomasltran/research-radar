"""Build and normalize LLM analysis records at the DB boundary."""

from __future__ import annotations

import json
import re
from typing import Any

RECOMMENDATIONS = {"read", "track", "ignore"}
JSON_FIELDS = {"key_contributions", "extends", "overlaps_with", "retrieved_paper_ids"}
TEXT_FIELDS = {
    "summary",
    "novelty_explanation",
    "relation_to_research",
    "recommendation_reason",
    "confidence",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _json_array(value: Any) -> str:
    if value is None or value == "":
        return "[]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return json.dumps([value], ensure_ascii=False)
        return json.dumps(parsed if isinstance(parsed, list) else [parsed], ensure_ascii=False)
    return json.dumps(value if isinstance(value, list) else [value], ensure_ascii=False)


def normalize_recommendation(value: Any) -> tuple[str, str]:
    """Return (recommendation, implied_reason) from loose LLM output."""
    raw = _text(value)
    lowered = raw.lower().strip()
    if not lowered:
        return "track", ""

    first_token = re.split(r"[\s:—-]+", lowered, maxsplit=1)[0]
    if first_token == "review":
        first_token = "read"
    recommendation = first_token if first_token in RECOMMENDATIONS else "track"

    implied_reason = ""
    match = re.match(r"^(read|review|track|ignore)\s*[—:-]\s*(.+)$", raw, flags=re.IGNORECASE)
    if match:
        implied_reason = match.group(2).strip()
    return recommendation, implied_reason


def normalize_corrected_recommendation(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = _text(value)
    first_token = re.split(r"[\s:—-]+", raw.lower().strip(), maxsplit=1)[0]
    if first_token == "review":
        first_token = "read"
    if first_token not in RECOMMENDATIONS:
        return None
    recommendation, _ = normalize_recommendation(raw)
    return recommendation


def _bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "y"} else 0
    return 0


def build_analysis_record(paper_id: str, analysis: dict, retrieved_paper_ids: list[str]) -> dict:
    """Build the DB analysis shape from raw prompt output."""
    record = {
        "paper_id": paper_id,
        "summary": analysis.get("summary", ""),
        "key_contributions": analysis.get("key_contributions", []),
        "is_novel": analysis.get("is_novel"),
        "novelty_explanation": analysis.get("novelty_explanation", ""),
        "extends": analysis.get("extends", []),
        "overlaps_with": analysis.get("overlaps_with", []),
        "relation_to_research": analysis.get("relation_to_my_research", ""),
        "recommendation": analysis.get("recommendation", "track"),
        "recommendation_reason": analysis.get("recommendation_reason", ""),
        "confidence": analysis.get("confidence", "medium"),
        "retrieved_paper_ids": retrieved_paper_ids,
    }
    return normalize_analysis_payload(record)


def normalize_analysis_payload(analysis: dict) -> dict:
    """Coerce an analysis dict into DB-safe values and canonical labels.

    Keep this as the single persistence boundary for prompt output. Ingest,
    reanalysis, and verification should pass loose LLM dictionaries through
    here via db.insert_analysis rather than pre-serializing fields themselves.
    """
    normalized = dict(analysis)

    for field in JSON_FIELDS:
        normalized[field] = _json_array(normalized.get(field))
    for field in TEXT_FIELDS:
        normalized[field] = _text(normalized.get(field))

    recommendation, implied_reason = normalize_recommendation(normalized.get("recommendation"))
    normalized["recommendation"] = recommendation
    if implied_reason and not normalized.get("recommendation_reason"):
        normalized["recommendation_reason"] = implied_reason

    normalized["is_novel"] = _bool(normalized.get("is_novel"))
    return normalized
