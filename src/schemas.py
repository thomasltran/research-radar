"""
schemas.py - Pydantic request/response models for the Research Radar API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ReadStateUpdate(BaseModel):
    read: bool


class ReadingStatusUpdate(BaseModel):
    reading_status: Literal["", "reading_list", "currently_reading"] = ""


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Folder name is required")
        return normalized


class FolderMembershipUpdate(BaseModel):
    in_folder: bool = True


class NotesUpdate(BaseModel):
    notes: str = Field(max_length=200_000)


class PipelineRunRequest(BaseModel):
    run_type: str = "manual"
    source_mode: str = "both"
    scan_start: str | None = None
    scan_end: str | None = None


class PipelineScheduleUpdate(BaseModel):
    enabled: bool = False
    time: str = "09:00"
    source_mode: str = "both"


class MaintenanceRunRequest(BaseModel):
    mode: Literal["relink", "reanalyze"] = "relink"
    working_set_only: bool = False
    all_papers: bool = False


class PruneActionUpdate(BaseModel):
    status: Literal["applied", "kept"]
