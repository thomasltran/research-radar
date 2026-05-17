"""Shared JSON coercion helpers for DB-backed fields."""

from __future__ import annotations

import json
from typing import Any


def json_load_safe(value: Any, default: Any = None) -> Any:
    """Return parsed JSON for strings, pass through structured values."""
    if default is None:
        default = []
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
