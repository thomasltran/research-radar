"""Shared recommendation policy gates."""

from __future__ import annotations

from src.pipeline_policy import VERIFICATION_TRIGGER, WORKING_SET_ENTRY_THRESHOLD


def effective_recommendation(recommendation: str | None, score: int | float | None) -> str | None:
    """Apply current product gates to persisted recommendation labels."""
    normalized = (recommendation or "").lower()
    if normalized not in {"read", "track", "ignore"}:
        return None
    if normalized == "read" and (score or 0) < WORKING_SET_ENTRY_THRESHOLD:
        return "track"
    return normalized


def apply_review_policy(analysis_record: dict, paper: dict) -> dict:
    """Keep scarce Review recommendations aligned with the numeric relevance gate."""
    score = paper.get("relevance_score") or 0
    if analysis_record.get("recommendation") == "read" and score < WORKING_SET_ENTRY_THRESHOLD:
        reason = analysis_record.get("recommendation_reason", "")
        analysis_record["recommendation"] = "track"
        analysis_record["recommendation_reason"] = (
            f"{reason} Demoted from Review because relevance score {score} is below "
            f"the working-set threshold {WORKING_SET_ENTRY_THRESHOLD}."
        ).strip()
    return analysis_record


def should_verify_analysis(analysis_record: dict, paper: dict) -> bool:
    """Verify anything shown in Review plus high-score papers."""
    recommendation = effective_recommendation(
        analysis_record.get("recommendation"),
        paper.get("relevance_score"),
    )
    score = paper.get("relevance_score") or 0
    return recommendation == "read" or score >= VERIFICATION_TRIGGER
