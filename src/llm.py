"""
llm.py — Ollama LLM client with robust JSON parsing.

Handles:
  - Ollama API communication (chat completions)
  - Forced JSON output with markdown-stripping fallback
  - All 5 prompt templates (relevance, compression, analysis, verification, pruning)
  - Retry logic for transient failures
"""

import json
import logging
import os
import re
import signal
import threading
import time
from contextlib import contextmanager
import requests

from src.config import load_config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

_CONFIG = load_config()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", _CONFIG.str("llm.ollama_base_url", "http://localhost:11434"))
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", _CONFIG.str("llm.default_model", "qwen2.5:14b"))
MAX_RETRIES = _CONFIG.int("llm.max_retries", 3)
RETRY_DELAY = _CONFIG.int("llm.retry_delay_seconds", 2)
WALL_CLOCK_GRACE = _CONFIG.int("llm.wall_clock_grace_seconds", 15)
DEFAULT_TEMPERATURE = _CONFIG.float("llm.default_temperature", 0.1)
DEFAULT_TIMEOUT = _CONFIG.int("llm.default_timeout_seconds", 120)
RELEVANCE_TIMEOUT = _CONFIG.int("llm.relevance_timeout_seconds", 75)


class LLMTimeoutError(TimeoutError):
    """Raised when an Ollama call exceeds its total wall-clock budget."""


