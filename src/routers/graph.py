"""routers/graph.py - Knowledge graph endpoint."""

from fastapi import APIRouter
from src.dependencies import get_conn
from src.services.graph_service import build_graph

router = APIRouter()


@router.get("/api/graph")
def get_graph():
    return build_graph(get_conn())
