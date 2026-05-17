"""routers/papers.py - Paper CRUD, notes, and read-state endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src import db
from src.dependencies import get_conn
from src.schemas import FolderMembershipUpdate, NotesUpdate, ReadingStatusUpdate, ReadStateUpdate
from src.services.notes_service import ensure_note_file, extract_notes, replace_notes, sync_note_read_state
from src.services.json_utils import json_load_safe
from src.services.paper_mapping import match_paper_title, normalize_title, paper_row_to_card
from src.services.search_service import fetch_paper_cards
from src.output import OUTPUT_DIR
from src.services.graph_service import digest_for_run

router = APIRouter()


@router.get("/api/papers")
def list_papers(
    q: str | None = None,
    read: bool | None = None,
    reading_status: str | None = None,
    recommendation: str | None = None,
    tag: str | None = None,
    cluster: str | None = None,
    working_set: bool | None = None,
    run_id: str | None = None,
    folder_id: int | None = None,
    semantic: bool = False,
    sort: str = "relevance",
):
    conn = get_conn()
    return {"papers": fetch_paper_cards(
        conn, q=q, read=read, reading_status=reading_status, recommendation=recommendation,
        tag=tag, cluster=cluster, working_set=working_set, run_id=run_id,
        folder_id=folder_id, semantic=semantic, sort=sort,
    )}


@router.get("/api/papers/{paper_id}")
def get_paper(paper_id: str):
    conn = get_conn()
    rows = fetch_paper_cards(conn, q=None)
    card = next((p for p in rows if p["id"] == paper_id), None)
    paper = db.get_paper(conn, paper_id)
    if not paper or not card:
        raise HTTPException(status_code=404, detail="Paper not found")

    summary = db.get_compressed_summary(conn, paper_id)
    analysis = db.get_analysis(conn, paper_id)
    verification_row = conn.execute(
        "SELECT * FROM verifications WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    verification = dict(verification_row) if verification_row else None
    note_path = paper_note_path_for(paper)
    paper_title_to_id = {normalize_title(row["title"]): row["id"] for row in rows}

    def related_items(kind: str, titles: list[str]) -> list[dict]:
        return [{"type": kind, "title": t, "paper_id": match_paper_title(t, paper_title_to_id)} for t in titles]

    return {
        **card,
        "abstract": paper.get("abstract"),
        "doi": paper.get("doi"),
        "source_id": paper.get("source_id"),
        "summary_detail": {
            **summary,
            "contributions": json_load_safe(summary.get("contributions") if summary else None, []),
            "key_terms": json_load_safe(summary.get("key_terms") if summary else None, []),
        } if summary else None,
        "analysis": {
            **analysis,
            "key_contributions": json_load_safe(analysis.get("key_contributions") if analysis else None, []),
            "extends": json_load_safe(analysis.get("extends") if analysis else None, []),
            "overlaps_with": json_load_safe(analysis.get("overlaps_with") if analysis else None, []),
            "retrieved_paper_ids": json_load_safe(analysis.get("retrieved_paper_ids") if analysis else None, []),
        } if analysis else None,
        "related_papers": (
            related_items("extends", json_load_safe(analysis.get("extends"), []))
            + related_items("overlaps_with", json_load_safe(analysis.get("overlaps_with"), []))
        ) if analysis else [],
        "verification": {
            **verification,
            "verified": bool(verification.get("verified")),
            "issues": json_load_safe(verification.get("issues"), []),
        } if verification else None,
        "note": {"exists": note_path.exists(), "path": str(note_path)},
    }


def paper_note_path_for(paper: dict):
    from src.output import paper_note_path  # noqa: PLC0415
    return paper_note_path(paper["title"])


@router.patch("/api/papers/{paper_id}/read")
def update_read_state(paper_id: str, update: ReadStateUpdate):
    conn = get_conn()
    if not db.get_paper(conn, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    db.set_paper_read_state(conn, paper_id, update.read)
    sync_note_read_state(conn, paper_id, update.read)
    return {"paper_id": paper_id, "read": update.read}


@router.patch("/api/papers/{paper_id}/reading-status")
def update_reading_status(paper_id: str, update: ReadingStatusUpdate):
    conn = get_conn()
    if not db.get_paper(conn, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    db.set_paper_reading_status(conn, paper_id, update.reading_status)
    normalized = update.reading_status if update.reading_status in {"reading_list", "currently_reading"} else ""
    return {"paper_id": paper_id, "reading_status": normalized}


@router.get("/api/papers/{paper_id}/notes")
def get_notes(paper_id: str):
    conn = get_conn()
    path = ensure_note_file(conn, paper_id)
    content = path.read_text(encoding="utf-8")
    return {"paper_id": paper_id, "notes": extract_notes(content), "path": str(path)}


@router.get("/api/papers/{paper_id}/note-file")
def get_note_file(paper_id: str):
    conn = get_conn()
    path = ensure_note_file(conn, paper_id)
    return FileResponse(path, media_type="text/markdown", filename=path.name)


@router.put("/api/papers/{paper_id}/notes")
def put_notes(paper_id: str, update: NotesUpdate):
    conn = get_conn()
    path = ensure_note_file(conn, paper_id)
    content = path.read_text(encoding="utf-8")
    path.write_text(replace_notes(content, update.notes), encoding="utf-8")
    return {"paper_id": paper_id, "notes": update.notes, "path": str(path)}
