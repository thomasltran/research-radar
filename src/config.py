"""Central typed accessors for user-editable configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "research_radar.yaml"

load_dotenv()


class AppConfig:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name, {})
        return value if isinstance(value, dict) else {}

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self._data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def str(self, path: str, default: str = "") -> str:
        value = self.get(path, default)
        return str(value) if value is not None else default

    def int(self, path: str, default: int) -> int:
        try:
            return int(self.get(path, default))
        except (TypeError, ValueError):
            return default

    def float(self, path: str, default: float) -> float:
        try:
            return float(self.get(path, default))
        except (TypeError, ValueError):
            return default

    @property
    def research_profile(self) -> dict[str, Any]:
        research = dict(self.section("research"))
        if "description" in research and "research_description" not in research:
            research["research_description"] = research["description"]
        return research

    def prompt_guidance(self, name: str) -> str:
        value = self.get(f"prompts.{name}", "")
        text = str(value).strip() if value is not None else ""
        return f"\n\nAdditional user guidance:\n{text}" if text else ""


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    config_override = os.getenv("RESEARCH_RADAR_CONFIG") or str(DEFAULT_CONFIG_PATH)
    config_path = Path(config_override).expanduser()
    with config_path.open(encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return AppConfig(data)
