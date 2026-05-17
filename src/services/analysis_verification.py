"""Verification persistence shared by ingest and maintenance flows."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from src import db
from src.services.analysis_normalization import normalize_corrected_recommendation

ACTIONABLE_PROBLEMS = {"unsupported", "overstated", "misattributed", "fabricated"}


def normalize_verification(verification: dict[str, Any]) -> dict[str, Any]:
    """Drop non-issue verifier chatter and keep stored rows actionable."""
    issues = []
    for issue in verification.get("issues", []) or []:
        if not isinstance(issue, dict):
            continue
        problem = str(issue.get("problem", "")).strip().lower()
        if problem not in ACTIONABLE_PROBLEMS:
            continue
        issues.append({
            "claim": str(issue.get("claim", "")).strip(),
            "problem": problem,
            "detail": str(issue.get("detail", "")).strip(),
        })

    corrected = normalize_corrected_recommendation(verification.get("corrected_recommendation"))
    return {
        "verified": not issues and not corrected,
        "issues": issues,
        "corrected_recommendation": corrected or "",
    }


def persist_verification(
    conn: sqlite3.Connection,
    paper_id: str,
    verification: dict[str, Any],
    analysis_record: dict[str, Any],
) -> str | None:
    """Store verification and apply any corrected recommendation."""
    normalized = normalize_verification(verification)
    db.insert_verification(conn, {
        "paper_id": paper_id,
        "verified": 1 if normalized["verified"] else 0,
        "issues": json.dumps(normalized["issues"]),
        "corrected_recommendation": normalized["corrected_recommendation"],
    })

    corrected = normalized["corrected_recommendation"]
    if not corrected or corrected == analysis_record.get("recommendation"):
        return None

    conn.execute("UPDATE analyses SET recommendation=? WHERE paper_id=?", (corrected, paper_id))
    conn.commit()
    analysis_record["recommendation"] = corrected
    return corrected
