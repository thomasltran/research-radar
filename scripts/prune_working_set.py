#!/usr/bin/env python3
"""Review and apply working-set prune suggestions."""

import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src import db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("prune-review")


def _snippet(text: str, limit: int = 240) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _format_preview(preview: dict) -> list[str]:
    lines = []
    if not preview:
        return lines
    if preview.get("abstract"):
        lines.append(f"  abstract: {_snippet(preview['abstract'])}")
    if preview.get("summary"):
        lines.append(f"  summary: {_snippet(preview['summary'])}")
    if preview.get("method"):
        lines.append(f"  method: {_snippet(preview['method'])}")
    if preview.get("key_terms"):
        lines.append(f"  key_terms: {', '.join(preview['key_terms'])}")
    if preview.get("contributions"):
        lines.append(f"  contributions: {', '.join(preview['contributions'])}")
    if preview.get("note_path"):
        lines.append(f"  note: {preview['note_path']}")
    if preview.get("source") or preview.get("published_date"):
        lines.append(
            f"  source/date: {preview.get('source', 'N/A')} / {preview.get('published_date', 'N/A')}"
        )
    if preview.get("relevance_score") is not None or preview.get("similarity") is not None:
        lines.append(
            f"  score/similarity: {preview.get('relevance_score', 'N/A')} / {preview.get('similarity', 'N/A')}"
        )
    if preview.get("cluster_id") is not None:
        lines.append(f"  cluster: {preview['cluster_id']}")
    return lines


def list_actions(status: str, limit: int) -> None:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        actions = db.list_prune_actions(conn, status=status, limit=limit)
    finally:
        conn.close()
    if not actions:
        print(f"No prune actions with status={status!r}.")
        return

    for action in actions:
        print(f"[{action['id']}] {action['title']}")
        print(f"  status: {action['status']} | recommendation: {action['recommendation']}")
        if action.get("reason"):
            print(f"  reason: {_snippet(action['reason'])}")
        if action.get("risk_if_removed"):
            print(f"  risk: {_snippet(action['risk_if_removed'])}")
        for line in _format_preview(action.get("preview") or {}):
            print(line)
        print("")


def apply_action(action_id: int) -> None:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        action = db.get_prune_action(conn, action_id)
        if not action:
            raise SystemExit(f"Prune action {action_id} not found.")

        db.mark_working_set(conn, action["paper_id"], False)
        db.update_prune_action_status(conn, action_id, "applied")
        embeddings = db.load_embeddings()
        db.rebuild_working_set_index(conn, embeddings)
    finally:
        conn.close()
    print(f"Applied prune action {action_id}: removed {action['title']} from the working set.")


def keep_action(action_id: int) -> None:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        action = db.get_prune_action(conn, action_id)
        if not action:
            raise SystemExit(f"Prune action {action_id} not found.")

        db.update_prune_action_status(conn, action_id, "kept")
    finally:
        conn.close()
    print(f"Kept prune action {action_id}: {action['title']}.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review and apply working-set prune suggestions.")
    parser.add_argument("command", nargs="?", choices=["list", "apply", "keep"], default="list")
    parser.add_argument("--status", default="pending", help="Prune status to filter by.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of rows to show.")
    parser.add_argument("--id", type=int, help="Prune action ID.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "apply":
        if args.id is None:
            raise SystemExit("--id is required for apply.")
        apply_action(args.id)
    elif args.command == "keep":
        if args.id is None:
            raise SystemExit("--id is required for keep.")
        keep_action(args.id)
    else:
        list_actions(args.status, args.limit)


if __name__ == "__main__":
    main()
