"""Shared pipeline thresholds and policy constants."""

from src.config import load_config

_CONFIG = load_config()

STAGE1_COSINE_CUTOFF = _CONFIG.float("pipeline.stage1_cosine_cutoff", 0.35)
STAGE2_RELEVANCE_CUTOFF = _CONFIG.int("pipeline.stage2_relevance_cutoff", 6)
WORKING_SET_ENTRY_THRESHOLD = _CONFIG.int("pipeline.working_set_entry_threshold", 7)
VERIFICATION_TRIGGER = _CONFIG.int("pipeline.verification_trigger", 8)
INGEST_RETRIEVAL_K = _CONFIG.int("pipeline.ingest_retrieval_k", 6)
GRAPH_WORKING_SET_RELEVANCE_FLOOR = WORKING_SET_ENTRY_THRESHOLD
