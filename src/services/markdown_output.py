"""
markdown_output.py - Pure Markdown formatting for digests and paper notes.

This module keeps presentation assembly separate from filesystem/database
orchestration in src.output.
"""

from __future__ import annotations

import re

from src.services.json_utils import json_load_safe


def sanitize_filename(title: str) -> str:
    """Convert a paper title to a safe filename."""
    name = re.sub(r'[^\w\s-]', '', title.lower())
    name = re.sub(r'[\s]+', '_', name.strip())
    return name[:80]


def paper_wikilink(title: str) -> str:
    """Return a wiki-link for compatible Markdown apps."""
    return f"[[{sanitize_filename(title)}|{title}]]"


def snippet(text: str, limit: int = 420) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def top_tags(tags: list[str], limit: int = 3) -> list[str]:
    seen = set()
    picked = []
    for tag in tags or []:
        clean = re.sub(r'[^a-z0-9\-]', '', str(tag).replace(' ', '-').replace('_', '-').lower())
        if not clean or clean in seen:
            continue
        seen.add(clean)
        picked.append(clean)
        if len(picked) >= limit:
            break
    return picked


def markdown_text(value, default: str = "N/A") -> str:
    """Coerce loose LLM output into markdown-safe text."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return str(value)


def append_analysis_block(lines: list[str], analysis: dict) -> None:
    lines.append("### Summary")
    lines.append(markdown_text(analysis.get("summary")) + "\n")

    lines.append("### Key Contributions")
    for contribution in json_load_safe(analysis.get("key_contributions")):
        lines.append(f"- {contribution}")
    lines.append("")

    lines.append("### Novelty")
    lines.append(markdown_text(analysis.get("novelty_explanation")))
    extends = json_load_safe(analysis.get("extends"))
    overlaps = json_load_safe(analysis.get("overlaps_with"))
    if extends:
        lines.append(f"- **Extends**: {', '.join(paper_wikilink(title) for title in extends)}")
    if overlaps:
        lines.append(f"- **Overlaps with**: {', '.join(paper_wikilink(title) for title in overlaps)}")
    lines.append("")

    lines.append("### Relation to My Research")
    lines.append(markdown_text(analysis.get("relation_to_research")) + "\n")


def append_prune_suggestion(lines: list[str], prune_result: dict) -> None:
    lines.append("\n## 🧹 Prune Suggestion\n")
    lines.append(f"**Paper**: {prune_result.get('title', 'Unknown')}")
    lines.append(f"**Recommendation**: {prune_result.get('prune_recommendation', 'unsure')}")
    lines.append(f"**Reason**: {prune_result.get('reason', 'N/A')}")
    lines.append(f"**Risk if removed**: {prune_result.get('risk_if_removed', 'N/A')}\n")
    preview = prune_result.get("preview") or {}
    if preview:
        lines.append("### Quick Preview")
        if preview.get("abstract"):
            lines.append(snippet(preview["abstract"]))
        if preview.get("summary"):
            lines.append(f"- **Summary**: {snippet(preview['summary'])}")
        if preview.get("method"):
            lines.append(f"- **Method**: {snippet(preview['method'])}")
        if preview.get("key_terms"):
            lines.append(f"- **Key Terms**: {', '.join(preview['key_terms'])}")
        if preview.get("note_path"):
            lines.append(f"- **Note**: `{preview['note_path']}`")
        lines.append("")
    lines.append("- [ ] Keep")
    lines.append("- [ ] Remove")


def build_paper_note_lines(
    *,
    analysis: dict,
    paper: dict,
    title: str,
    authors: str,
    tags: str,
    score,
    recommendation: str,
    summary: dict | None,
    is_read: str,
    existing_notes: str,
) -> list[str]:
    lines = [
        "---",
        f"tags: [{tags}]",
        f"read: {is_read}",
        f"relevance: {score}",
        f"recommendation: {recommendation}",
        f"source: {paper.get('source', '')}",
        f"published: {paper.get('published_date', '')}",
        f"added: {paper.get('ingested_at', '')}",
        f"working_set: {'true' if paper.get('in_working_set') else 'false'}",
        f"cluster: {paper.get('cluster_id', '')}",
        "---\n",
        f"# {title}\n",
        f"**Authors**: {authors}",
        f"**Link**: {paper.get('url', '')}",
        f"**DOI**: {paper.get('doi', 'N/A')}\n",
        "## Summary",
        markdown_text(analysis.get("summary")) + "\n",
        "## Key Contributions",
    ]

    for contribution in json_load_safe(analysis.get("key_contributions")):
        lines.append(f"- {contribution}")
    lines.append("")

    if summary:
        lines.append("## Method")
        lines.append(summary.get("method", "N/A") + "\n")

    lines.append("## Novelty Assessment")
    lines.append(markdown_text(analysis.get("novelty_explanation")) + "\n")

    extends = json_load_safe(analysis.get("extends"))
    overlaps = json_load_safe(analysis.get("overlaps_with"))
    if extends or overlaps:
        lines.append("## Related Papers")
        for title in extends:
            lines.append(f"- **Extends**: {paper_wikilink(title)}")
        for title in overlaps:
            lines.append(f"- **Overlaps**: {paper_wikilink(title)}")
        lines.append("")

    lines.append("## Relation to My Research")
    lines.append(markdown_text(analysis.get("relation_to_research")) + "\n")

    lines.append("## Recommendation")
    lines.append(f"**{recommendation}**: {markdown_text(analysis.get('recommendation_reason'), '')}")

    lines.append("\n## My Notes")
    if existing_notes:
        lines.append(existing_notes)
    return lines
