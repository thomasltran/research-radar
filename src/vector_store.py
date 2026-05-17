"""FAISS index and embedding persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from src.config import load_config

EMBEDDING_DIM = load_config().int("embeddings.dimension", 768)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.npz"


def index_path(name: str) -> Path:
    return DATA_DIR / f"{name}.faiss"


def ws_id_map_path() -> Path:
    return DATA_DIR / "ws_id_map.json"


def create_empty_index() -> faiss.IndexFlatIP:
    """Create a new empty FAISS flat inner-product index."""
    return faiss.IndexFlatIP(EMBEDDING_DIM)


def _normalized_vector(embedding: np.ndarray) -> np.ndarray:
    vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
    if vec.shape[1] != EMBEDDING_DIM:
        raise ValueError(f"Expected embedding dimension {EMBEDDING_DIM}, got {vec.shape[1]}")
    faiss.normalize_L2(vec)
    return vec


def save_index(index: faiss.IndexFlatIP, name: str) -> None:
    """Persist a FAISS index to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path(name)))


def load_index(name: str) -> faiss.IndexFlatIP:
    """Load a FAISS index from disk, or create empty if not found."""
    path = index_path(name)
    if path.exists():
        return faiss.read_index(str(path))
    return create_empty_index()


def add_to_index(index: faiss.IndexFlatIP, embedding: np.ndarray) -> int:
    """Add one embedding and return its FAISS position."""
    vec = _normalized_vector(embedding)
    position = index.ntotal
    index.add(vec)
    return position


def search_index(index: faiss.IndexFlatIP, query_embedding: np.ndarray,
                 k: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Search the index for top-k nearest neighbors."""
    vec = _normalized_vector(query_embedding)
    k = min(k, index.ntotal)
    if k == 0:
        return np.array([[]]), np.array([[]])
    distances, indices = index.search(vec, k)
    return distances, indices


def save_ws_id_map(ws_map: dict[int, str]) -> None:
    """Persist the working set FAISS position to paper_id mapping."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {str(k): v for k, v in ws_map.items()}
    ws_id_map_path().write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def load_ws_id_map() -> dict[int, str]:
    """Load the working set FAISS position to paper_id mapping."""
    path = ws_id_map_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in data.items()}


def save_embeddings(embeddings_by_id: dict[str, np.ndarray]) -> None:
    """Persist paper embeddings to disk, merging with existing vectors."""
    existing = load_embeddings()
    existing.update(embeddings_by_id)
    if not existing:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        str(EMBEDDINGS_PATH),
        ids=np.array(list(existing.keys())),
        vectors=np.stack(list(existing.values())),
    )


def load_embeddings() -> dict[str, np.ndarray]:
    """Load persisted paper embeddings."""
    if not EMBEDDINGS_PATH.exists():
        return {}
    data = np.load(str(EMBEDDINGS_PATH), allow_pickle=True)
    return {str(pid): vec for pid, vec in zip(data["ids"], data["vectors"])}
