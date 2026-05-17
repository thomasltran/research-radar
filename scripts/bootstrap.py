"""
bootstrap.py — Cold Start Bootstrap Script.

Seeds the system with the initial papers from config/research_radar.yaml:
  1. Fetches abstracts from Semantic Scholar by title search
  2. Generates embeddings for each seed paper
  3. Runs Prompt 2 (Compression) to create LLM-ready summaries
  4. Inserts papers into SQLite with in_working_set=1, relevance_score=10
  5. Populates both FAISS indices
  6. Computes and saves the initial interest vector
"""

import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import yaml
from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv()
S2_API_KEY = os.getenv("S2_API_KEY")

ROOT_DIR = Path(__file__).resolve().parent.parent

# Add project root to path for direct script execution.
sys.path.insert(0, str(ROOT_DIR))

from src import db, embed, llm
from src.config import DEFAULT_CONFIG_PATH, load_config
from src.profile import canonicalize_tags

_CONFIG = load_config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bootstrap")

# ──────────────────────────────────────────────
# Semantic Scholar API
# ──────────────────────────────────────────────

S2_API_BASE = "https://api.semanticscholar.org/graph/v1"


def search_paper_by_title(title: str) -> dict | None:
    """
    Search Semantic Scholar for a paper by title.
    Returns a dict with paperId, title, abstract, authors, url, externalIds, year.
    """
    # Clean title for search — strip venue/year annotations in parentheses
    clean_title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()

    url = f"{S2_API_BASE}/paper/search"
    params = {
        "query": clean_title,
        "limit": 5,
        "fields": "paperId,title,abstract,tldr,authors,url,externalIds,year,publicationDate",
    }

    data = {"data": []}
    headers = {"User-Agent": "ResearchRadar/1.0"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY
        
    for attempt in range(7):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 429:
                wait = min(300, 5 * (2 ** attempt))
                logger.warning(f"S2 rate limit hit, waiting {wait}s (attempt {attempt+1}/7)...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as e:
            logger.warning(f"S2 search attempt {attempt + 1}/7 failed: {e}")
            if attempt < 6:
                wait = min(300, 5 * (2 ** attempt))
                time.sleep(wait)
            else:
                return None

    papers = data.get("data", [])
    if not papers:
        logger.warning(f"No results found for: {title}")
        return None

    # Find best match — prefer exact title match
    for paper in papers:
        if paper.get("abstract") or paper.get("tldr"):
            return paper

    # Fallback: first result even without abstract
    return papers[0] if papers else None


# ──────────────────────────────────────────────
# Bootstrap logic
# ──────────────────────────────────────────────

def _arxiv_result_to_dict(result) -> dict:
    """Convert an arxiv.Result to our normalized dict format."""
    return {
        "title": result.title,
        "abstract": result.summary.replace('\n', ' '),
        "authors": [{"name": a.name} for a in result.authors],
        "url": result.entry_id,
        "year": result.published.year if result.published else None,
        "paperId": result.entry_id.split('/abs/')[-1],
    }


def search_arxiv_by_title(title: str) -> Optional[dict]:
    """
    Search Arxiv by title using multiple strategies.
    Validates results with fuzzy title matching to avoid false positives.
    """
    import arxiv
    clean_title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    client = arxiv.Client()
    match_threshold = _CONFIG.int("bootstrap.arxiv_title_match_threshold", 80)

    # Strategy 1: Exact quoted title search
    queries = [
        f'ti:"{clean_title}"',
    ]
    # Strategy 2: If title has a subtitle (colon), also try the full title unquoted
    if ':' in clean_title:
        # Use key terms from both parts
        parts = clean_title.split(':')
        main_words = parts[0].strip().split()[:4]
        sub_words = parts[1].strip().split()[:4]
        all_words = main_words + sub_words
        queries.append(' AND '.join(f'ti:{w}' for w in all_words if len(w) > 2))
    # Strategy 3: General keyword search with important words
    important = [w for w in clean_title.replace(':', ' ').split() if len(w) > 3]
    if len(important) > 3:
        queries.append(' AND '.join(f'ti:{w}' for w in important[:6]))

    for query in queries:
        search = arxiv.Search(
            query=query,
            max_results=5,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        for attempt in range(3):
            try:
                for result in client.results(search):
                    score = fuzz.ratio(clean_title.lower(), result.title.lower())
                    if score >= match_threshold and result.summary and result.summary.strip():
                        logger.info(f"  → Arxiv match (score={score}): {result.title}")
                        return _arxiv_result_to_dict(result)
                break  # No results for this query, try next strategy
            except Exception as e:
                logger.warning(f"Arxiv search attempt {attempt+1}/3 failed: {e}")
                time.sleep(3)
        time.sleep(0.5)

    return None


def run_bootstrap(config_path: str | None = None, run_id: int | None = None):
    """Execute the cold start bootstrap."""
    conn = db.get_connection()
    db.init_schema(conn)

    if config_path is None:
        profile = load_config().research_profile
    else:
        config_path = Path(config_path)
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        profile = config.get("research", config)
        if "description" in profile and "research_description" not in profile:
            profile["research_description"] = profile["description"]

    seed_papers = profile.get("seed_papers", [])
    if not seed_papers:
        logger.error(f"No seed papers found in {DEFAULT_CONFIG_PATH.name}")
        if run_id is not None:
            db.complete_pipeline_run(conn, run_id, "failed", error_details="No seed papers found")
        return

    logger.info(f"Bootstrapping with {len(seed_papers)} seed papers...")

    # Check if already bootstrapped
    ws_count = db.get_working_set_count(conn)
    if ws_count > 0:
        logger.info(f"Working set already has {ws_count} papers. Skipping bootstrap.")
        logger.info("Delete data/research.db to re-bootstrap.")
        if run_id is not None:
            db.complete_pipeline_run(conn, run_id, "failed", error_details="Database already bootstrapped")
        return

    # Initialize FAISS indices
    index_all = db.create_empty_index()
    index_ws = db.create_empty_index()
    ws_map: dict[int, str] = {}
    embeddings: dict[str, np.ndarray] = {}

    successful = 0
    analyses = []
    papers_by_id = {}

    for i, seed in enumerate(seed_papers, 1):
        title = seed["title"]
        logger.info(f"[{i}/{len(seed_papers)}] Processing: {title}")

        # 1. Fetch from Semantic Scholar first (we have API key), fallback to Arxiv
        paper_data = search_paper_by_title(title)
        source_name = "Semantic Scholar"
        
        if not paper_data:
            logger.info(f"  → Semantic Scholar failed, falling back to Arxiv...")
            paper_data = search_arxiv_by_title(title)
            source_name = "Arxiv"

        if not paper_data:
            logger.error(f"  ✗ Could not find paper on Arxiv or Semantic Scholar")
            continue

        abstract = paper_data.get("abstract")
        if not abstract and paper_data.get("tldr"):
            abstract = paper_data["tldr"].get("text")
            
        if not abstract:
            logger.error(f"  ✗ Paper found but no abstract/tldr available")
            continue

        logger.info(f"  ✓ Found ({source_name}): {paper_data['title']}")

        # 2. Generate embedding
        logger.info(f"  → Generating embedding...")
        paper_embedding = embed.embed_abstract(abstract)

        # 3. Generate compressed summary via LLM
        logger.info(f"  → Generating compressed summary (LLM)...")
        try:
            compression = llm.prompt_compression(paper_data["title"], abstract, profile)
        except Exception as e:
            logger.error(f"  ✗ LLM compression failed: {e}")
            # Use a basic fallback summary
            compression = {
                "contributions": [f"See abstract for details on {title}"],
                "method": "See abstract",
                "key_terms": [],
                "domain": seed.get("focus", "systems"),
            }

        # 4. Prepare paper record
        paper_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Extract metadata
        authors = [a.get("name", "Unknown") for a in paper_data.get("authors", [])]
        ext_ids = paper_data.get("externalIds", {}) or {}
        doi = ext_ids.get("DOI")
        arxiv_id = ext_ids.get("ArXiv")

        # Insert into DB
        paper_rec = {
            "id": paper_id,
            "title": paper_data["title"],
            "authors": json.dumps([a.get("name") for a in paper_data.get("authors", [])]),
            "abstract": abstract,
            "source": "bootstrap",
            "source_id": str(paper_data.get("paperId", "")),
            "url": paper_data.get("url", ""),
            "doi": paper_data.get("externalIds", {}).get("DOI") if "externalIds" in paper_data else None,
            "published_date": str(paper_data.get("year", "")) or None,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "run_id": None,  # seed papers have no run
            "relevance_score": 10,
            "paper_type": "system",  # reasonable default for systems papers
            "matching_topics": json.dumps(profile.get("topics", [])),
            "in_working_set": 1,
            "faiss_id": None,
            "added_to_ws_at": now,
        }

        # 5. Insert into database
        inserted = db.insert_paper(conn, paper_rec)
        if not inserted:
            logger.warning(f"  ⚠ Paper already exists in database (duplicate)")
            continue

        # Add to FAISS only after the DB insert succeeds, so duplicate seeds do not
        # leave dangling vectors or working-set ID map entries.
        faiss_pos = db.add_to_index(index_all, paper_embedding)
        db.update_paper_faiss_id(conn, paper_id, faiss_pos)
        ws_pos = db.add_to_index(index_ws, paper_embedding)
        ws_map[ws_pos] = paper_id
        embeddings[paper_id] = paper_embedding
        paper_rec["faiss_id"] = faiss_pos

        # 6. Insert compressed summary
        key_terms = canonicalize_tags(compression.get("key_terms", []), profile.get("tags", []))
        summary_record = {
            "paper_id": paper_id,
            "contributions": json.dumps(compression.get("contributions", [])),
            "method": compression.get("method", ""),
            "key_terms": json.dumps(key_terms),
            "domain": compression.get("domain", ""),
        }
        db.insert_compressed_summary(conn, summary_record)

        papers_by_id[paper_id] = paper_rec
        analysis_record = {
            "paper_id": paper_id,
            "title": paper_data["title"],
            "summary": f"**[Seed Paper]**\n\n{abstract}",
            "key_contributions": json.dumps(compression.get("contributions", [])),
            "is_novel": True,
            "novelty_explanation": "Seed paper manually selected during bootstrap.",
            "relation_to_research": "Foundational seed paper for the research profile.",
            "recommendation": "read",
            "recommendation_reason": "Curated seed paper.",
            "extends": "[]",
            "overlaps_with": "[]",
            "confidence": "high"
        }
        db.insert_analysis(conn, analysis_record)
        analyses.append(analysis_record)

        successful += 1
        logger.info(f"  ✓ Successfully bootstrapped ({successful}/{len(seed_papers)})")

        # Rate limit for S2 API (100 req/5 min for unauthenticated)
        if i < len(seed_papers):
            time.sleep(_CONFIG.float("bootstrap.seed_request_delay_seconds", 1.5))

    if successful == 0:
        logger.error("Bootstrap failed — no papers were successfully processed")
        if run_id is not None:
            db.complete_pipeline_run(conn, run_id, "failed", error_details="No papers were successfully processed")
        return

    # Generate Markdown notes for the seed papers
    try:
        from src.output import generate_paper_notes
        generate_paper_notes(conn, analyses, papers_by_id)
        logger.info("Generated Markdown notes for seed papers")
    except Exception as e:
        logger.error(f"Failed to generate notes for seed papers: {e}")

    # 7. Save FAISS indices
    db.save_index(index_all, "index_all")
    db.save_index(index_ws, "index_ws")
    db.save_ws_id_map(ws_map)
    logger.info(f"FAISS indices saved (all: {index_all.ntotal}, ws: {index_ws.ntotal})")

    # 8. Persist embeddings to disk for future pipeline runs
    db.save_embeddings(embeddings)
    logger.info(f"Embeddings persisted ({len(embeddings)} vectors)")

    # 9. Compute and save initial interest vector
    ws_embeddings = list(embeddings.values())
    interest_vector = embed.compute_interest_vector(ws_embeddings, previous_vector=None)
    embed.save_interest_vector(interest_vector)
    logger.info("Initial interest vector computed and saved")

    logger.info(f"\n{'='*60}")
    logger.info(f"Bootstrap complete!")
    logger.info(f"  Papers seeded:      {successful}/{len(seed_papers)}")
    logger.info(f"  FAISS all_papers:    {index_all.ntotal} vectors")
    logger.info(f"  FAISS working_set:   {index_ws.ntotal} vectors")
    logger.info(f"  Interest vector:     saved")
    logger.info(f"{'='*60}")


    if run_id is not None:
        db.complete_pipeline_run(conn, run_id, "success", papers_fetched=successful, papers_added_ws=successful)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bootstrap the Research Radar database.")
    parser.add_argument("config", nargs="?", help="Optional path to research_radar.yaml")
    parser.add_argument("--run-id", type=int, help="Optional pipeline run ID")
    args = parser.parse_args()

    try:
        run_bootstrap(args.config, args.run_id)
    except Exception as e:
        logger.exception("Bootstrap failed with an unhandled error")
        if args.run_id is not None:
            conn = db.get_connection()
            db.complete_pipeline_run(conn, args.run_id, "failed", error_details=str(e))
        sys.exit(1)
