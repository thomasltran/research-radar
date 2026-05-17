"""
output.py — Markdown output generation for daily digests and paper notes.

Generates:
  - output/digests/YYYY-MM-DD.md — daily summary of all analyzed papers
  - output/papers/{sanitized_title}.md — individual Markdown paper notes
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from src import db
from src.profile import canonicalize_tags, load_research_profile
from src.services.json_utils import json_load_safe
from src.services.markdown_output import (
    append_analysis_block,
    append_prune_suggestion,
    build_paper_note_lines,
    paper_wikilink as format_paper_wikilink,
    sanitize_filename as format_sanitize_filename,
    top_tags,
)

load_dotenv()

logger = logging.getLogger(__name__)

output_path = os.getenv("OUTPUT_DIR")
if output_path:
    OUTPUT_DIR = Path(output_path)
else:
    OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def sanitize_filename(title: str) -> str:
    """Convert a paper title to a safe filename."""
    return format_sanitize_filename(title)


def paper_note_path(title: str) -> Path:
    """Return the local Markdown note path for a paper title."""
    return OUTPUT_DIR / "papers" / f"{sanitize_filename(title)}.md"


def paper_wikilink(title: str) -> str:
    """Return a wiki-link for compatible Markdown apps."""
    return format_paper_wikilink(title)


def generate_daily_digest(conn, analyses: list[dict], papers_by_id: dict,
                          run_stats: dict, prune_result: dict = None,
                          run_type: str = "manual") -> None:
    """Generate the daily digest markdown file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_dir = OUTPUT_DIR / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    filepath = digest_dir / f"{today}.md"

    # Sort by relevance score descending
    sorted_analyses = sorted(analyses, key=lambda a: (papers_by_id.get(a["paper_id"], {}).get("relevance_score") or 0), reverse=True)

    lines = [
        f"# Research Digest — {today}\n",
        f"> Run: {run_type} | Fetched: {run_stats.get('papers_fetched',0)} | "
        f"Relevant: {run_stats.get('papers_passed_s2',0)} | "
        f"Analyzed: {run_stats.get('papers_analyzed',0)}\n",
        "---\n",
    ]

    for a in sorted_analyses:
        rec = (a.get("recommendation") or "track").lower()
        if rec == "ignore":
            continue

        pid = a["paper_id"]
        paper = papers_by_id.get(pid, {})
        score = paper.get("relevance_score", "?")
        title = a.get("title", paper.get("title", "Unknown"))
        authors_raw = paper.get("authors", "[]")
        authors = ", ".join(json_load_safe(authors_raw, []))

        lines.append(f"\n## [{score}/10] {title}\n")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Published**: {paper.get('published_date', 'N/A')} | **Source**: {paper.get('source', 'N/A')}")
        lines.append(f"**Type**: {paper.get('paper_type', 'N/A')} | **Confidence**: {a.get('confidence', 'N/A')}")
        lines.append(f"**Link**: {paper.get('url', 'N/A')}\n")

        append_analysis_block(lines, a)

        # Verification issues
        verification = None
        try:
            row = conn.execute("SELECT * FROM verifications WHERE paper_id=?", (pid,)).fetchone()
            if row:
                verification = dict(row)
        except Exception:
            pass
        if verification and not verification.get("verified"):
            issues = json_load_safe(verification.get("issues"))
            if issues:
                lines.append("### ⚠️ Verification Issues")
                for issue in issues:
                    lines.append(f"- **{issue.get('problem','?')}**: {issue.get('claim','')} — {issue.get('detail','')}")
                lines.append("")

        rec = a.get("recommendation") or "track"
        reason = a.get("recommendation_reason", "")
        lines.append(f"### Recommendation: **{rec}**")
        lines.append(reason + "\n")
        lines.append("---\n")

    # Prune suggestion
    if prune_result:
        append_prune_suggestion(lines, prune_result)

    filepath.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Daily digest written: {filepath}")


def generate_paper_notes(conn, analyses: list[dict], papers_by_id: dict) -> None:
    """Generate individual Markdown paper notes."""
    papers_dir = OUTPUT_DIR / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for a in analyses:
        rec = (a.get("recommendation") or "track").lower()
        if rec == "ignore":
            continue
        
        written += 1
        
        pid = a["paper_id"]
        paper = papers_by_id.get(pid, {})
        title = a.get("title", paper.get("title", "Unknown"))
        summary = db.get_compressed_summary(conn, pid)

        # YAML frontmatter
        key_terms = json_load_safe(summary.get("key_terms") if summary else None)
        clean_terms = canonicalize_tags(top_tags(key_terms, limit=3), load_research_profile().get("tags", []))
        tags = ", ".join(clean_terms) if clean_terms else ""
        score = paper.get("relevance_score", "")


        authors_raw = paper.get("authors", "[]")
        authors = ", ".join(json_load_safe(authors_raw, []))

        filepath = paper_note_path(title)

        is_read = "false"
        existing_notes = ""
        if filepath.exists():
            try:
                content = filepath.read_text(encoding="utf-8")
                notes_match = re.search(r"^## My Notes\s*\n(.*)", content, re.MULTILINE | re.DOTALL)
                if notes_match:
                    existing_notes = notes_match.group(1).strip()
            except Exception:
                pass
        try:
            is_read = "true" if db.get_paper_read_state(conn, pid) else "false"
        except Exception:
            # Older databases can still regenerate notes before migrations run.
            pass

        lines = build_paper_note_lines(
            analysis=a,
            paper=paper,
            title=title,
            authors=authors,
            tags=tags,
            score=score,
            recommendation=rec,
            summary=summary,
            is_read=is_read,
            existing_notes=existing_notes,
        )

        filepath.write_text("\n".join(lines), encoding="utf-8")

    logger.info(f"Paper notes written: {written} files")
