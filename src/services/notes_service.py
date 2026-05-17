"""
notes_service.py - Markdown note file I/O for individual papers.

Extracted verbatim from web_server.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from src import db
from src.output import paper_note_path


def note_path_for_paper(paper: dict) -> Path:
    return paper_note_path(paper["title"])


def _default_note(paper: dict, read: bool = False) -> str:
    return "\n".join([
        "---",
        f"read: {'true' if read else 'false'}",
        f"source: {paper.get('source', '')}",
        f"published: {paper.get('published_date', '')}",
        f"working_set: {'true' if paper.get('in_working_set') else 'false'}",
        "---",
        "",
        f"# {paper['title']}",
        "",
        "## My Notes",
        "",
    ])


def ensure_note_file(conn, paper_id: str) -> Path:
    paper = db.get_paper(conn, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    path = note_path_for_paper(paper)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_default_note(paper, db.get_paper_read_state(conn, paper_id)), encoding="utf-8")
    return path


def extract_notes(content: str) -> str:
    match = re.search(r"^## My Notes\s*\n(?P<notes>.*?)(?=^##\s|\Z)", content, re.MULTILINE | re.DOTALL)
    return match.group("notes").strip() if match else ""


def replace_notes(content: str, notes: str) -> str:
    body = notes.rstrip()
    replacement = f"## My Notes\n{body}\n" if body else "## My Notes\n"
    if re.search(r"^## My Notes\s*\n", content, re.MULTILINE):
        return re.sub(
            r"^## My Notes\s*\n.*?(?=^##\s|\Z)",
            replacement,
            content,
            flags=re.MULTILINE | re.DOTALL,
        ).rstrip() + "\n"
    return content.rstrip() + "\n\n" + replacement


def sync_note_read_state(conn, paper_id: str, read: bool) -> None:
    path = ensure_note_file(conn, paper_id)
    content = path.read_text(encoding="utf-8")
    read_line = f"read: {'true' if read else 'false'}"

    if re.match(r"^---\s*\n", content):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2]
            if re.search(r"^read:\s*(true|false)\s*$", frontmatter, re.MULTILINE | re.IGNORECASE):
                frontmatter = re.sub(
                    r"^read:\s*(true|false)\s*$",
                    read_line,
                    frontmatter,
                    flags=re.MULTILINE | re.IGNORECASE,
                )
            else:
                frontmatter = frontmatter.rstrip() + f"\n{read_line}\n"
            path.write_text(f"---{frontmatter}---{body}", encoding="utf-8")
            return

    path.write_text(f"---\n{read_line}\n---\n\n{content}", encoding="utf-8")
