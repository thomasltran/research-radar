"""
embed.py — Embedding generation using bge-base via sentence-transformers.

Handles:
  - Model loading (lazy singleton)
  - Single and batch abstract embedding
  - Interest vector computation (EMA of working set)
"""

import json
import logging
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

from src.config import load_config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Model singleton
# ──────────────────────────────────────────────

_CONFIG = load_config()
_model = None
MODEL_NAME = _CONFIG.str("embeddings.model_name", "BAAI/bge-base-en-v1.5")
EMBEDDING_DIM = _CONFIG.int("embeddings.dimension", 768)
INTEREST_ALPHA = _CONFIG.float("embeddings.interest_alpha", 0.7)
INTEREST_VECTOR_PATH = Path(__file__).resolve().parent.parent / "data" / "interest_vector.npy"


def get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {MODEL_NAME}")
        try:
            _model = SentenceTransformer(MODEL_NAME, local_files_only=True)
        except TypeError:
            _model = SentenceTransformer(MODEL_NAME)
        except Exception:
            logger.warning("Local embedding model cache unavailable; retrying with default loader")
            _model = SentenceTransformer(MODEL_NAME)
        logger.info("Embedding model loaded.")
    return _model


# ──────────────────────────────────────────────
# Embedding generation
# ──────────────────────────────────────────────

def embed_text(text: str) -> np.ndarray:
    """
    Embed a single text string. Returns a 768-dim float32 vector.
    The vector is L2-normalized for cosine similarity via inner product.
    """
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def embed_texts(texts: list[str]) -> np.ndarray:
    """
    Embed a batch of text strings. Returns (N, 768) float32 array.
    All vectors are L2-normalized.
    """
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 10)
    return np.asarray(vecs, dtype=np.float32)


def embed_abstract(abstract: str) -> np.ndarray:
    """
    Embed a paper abstract with the recommended bge-base prefix.
    BGE models benefit from a task-specific prefix for retrieval.
    """
    # For bge models, prepend instruction for better retrieval quality
    prefixed = f"Represent this scientific abstract for retrieval: {abstract}"
    return embed_text(prefixed)


def embed_query(query: str) -> np.ndarray:
    """
    Embed a search query with the recommended bge-base query prefix.
    """
    prefixed = f"Represent this sentence for searching relevant passages: {query}"
    return embed_text(prefixed)


# ──────────────────────────────────────────────
# Interest vector (EMA of working set embeddings)
# ──────────────────────────────────────────────

def compute_interest_vector(
    working_set_embeddings: list[np.ndarray],
    previous_vector: Optional[np.ndarray] = None,
    alpha: float = INTEREST_ALPHA,
) -> np.ndarray:
    """
    Compute the interest vector as an exponential moving average:
        interest = alpha * previous + (1 - alpha) * mean(working_set)
    
    If no previous vector exists (cold start), returns mean(working_set).
    
    Args:
        working_set_embeddings: list of embedding vectors for working set papers
        previous_vector: the previous interest vector, or None for cold start
        alpha: decay factor (0.7 = heavy weight on history)
    
    Returns:
        Normalized interest vector (768-dim float32)
    """
    if not working_set_embeddings:
        raise ValueError("Cannot compute interest vector from empty working set")

    ws_mean = np.mean(np.stack(working_set_embeddings), axis=0).astype(np.float32)

    if previous_vector is None:
        # Cold start: pure mean of seed embeddings
        vec = ws_mean
    else:
        vec = alpha * previous_vector + (1 - alpha) * ws_mean

    # Normalize
    vec = vec.reshape(1, -1)
    faiss.normalize_L2(vec)
    return vec.flatten()


def save_interest_vector(vector: np.ndarray) -> None:
    """Persist the interest vector to disk."""
    INTEREST_VECTOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(INTEREST_VECTOR_PATH), vector)
    logger.info(f"Interest vector saved to {INTEREST_VECTOR_PATH}")


def load_interest_vector() -> Optional[np.ndarray]:
    """Load the interest vector from disk, or return None if not found."""
    if INTEREST_VECTOR_PATH.exists():
        return np.load(str(INTEREST_VECTOR_PATH))
    return None


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.
    Assumes both are already L2-normalized (from our embedding pipeline).
    """
    return float(np.dot(vec_a.flatten(), vec_b.flatten()))
