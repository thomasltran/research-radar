"""routers/tags.py - Tag statistics endpoint."""

from fastapi import APIRouter
from src import db
from src.dependencies import get_conn
from src.profile import canonicalize_tags, load_research_profile
from src.services.json_utils import json_load_safe

router = APIRouter()


@router.get("/api/tags")
def list_tags():
    conn = get_conn()
    allowed = set(load_research_profile().get("tags", []))
    rows = conn.execute("""
        SELECT p.id, p.in_working_set, COALESCE(prs.read, 0) AS read, cs.key_terms
        FROM papers p
        JOIN compressed_summaries cs ON cs.paper_id = p.id
        LEFT JOIN paper_read_state prs ON prs.paper_id = p.id
    """).fetchall()
    tags: dict[str, dict] = {}
    for row in rows:
        for tag in canonicalize_tags(json_load_safe(row["key_terms"], []), allowed):
            item = tags.setdefault(tag, {"tag": tag, "count": 0, "unread_count": 0, "working_set_count": 0})
            item["count"] += 1
            item["unread_count"] += 0 if row["read"] else 1
            item["working_set_count"] += 1 if row["in_working_set"] else 0
    return {"tags": sorted(tags.values(), key=lambda x: (-x["count"], x["tag"]))}
