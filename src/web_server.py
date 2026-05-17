"""
web_server.py - FastAPI application factory for Research Radar.

This file is intentionally slim: it creates the app, wires middleware,
registers routers, and delegates lifecycle events to the scheduler.
All business logic lives in src/services/ and src/routers/.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from src.core.scheduler import start_scheduler, stop_scheduler
from src.routers import folders, graph, papers, pipeline, runs, stats, tags

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_scheduler(app.state)
    yield
    await stop_scheduler(app.state)


app = FastAPI(title="Research Radar Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(papers.router)
app.include_router(folders.router)
app.include_router(pipeline.router)
app.include_router(runs.router)
app.include_router(graph.router)
app.include_router(tags.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# ── Static frontend ───────────────────────────────────────────────────────────
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    index_path = FRONTEND_DIST / "index.html"
    requested = FRONTEND_DIST / full_path
    if requested.is_file():
        return FileResponse(requested)
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend build not found. Run npm run build in frontend/.")


def main():
    import uvicorn
    reload_enabled = os.getenv("RESEARCH_RADAR_RELOAD", "").lower() in {"1", "true", "yes"}
    uvicorn.run("src.web_server:app", host="127.0.0.1", port=8000, reload=reload_enabled)


if __name__ == "__main__":
    main()
