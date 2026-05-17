"""routers/folders.py - Project/folder CRUD and paper membership endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src import db
from src.dependencies import get_conn
from src.schemas import FolderCreate, FolderMembershipUpdate

router = APIRouter()


@router.get("/api/folders")
def list_folders():
    return {"folders": db.list_folders(get_conn())}


@router.post("/api/folders")
def create_folder(update: FolderCreate):
    conn = get_conn()
    try:
        folder = db.create_folder(conn, update.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"folder": folder}


@router.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: int):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM paper_folders WHERE id = ?", (folder_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Folder not found")
    db.delete_folder(conn, folder_id)
    return {"folder_id": folder_id, "deleted": True}


@router.put("/api/folders/{folder_id}/papers/{paper_id}")
def update_folder_membership(folder_id: int, paper_id: str, update: FolderMembershipUpdate):
    conn = get_conn()
    if not db.get_paper(conn, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    if not conn.execute("SELECT 1 FROM paper_folders WHERE id = ?", (folder_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Folder not found")
    db.set_paper_folder_membership(conn, folder_id, paper_id, update.in_folder)
    return {"paper_id": paper_id, "folder_id": folder_id, "in_folder": update.in_folder}
