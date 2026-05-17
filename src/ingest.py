"""
ingest.py — Paper fetching logic using Arxiv and Semantic Scholar APIs.

Handles:
  - Arxiv paper search using the arxiv Python package
  - Semantic Scholar REST API search
  - Deduplication (DOI primary, rapidfuzz title fallback)
  - Normalization into unified Paper schema
"""
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz

from src.config import load_config

load_dotenv()
S2_API_KEY = os.getenv("S2_API_KEY")
_CONFIG = load_config()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
DEDUP_FUZZY_THRESHOLD = _CONFIG.int("dedup.fuzzy_title_threshold", 90)
DEFAULT_MAX_PER_SOURCE = _CONFIG.int("ingestion.max_per_source", 50)
SOURCE_REQUEST_DELAY_SECONDS = _CONFIG.float("ingestion.source_request_delay_seconds", 1.5)


# ──────────────────────────────────────────────
# Arxiv Ingestion
# ──────────────────────────────────────────────

def fetch_arxiv_papers(keywords: list[str], since: Optional[str] = None,
                       until: Optional[str] = None,
                       max_results: int = 50) -> list[dict]:
    """
    Fetch papers from Arxiv matching the given keywords.
    
    Args:
        keywords: list of topic strings to search for
        since: ISO 8601 timestamp — only fetch papers submitted after this
        max_results: max papers to fetch per query
    
    Returns:
        List of normalized paper dicts
    """
    import arxiv

    papers = []
    seen_ids = set()
    attempted_queries = 0
    failed_queries = 0

    # Build search queries from keywords
    for keyword in keywords:
        # Clean keyword for arxiv query (split into boolean terms)
        words = [w for w in re.split(r'\W+', keyword) if len(w) > 3]
        if not words:
            continue
        attempted_queries += 1
        
        # Use up to 4 significant words to avoid over-constraining the search
        query = " AND ".join(f'abs:{w}' for w in words[:4])

        logger.info(f"Arxiv search: {query}")
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        query_succeeded = False
        for attempt in range(7):
            try:
                for result in client.results(search):
                    # Filter by date range if provided.
                    published = result.published.replace(tzinfo=timezone.utc)
                    if since:
                        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                        if published < since_dt:
                            continue
                    if until:
                        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                        if published > until_dt:
                            continue

                    arxiv_id = result.entry_id.split("/abs/")[-1]
                    if arxiv_id in seen_ids:
                        continue
                    seen_ids.add(arxiv_id)

                    paper = _normalize_arxiv_result(result, arxiv_id)
                    papers.append(paper)
                query_succeeded = True
                break
            except Exception as e:
                logger.error(f"Arxiv search attempt {attempt + 1}/7 failed for '{keyword}': {e}")
                if attempt < 6:
                    wait = min(300, 5 * (2 ** attempt))
                    time.sleep(wait)
                else:
                    break
        if not query_succeeded:
            failed_queries += 1

        # Be polite to the API
        time.sleep(1)

    if attempted_queries > 0 and failed_queries == attempted_queries:
        raise RuntimeError("All arXiv searches failed")
    if failed_queries:
        logger.warning("Arxiv: %s/%s searches failed", failed_queries, attempted_queries)
    logger.info(f"Arxiv: fetched {len(papers)} papers total")
    return papers


def _normalize_arxiv_result(result, arxiv_id: str) -> dict:
    """Convert an arxiv.Result to our normalized paper dict."""
    return {
        "id": str(uuid.uuid4()),
        "title": result.title.strip(),
        "authors": json.dumps([a.name for a in result.authors]),
        "abstract": result.summary.strip(),
        "source": "arxiv",
        "source_id": arxiv_id,
        "url": result.entry_id,
        "doi": result.doi,
        "published_date": result.published.isoformat() if result.published else None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "run_id": None,  # set later by pipeline
        "relevance_score": None,
        "paper_type": None,
        "matching_topics": None,
        "in_working_set": 0,
        "faiss_id": None,
        "added_to_ws_at": None,
    }


