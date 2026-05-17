"""Research profile loading helpers."""

from __future__ import annotations

from typing import Iterable

from src.config import load_config


def load_research_profile() -> dict:
    return load_config().research_profile


def allowed_tags() -> list[str]:
    tags = load_research_profile().get("tags", [])
    return [str(tag).strip().lower() for tag in tags if str(tag).strip()]


def canonicalize_tags(tags: Iterable[str] | None, allowed: Iterable[str] | None = None) -> list[str]:
    allowed_map = {
        str(tag).strip().lower(): str(tag).strip().lower()
        for tag in (allowed or allowed_tags())
        if str(tag).strip()
    }
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags or []:
        normalized = str(tag).strip().lower()
        if normalized not in allowed_map or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(allowed_map[normalized])
    return cleaned