@contextmanager
def _wall_clock_timeout(seconds: int):
    """Bound total time for blocking Ollama calls in main-thread jobs."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _handle_timeout(signum, frame):
        raise LLMTimeoutError(f"Ollama request exceeded {seconds}s wall-clock timeout")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


# ──────────────────────────────────────────────
# JSON parsing (handles 14B model quirks)
# ──────────────────────────────────────────────

def parse_llm_json(raw: str) -> dict:
    """
    Parse JSON from LLM output, handling common 14B model issues:
    - Wrapped in markdown code blocks (```json ... ```)
    - Trailing commas before closing braces/brackets
    - Leading/trailing whitespace and newlines
    """
    text = raw.strip()

    # Strip markdown code blocks
    # Match ```json ... ``` or ``` ... ```
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON: {e}\nRaw output:\n{raw}")
        raise


# ──────────────────────────────────────────────
# Ollama API client
# ──────────────────────────────────────────────

def chat(system_prompt: str, user_prompt: str,
         model: str = DEFAULT_MODEL,
         temperature: float = DEFAULT_TEMPERATURE,
         timeout: int = DEFAULT_TIMEOUT,
         max_retries: int = MAX_RETRIES) -> str:
    """
    Send a chat completion request to Ollama.
    Returns the raw response text.
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "keep_alive": "5m",
        "options": {
            "temperature": temperature,
        },
        "format": "json",  # Force JSON mode
    }

    for attempt in range(1, max_retries + 1):
        try:
            with _wall_clock_timeout(timeout + WALL_CLOCK_GRACE):
                resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]
        except LLMTimeoutError as e:
            logger.warning("%s (attempt %s/%s)", e, attempt, max_retries)
            if attempt < max_retries:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Is it running?")
            if attempt < max_retries:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama request timed out (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise
        except Exception as e:
            logger.error(f"Ollama API error (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise

    raise RuntimeError("Ollama chat failed after all retries")


def chat_json(system_prompt: str, user_prompt: str,
              model: str = DEFAULT_MODEL,
              temperature: float = DEFAULT_TEMPERATURE,
              timeout: int = DEFAULT_TIMEOUT,
              max_retries: int = MAX_RETRIES) -> dict:
    """
    Send a chat request and parse the response as JSON.
    Handles markdown stripping and trailing commas.
    """
    raw = chat(system_prompt, user_prompt, model=model, temperature=temperature, timeout=timeout, max_retries=max_retries)
    return parse_llm_json(raw)


def _json_array(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []


def _format_known_papers(retrieved_papers: list[dict]) -> str:
    known_section = ""
    for i, paper in enumerate(retrieved_papers, 1):
        contribs_str = ", ".join(_json_array(paper.get("contributions"))) or "N/A"
        terms_str = ", ".join(_json_array(paper.get("key_terms"))) or "N/A"
        abstract = (paper.get("abstract") or "").replace("\n", " ")
        if len(abstract) > 700:
            abstract = abstract[:700].rsplit(" ", 1)[0] + "..."

        known_section += f"""[{i}] {paper['title']}
Similarity: {paper.get('similarity', 'N/A')}
Relevance: {paper.get('relevance_score', 'N/A')}/10
Domain: {paper.get('domain', 'N/A')}
Cluster: {paper.get('cluster_id', 'N/A')}
Contributions: {contribs_str}
Method: {paper.get('method', 'N/A')}
Terms: {terms_str}
Abstract excerpt: {abstract}
"""
    return known_section


# ──────────────────────────────────────────────
# Prompt Templates
# ──────────────────────────────────────────────

def prompt_relevance_scoring(title: str, abstract: str, profile: dict) -> dict:
    """
    Prompt 1: Relevance Scoring (Stage 2).
    Returns parsed JSON with relevance_score, rationale, matching_topics, paper_type.
    """
    system = """You are a strict research relevance scorer. Given a paper's title and
abstract, evaluate how relevant it is to the user's research interests.

RULES:
- If the paper matches ANY exclusion, score ≤ 3 regardless of topic overlap.
- matching_topics MUST only contain items from the user's topic list.
  If none match, return an empty array.
- Do NOT inflate scores. A 9 is very strong but not core. A 10 means the
  paper is a direct contribution to the user's exact research focus. Most
  papers score 4-6.

Respond ONLY with valid JSON. No other text."""

    topics_str = "\n".join(f"  - {t}" for t in profile.get("topics", []))
    methods_str = "\n".join(f"  - {m}" for m in profile.get("methods", []))
    exclusions_str = "\n".join(f"  - {e}" for e in profile.get("exclusions", []))

    user = f"""## My Research Interests
{profile['research_description']}

Topics:
{topics_str}

Methods:
{methods_str}

Exclusions:
{exclusions_str}

## Paper to Evaluate
Title: {title}
Abstract: {abstract}

## Task
Score this paper's relevance on a scale of 1-10.
Calibration: 5 = shares a subfield but not my focus. 8 = directly addresses
my research area. 9 = very strong fit, closely aligned with my exact focus,
but not a core contribution. 10 = core contribution to my exact focus (rare).
{_CONFIG.prompt_guidance("relevance_guidance")}

Respond with this exact JSON structure:
{{
  "relevance_score": <integer 1-10>,
  "rationale": "<1-2 sentences explaining the score>",
  "matching_topics": ["<exact topic string from my list>"],
  "paper_type": "<one of: empirical, theoretical, survey, system, benchmark, other>"
}}"""

    return chat_json(system, user, timeout=RELEVANCE_TIMEOUT, max_retries=1)


def prompt_compression(title: str, abstract: str, profile: dict) -> dict:
    """
    Prompt 2: Compression (LLM-ready summary).
    Returns parsed JSON with contributions, method, key_terms, domain.
    """
    system = """You are an academic paper compressor. Extract ONLY the essential
information from a paper's abstract into a structured format.
Be extremely concise. Every word must earn its place.
Favor skimmable fragments over paragraph prose.

RULES:
- Contributions = concrete results/artifacts, NOT background or motivation.
- Maximum 3 contributions. If fewer, use fewer.
- Each contribution should be one concise bullet-worthy sentence fragment.
- Method should be easy to scan: 1-2 compact sentences, no paragraph wall.
- key_terms MUST be chosen ONLY from the provided Allowed Tags list. Do not invent new tags.

Respond ONLY with valid JSON. No other text."""

    tags_str = "\n".join(f"  - {t}" for t in profile.get("tags", []))

    user = f"""## Paper
Title: {title}
Abstract: {abstract}

## Allowed Tags
{tags_str}

## Task
Compress this paper into a structured summary for future reference.
Focus on: what was built/found, how, and what's new.
{_CONFIG.prompt_guidance("compression_guidance")}

Respond with this exact JSON structure:
{{
  "contributions": [
    "<contribution 1: concrete result or artifact>",
    "<contribution 2>"
  ],
  "method": "<1-2 sentences: core technique or approach used>",
  "key_terms": ["<term1>", "<term2>", "<term3>"],
  "domain": "<specific subfield, e.g., 'GPU memory management' not 'systems'>"
}}"""

    return chat_json(system, user)


def prompt_rag_analysis(title: str, abstract: str,
                        retrieved_papers: list[dict],
                        profile: dict) -> dict:
    """
    Prompt 3: RAG Deep Analysis.
    
    Args:
        title: new paper title
        abstract: new paper abstract
        retrieved_papers: list of dicts with keys: title, contributions, method, key_terms
        profile: research profile dict
    
    Returns parsed JSON with summary, key_contributions, is_novel, etc.
    """
    system = """You are a research analyst. Compare a new paper against a set of known
papers from the user's working set. Identify what is genuinely new,
what overlaps with known work, and whether this paper matters.
Prefer dense, skimmable Markdown bullets over paragraph prose for reader-facing fields.

GROUNDING RULES:
- You may ONLY reference papers listed under "Known Papers" below.
- extends/overlaps arrays MUST use exact titles from that list, or be empty.
- If you cannot determine novelty from the given information,
  set is_novel to true and explanation to "insufficient context for comparison".
- Do NOT invent relationships or cite papers not in the provided list.

RECOMMENDATION RULES:
- Default to "track" for relevant papers. Choose "read" only when the paper is
  urgent enough to enter a scarce Review queue.
- "read" requires strong evidence from the title/abstract/context that it is
  directly actionable for the user's current research, changes how they should
  think about a core system/design problem, or contains a method/result they
  should inspect soon.
- "track" means relevant enough to keep indexed and visible, but mostly
  background, adjacent, survey-like, incremental, or not urgent.
- "ignore" means not useful for the user's stated research after analysis.
- Do not choose "read" merely because the paper is generally relevant, novel,
  high-scoring, or matches one broad topic. If the rationale is only "relevant
  to your interests", choose "track".
- Use "ignore" for papers whose relevance is only via generic AI/ML/HPC terms
  without a concrete systems, architecture, memory, networking, or distributed
  runtime connection.

Respond ONLY with valid JSON. No other text."""

    known_section = _format_known_papers(retrieved_papers)

    user = f"""## My Research Interests
{profile['research_description']}

## New Paper
Title: {title}
Abstract: {abstract}

## Known Papers from My Working Set
{known_section}

## Task
Analyze this new paper in the context of my known work. Use the similarity,
domain, contribution, method, and abstract-excerpt evidence to decide
relationships. Prefer "overlaps_with" for shared problem/method/evaluation,
and "extends" only when the new work clearly builds on an idea, interface,
system design, or result from a known paper.
{_CONFIG.prompt_guidance("analysis_guidance")}

Respond with this exact JSON structure:
{{
  "summary": "<Markdown bullets, 2-4 bullets max. Use labels like '- Problem:', '- Approach:', '- Result:', '- Why it matters:'. Keep each bullet one compact sentence.>",
  "key_contributions": ["<concise contribution 1>", "<concise contribution 2>"],
  "is_novel": <true/false>,
  "novelty_explanation": "<Markdown bullets, 1-3 bullets. MUST cite known papers by exact title if claiming overlap or extension>",
  "extends": ["<exact title from Known Papers list, or empty>"],
  "overlaps_with": ["<exact title from Known Papers list, or empty>"],
  "relation_to_my_research": "<Markdown bullets, 1-3 bullets: why this matters to my specific work>",
  "recommendation": "<one of: read, track, ignore>",
  "recommendation_reason": "<1 sentence>",
  "confidence": "<one of: high, medium, low>"
}}"""

    return chat_json(system, user)


def prompt_relationship_update(title: str, abstract: str,
                               retrieved_papers: list[dict],
                               profile: dict,
                               existing_analysis: dict | None = None) -> dict:
    """Refresh paper-to-paper relationships for an existing analyzed paper."""
    system = """You are refreshing a research graph. Given one paper, its current
analysis, and nearby working-set papers, identify grounded relationships.

RULES:
- You may ONLY reference papers listed under "Known Papers" below.
- extends/overlaps_with MUST use exact titles from Known Papers, or be empty.
- Use "extends" only for clear building-on relationships.
- Use "overlaps_with" for similar problem, method, system component, or evaluation.
- Do not preserve old links unless the provided evidence still supports them.

Respond ONLY with valid JSON. No other text."""

    known_section = _format_known_papers(retrieved_papers)
    old_extends = ", ".join(_json_array((existing_analysis or {}).get("extends"))) or "None"
    old_overlaps = ", ".join(_json_array((existing_analysis or {}).get("overlaps_with"))) or "None"

    user = f"""## My Research Interests
{profile['research_description']}

## Paper To Refresh
Title: {title}
Abstract: {abstract}

## Current Analysis
Summary: {(existing_analysis or {}).get('summary', 'N/A')}
Novelty: {(existing_analysis or {}).get('novelty_explanation', 'N/A')}
Previous extends: {old_extends}
Previous overlaps_with: {old_overlaps}

## Known Papers
{known_section}

## Task
Refresh only the relationship fields and briefly explain the relationship evidence.
{_CONFIG.prompt_guidance("relationship_guidance")}

Respond with this exact JSON structure:
{{
  "extends": ["<exact title from Known Papers list, or empty>"],
  "overlaps_with": ["<exact title from Known Papers list, or empty>"],
  "relationship_rationale": "<1-3 sentences citing exact known-paper titles when links are present>",
  "confidence": "<one of: high, medium, low>"
}}"""

    return chat_json(system, user)


def prompt_verification(analysis: dict, abstract: str,
                        retrieved_papers: list[dict]) -> dict:
    """
    Prompt 4: Selective Verification.
    Runs selectively for Review recommendations and other high-score papers.
    
    Args:
        analysis: the Prompt 3 output dict
        abstract: original paper abstract
        retrieved_papers: same papers used in Prompt 3
    
    Returns parsed JSON with verified, issues, corrected_recommendation.
    """
    system = """You are a fact-checker. You are given specific claims from a paper
analysis and the source material they were based on. Check whether
each claim is supported.

RULES:
- Do NOT re-analyze the paper or generate new insights.
- Only check the claims provided against the provided context.
- If a claim references a paper not in the Known Papers list, flag it.
- Only include unsupported/overstated/misattributed/fabricated claims in issues.
- Do not include supported claims in issues.

Respond ONLY with valid JSON. No other text."""

    # Build claims section
    extends = analysis.get("extends", [])
    if isinstance(extends, str):
        extends = json.loads(extends) if extends else []
    overlaps = analysis.get("overlaps_with", [])
    if isinstance(overlaps, str):
        overlaps = json.loads(overlaps) if overlaps else []

    extends_str = ", ".join(extends) if extends else "None"
    overlaps_str = ", ".join(overlaps) if overlaps else "None"

    # Build known papers context
    known_section = ""
    for i, paper in enumerate(retrieved_papers, 1):
        contribs = paper.get("contributions", "[]")
        if isinstance(contribs, str):
            contribs = json.loads(contribs)
        contribs_str = ", ".join(contribs) if contribs else "N/A"

        known_section += f"""[{i}] {paper['title']}
Contributions: {contribs_str}
Method: {paper.get('method', 'N/A')}
"""

    user = f"""## Claims to Verify
Novelty explanation: {analysis.get('novelty_explanation', 'N/A')}
Extends: {extends_str}
Overlaps with: {overlaps_str}
Relation to my research: {analysis.get('relation_to_research', 'N/A')}
Recommendation: {analysis.get('recommendation', 'N/A')} — {analysis.get('recommendation_reason', 'N/A')}

## Source Material
New paper abstract: {abstract}

Known papers used as context:
{known_section}

## Task
Verify each claim above against the source material.
{_CONFIG.prompt_guidance("verification_guidance")}

Respond with this exact JSON structure:
{{
  "verified": <true if all claims are supported, false otherwise>,
  "issues": [
    {{
      "claim": "<the specific claim>",
      "problem": "<one of: unsupported, overstated, misattributed, fabricated>",
      "detail": "<1 sentence explanation>"
    }}
  ],
  "corrected_recommendation": "<read/track/ignore only if issues warrant a change; otherwise empty string>"
}}"""

    return chat_json(system, user)


def prompt_pruning(title: str, summary: dict, relevance_score: int,
                   added_at: str, profile: dict) -> dict:
    """
    Prompt 5: Pruning Suggestion.
    Only runs after the configured working-set size threshold, max once per day.
    
    Args:
        title: paper title
        summary: compressed summary dict (contributions, method, key_terms)
        relevance_score: original relevance score
        added_at: ISO 8601 date when paper was added
        profile: research profile dict
    
    Returns parsed JSON with prune_recommendation, reason, risk_if_removed.
    """
    system = """You are helping a researcher decide whether to remove a paper from
their working set. Explain briefly why this paper may no longer be
relevant. Be honest — if the paper might still be useful, say so.

Respond ONLY with valid JSON. No other text."""

    topics_str = "\n".join(f"  - {t}" for t in profile.get("topics", []))

    contribs = summary.get("contributions", [])
    if isinstance(contribs, str):
        contribs = json.loads(contribs)
    contribs_str = "\n".join(f"  - {c}" for c in contribs)

    terms = summary.get("key_terms", [])
    if isinstance(terms, str):
        terms = json.loads(terms)
    terms_str = ", ".join(terms)

    user = f"""## My Current Research Interests
{profile['research_description']}
Topics:
{topics_str}

## Paper Under Review
Title: {title}
Compressed Summary:
- Contributions:
{contribs_str}
- Method: {summary.get('method', 'N/A')}
- Key terms: {terms_str}

Original Relevance Score: {relevance_score}
Date Added: {added_at}

## Task
Should this paper be removed from the working set?
{_CONFIG.prompt_guidance("pruning_guidance")}

Respond with this exact JSON structure:
{{
  "prune_recommendation": "<one of: remove, keep, unsure>",
  "reason": "<2-3 sentences explaining why>",
  "risk_if_removed": "<1 sentence: what context would be lost>"
}}"""

    return chat_json(system, user)
