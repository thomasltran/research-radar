"""routers/stats.py - Workspace stats and prune-action endpoints."""

from fastapi import APIRouter, HTTPException
from src import db, embed, rag
from src.dependencies import get_conn
from src.schemas import PruneActionUpdate

router = APIRouter()


@router.get("/api/stats")
def get_stats():
    conn = get_conn()
    pending_prunes = conn.execute(
        "SELECT COUNT(*) AS count FROM prune_actions WHERE status = 'pending'"
    ).fetchone()["count"]
    return {
        "working_set_count": db.get_working_set_count(conn),
        "pending_prune_count": pending_prunes,
    }


@router.get("/api/prune-actions")
def list_prune_actions(status: str = "pending", limit: int = 10):
    return {"actions": db.list_prune_actions(get_conn(), status=status, limit=limit)}


@router.patch("/api/prune-actions/{action_id}")
def update_prune_action(action_id: int, update: PruneActionUpdate):
    status = update.status
    conn = get_conn()
    action = db.get_prune_action(conn, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Prune action not found")
    if status == "applied":
        db.mark_working_set(conn, action["paper_id"], False)
        embeddings = db.load_embeddings()
        db.rebuild_working_set_index(conn, embeddings)
        ws_papers = db.get_working_set_papers(conn)
        ws_embs = {paper["id"]: embeddings[paper["id"]] for paper in ws_papers if paper["id"] in embeddings}
        if len(ws_embs) >= rag.CLUSTER_MINIMUM:
            rag.cluster_working_set(conn, ws_embs)
        ws_vecs = list(ws_embs.values())
        if ws_vecs:
            embed.save_interest_vector(embed.compute_interest_vector(ws_vecs, previous_vector=embed.load_interest_vector()))
    db.update_prune_action_status(conn, action_id, status)
    return {"action_id": action_id, "status": status}