# ──────────────────────────────────────────────
# Semantic Scholar Ingestion
# ──────────────────────────────────────────────

def fetch_s2_papers(keywords: list[str], since: Optional[str] = None,
                    until: Optional[str] = None,
                    max_results: int = 50) -> list[dict]:
    """
    Fetch papers from Semantic Scholar matching the given keywords.
    
    Args:
        keywords: list of topic strings to search for
        since: ISO 8601 date string — only fetch papers published after this
        max_results: max papers to return total (across all keywords)
    
    Returns:
        List of normalized paper dicts
    """
    papers = []
    seen_ids = set()
    per_keyword_limit = max(10, max_results // len(keywords)) if keywords else max_results
    attempted_queries = 0
    failed_queries = 0

    for keyword in keywords:
        attempted_queries += 1
        logger.info(f"S2 search: {keyword}")

        params = {
            "query": keyword,
            "limit": min(per_keyword_limit, 100),  # S2 max is 100
            "fields": "paperId,title,abstract,tldr,authors,url,externalIds,year,publicationDate",
        }

        if since or until:
            since_date = since[:10] if since else ""
            until_date = until[:10] if until else ""
            params["publicationDateOrYear"] = f"{since_date}:{until_date}"

        data = {"data": []}  # default in case all retries fail
        query_succeeded = False
        headers = {"User-Agent": "ResearchRadar/1.0"}
        if S2_API_KEY:
            headers["x-api-key"] = S2_API_KEY
            
        for attempt in range(7):
            try:
                resp = requests.get(
                    f"{S2_API_BASE}/paper/search",
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = min(300, 5 * (2 ** attempt))
                    logger.warning(f"S2 rate limit, waiting {wait}s (attempt {attempt+1}/7)...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                query_succeeded = True
                break
            except requests.exceptions.RequestException as e:
                logger.error(f"S2 search attempt {attempt + 1}/7 failed: {e}")
                if attempt < 6:
                    wait = min(300, 5 * (2 ** attempt))
                    time.sleep(wait)
        if not query_succeeded:
            failed_queries += 1

        for item in data.get("data", []):
            s2_id = item.get("paperId", "")
            if s2_id in seen_ids or not (item.get("abstract") or item.get("tldr")):
                continue
            seen_ids.add(s2_id)

            paper = _normalize_s2_result(item)
            papers.append(paper)

        # Avoid hammering public APIs across broad topic lists.
        time.sleep(SOURCE_REQUEST_DELAY_SECONDS)

    if attempted_queries > 0 and failed_queries == attempted_queries:
        raise RuntimeError("All Semantic Scholar searches failed")
    if failed_queries:
        logger.warning("Semantic Scholar: %s/%s searches failed", failed_queries, attempted_queries)
    logger.info(f"Semantic Scholar: fetched {len(papers)} papers total")
    return papers


def _normalize_s2_result(item: dict) -> dict:
    """Convert a Semantic Scholar API result to our normalized paper dict."""
    ext_ids = item.get("externalIds", {}) or {}
    authors = [a.get("name", "Unknown") for a in item.get("authors", [])]
    
    abstract = item.get("abstract")
    if not abstract and item.get("tldr"):
        abstract = item["tldr"].get("text", "")
    abstract = abstract or ""

    return {
        "id": str(uuid.uuid4()),
        "title": item.get("title", "").strip(),
        "authors": json.dumps(authors),
        "abstract": abstract.strip(),
        "source": "semantic_scholar",
        "source_id": item.get("paperId", ""),
        "url": item.get("url", ""),
        "doi": ext_ids.get("DOI"),
        "published_date": item.get("publicationDate"),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "run_id": None,
        "relevance_score": None,
        "paper_type": None,
        "matching_topics": None,
        "in_working_set": 0,
        "faiss_id": None,
        "added_to_ws_at": None,
    }


# ──────────────────────────────────────────────
# Combined Ingestion
# ──────────────────────────────────────────────

def fetch_all_papers(profile: dict, since: Optional[str] = None,
                     until: Optional[str] = None,
                     max_per_source: int | None = None) -> list[dict]:
    """
    Fetch papers from all sources using the research profile keywords.
    
    Args:
        profile: research_profile dict with 'topics' key
        since: ISO 8601 timestamp for incremental fetch
        max_per_source: max results per source
    
    Returns:
        Combined, deduplicated list of normalized paper dicts
    """
    topics = profile.get("topics", [])
    if not topics:
        raise RuntimeError("No topics defined in research profile")
    max_per_source = max_per_source or DEFAULT_MAX_PER_SOURCE

    # Determine which sources to fetch from; env var is a runtime override.
    fetch_source = os.getenv("FETCH_SOURCE", _CONFIG.str("pipeline.default_fetch_source", "both")).lower()

    arxiv_papers = []
    s2_papers = []
    source_errors: dict[str, str] = {}

    if fetch_source in ("arxiv", "both"):
        try:
            arxiv_papers = fetch_arxiv_papers(topics, since=since, until=until, max_results=max_per_source)
        except Exception as exc:
            source_errors["arxiv"] = str(exc)
            logger.exception("Arxiv fetch failed")
        
    if fetch_source in ("s2", "both", "semantic_scholar"):
        try:
            s2_papers = fetch_s2_papers(topics, since=since, until=until, max_results=max_per_source)
        except Exception as exc:
            source_errors["semantic_scholar"] = str(exc)
            logger.exception("Semantic Scholar fetch failed")

    selected_sources = []
    if fetch_source in ("arxiv", "both"):
        selected_sources.append("arxiv")
    if fetch_source in ("s2", "both", "semantic_scholar"):
        selected_sources.append("semantic_scholar")
    if selected_sources and all(source in source_errors for source in selected_sources):
        detail = "; ".join(f"{source}: {error}" for source, error in source_errors.items())
        raise RuntimeError(f"All selected sources failed: {detail}")

    # Cross-source dedup
    combined = arxiv_papers.copy()
    for paper in s2_papers:
        if not _is_duplicate(paper, combined):
            combined.append(paper)

    logger.info(f"Combined: {len(combined)} unique papers "
                f"(arxiv: {len(arxiv_papers)}, s2: {len(s2_papers)})")
    return combined


# ──────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────

def _is_duplicate(paper: dict, existing: list[dict]) -> bool:
    """
    Check if a paper is a duplicate of any in the existing list.
    Uses DOI (exact match) first, then fuzzy title matching.
    """
    doi = paper.get("doi")
    title = paper.get("title", "")

    for ex in existing:
        # DOI match (primary)
        if doi and ex.get("doi") and doi == ex["doi"]:
            return True

        # Fuzzy title match (fallback)
        ex_title = ex.get("title", "")
        if title and ex_title:
            score = fuzz.ratio(title.lower(), ex_title.lower())
            if score >= DEDUP_FUZZY_THRESHOLD:
                return True

    return False


def is_duplicate_in_db(conn, paper: dict) -> bool:
    """
    Check if a paper already exists in the database.
    Checks DOI, source+source_id, and fuzzy title match.
    """
    from src import db

    # Check DOI
    if paper.get("doi") and db.paper_exists_by_doi(conn, paper["doi"]):
        return True

    # Check source + source_id
    if paper.get("source_id") and db.paper_exists_by_source(conn, paper["source"], paper["source_id"]):
        return True

    # Fuzzy title check against recent papers
    title = paper.get("title", "")
    if title:
        rows = conn.execute(
            "SELECT title FROM papers ORDER BY ingested_at DESC LIMIT 500"
        ).fetchall()
        for row in rows:
            if fuzz.ratio(title.lower(), row["title"].lower()) >= DEDUP_FUZZY_THRESHOLD:
                return True

    return False
