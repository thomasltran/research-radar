"""
main.py — Pipeline orchestration.

Ties together: ingest → dedup → embed → filter → RAG → analyze → verify → output → prune
"""

import argparse
import json
import logging
import os
import signal
from datetime import datetime, timezone

import numpy as np

from src import db, embed, ingest, llm, rag
from src.config import load_config
from src.output import paper_note_path
from src.pipeline_policy import (
    INGEST_RETRIEVAL_K,
    STAGE1_COSINE_CUTOFF,
    STAGE2_RELEVANCE_CUTOFF,
    WORKING_SET_ENTRY_THRESHOLD,
)
from src.profile import canonicalize_tags, load_research_profile
from src.services.analysis_normalization import build_analysis_record
from src.services.analysis_verification import persist_verification
from src.services.recommendation_policy import apply_review_policy, should_verify_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline")
_CONFIG = load_config()


def _mark_ingestion_success(conn, until: str) -> None:
    """Advance source cursors after a successful fetch attempt, even if no new papers passed dedup."""
    for source in _enabled_sources():
        db.update_ingestion_state(conn, source, until)


def _record_stage_error(conn, run_id: int, stats: dict, message: str) -> None:
    stats["error_count"] += 1
    logger.error(message)
    db.update_pipeline_run(conn, run_id, error_count=stats["error_count"])


def _enabled_sources() -> list[str]:
    source_mode = os.getenv("FETCH_SOURCE", _CONFIG.str("pipeline.default_fetch_source", "both")).lower()
    if source_mode == "arxiv":
        return ["arxiv"]
    if source_mode in ("s2", "semantic_scholar"):
        return ["semantic_scholar"]
    return ["arxiv", "semantic_scholar"]


def _incremental_since(conn) -> str | None:
    last_runs = [
        ts for ts in (db.get_last_successful_run(conn, source) for source in _enabled_sources())
        if ts
    ]
    return min(last_runs) if last_runs else None


def load_profile() -> dict:
    return load_research_profile()


def _build_prune_preview(conn, candidate: dict, summary: dict, prune_result: dict) -> dict:
    paper = db.get_paper(conn, candidate["id"]) or candidate
    contributions = summary.get("contributions", [])
    if isinstance(contributions, str):
        try:
            contributions = json.loads(contributions)
        except json.JSONDecodeError:
            contributions = []

    key_terms = summary.get("key_terms", [])
    if isinstance(key_terms, str):
        try:
            key_terms = json.loads(key_terms)
        except json.JSONDecodeError:
            key_terms = []

    preview = {
        "abstract": paper.get("abstract", ""),
        "summary": " ".join(contributions) if contributions else paper.get("abstract", "")[:500],
        "method": summary.get("method", ""),
        "key_terms": key_terms,
        "contributions": contributions,
        "source": paper.get("source", ""),
        "published_date": paper.get("published_date", ""),
        "relevance_score": paper.get("relevance_score", candidate.get("relevance_score")),
        "similarity": candidate.get("similarity"),
        "cluster_id": paper.get("cluster_id"),
        "note_path": str(paper_note_path(paper.get("title", candidate.get("title", "paper")))),
    }
    return preview


def run_pipeline(run_type: str = "scheduled", run_id: int | None = None):
    """Execute the full daily pipeline."""
    logger.info(f"{'='*60}\nStarting pipeline run ({run_type})\n{'='*60}")
    profile = load_profile()
    conn = db.get_connection()
    db.init_schema(conn)
    if run_id is None:
        run_id = db.create_pipeline_run(conn, run_type)
    else:
        db.update_pipeline_run(conn, run_id, status="running", run_type=run_type)

    def _mark_cancelled(signum, frame):
        raise KeyboardInterrupt(f"Pipeline cancelled by signal {signum}")

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _mark_cancelled)
    signal.signal(signal.SIGTERM, _mark_cancelled)

    index_all = db.load_index("index_all")
    index_ws = db.load_index("index_ws")
    ws_id_map = db.load_ws_id_map()

    # Load persisted embeddings from previous runs (critical for clustering/interest vector)
    all_embeddings = db.load_embeddings()

    stats = dict(papers_fetched=0, papers_passed_s1=0, papers_passed_s2=0,
                 papers_analyzed=0, papers_verified=0, papers_added_ws=0, error_count=0)

    try:
        # ── Ingest ──
        since = os.getenv("PIPELINE_SCAN_START") or _incremental_since(conn)
        until = os.getenv("PIPELINE_SCAN_END") or datetime.now(timezone.utc).isoformat()
        logger.info(f"Enabled sources: {', '.join(_enabled_sources())}")
        logger.info(f"Scan window: {since or 'beginning'} -> {until}")
        fetched = ingest.fetch_all_papers(profile, since=since, until=until)
        stats["papers_fetched"] = len(fetched)
        db.update_pipeline_run(conn, run_id, papers_fetched=stats["papers_fetched"])
        if not fetched:
            logger.info("No papers fetched.")
            _mark_ingestion_success(conn, until)
            db.complete_pipeline_run(conn, run_id, "success", **stats)
            return

        # ── Dedup ──
        new_papers = []
        for p in fetched:
            if not ingest.is_duplicate_in_db(conn, p):
                p["run_id"] = run_id
                if db.insert_paper(conn, p):
                    new_papers.append(p)
        logger.info(f"Dedup: {len(new_papers)} new from {len(fetched)}")
        if not new_papers:
            _mark_ingestion_success(conn, until)
            db.complete_pipeline_run(conn, run_id, "success", **stats)
            return

        # ── Embed all new papers ──
        abstracts = [f"Represent this scientific abstract for retrieval: {p['abstract']}" for p in new_papers]
        vecs = embed.embed_texts(abstracts)
        paper_emb = {p["id"]: v for p, v in zip(new_papers, vecs)}

        # Add ALL new papers to index_all (spec: "every ingested paper, whether relevant or not")
        for p in new_papers:
            pid = p["id"]
            if pid in paper_emb:
                fpos = db.add_to_index(index_all, paper_emb[pid])
                db.update_paper_faiss_id(conn, pid, fpos)

        # Merge new embeddings into the persistent store
        all_embeddings.update(paper_emb)

        # ── Stage 1: embedding similarity filter ──
        iv = embed.load_interest_vector()
        if iv is not None:
            s1 = [p for p in new_papers if p["id"] in paper_emb
                  and embed.cosine_similarity(iv, paper_emb[p["id"]]) >= STAGE1_COSINE_CUTOFF]
        else:
            s1 = new_papers
        stats["papers_passed_s1"] = len(s1)
        db.update_pipeline_run(conn, run_id, papers_passed_s1=stats["papers_passed_s1"])
        logger.info(f"Stage 1: {len(s1)}/{len(new_papers)} passed")

        # ── Stage 2: LLM relevance scoring ──
        s2 = []
        total_s1 = len(s1)
        for i, p in enumerate(s1, 1):
            try:
                res = llm.prompt_relevance_scoring(p["title"], p["abstract"], profile)
                score = int(res.get("relevance_score", 0))
                conn.execute("UPDATE papers SET relevance_score=?, paper_type=?, matching_topics=? WHERE id=?",
                             (score, res.get("paper_type", "other"), json.dumps(res.get("matching_topics", [])), p["id"]))
                conn.commit()
                p["relevance_score"] = score
                if score >= STAGE2_RELEVANCE_CUTOFF:
                    s2.append(p)
                    logger.info(f"  [{i}/{total_s1}] S2 PASS ({score}): {p['title'][:60]}")
                else:
                    logger.info(f"  [{i}/{total_s1}] S2 FAIL ({score}): {p['title'][:60]}")
            except Exception as e:
                _record_stage_error(conn, run_id, stats, f"  [{i}/{total_s1}] S2 error: {e}")
        stats["papers_passed_s2"] = len(s2)
        db.update_pipeline_run(conn, run_id, papers_passed_s2=stats["papers_passed_s2"])

        # ── Compress + Working Set + FAISS WS index ──
        ws_added = 0
        total_s2 = len(s2)
        for i, p in enumerate(s2, 1):
            pid = p["id"]
            score = p.get("relevance_score", 0) or 0
            try:
                comp = llm.prompt_compression(p["title"], p["abstract"], profile)
                key_terms = canonicalize_tags(comp.get("key_terms", []), profile.get("tags", []))
                db.insert_compressed_summary(conn, {
                    "paper_id": pid,
                    "contributions": json.dumps(comp.get("contributions", [])),
                    "method": comp.get("method", ""),
                    "key_terms": json.dumps(key_terms),
                    "domain": comp.get("domain", ""),
                })
                logger.info(f"  [{i}/{total_s2}] Compressed: {p['title'][:50]}")

                if score >= WORKING_SET_ENTRY_THRESHOLD:
                    db.mark_working_set(conn, pid, True)
                    if pid in paper_emb:
                        ws_pos = db.add_to_index(index_ws, paper_emb[pid])
                        ws_id_map[ws_pos] = pid
                    ws_added += 1
            except Exception as e:
                _record_stage_error(conn, run_id, stats, f"  [{i}/{total_s2}] Compress error: {e}")
        stats["papers_added_ws"] = ws_added
        db.update_pipeline_run(conn, run_id, papers_added_ws=stats["papers_added_ws"])

        # Refresh the working-set index and clusters before relationship analysis
        # so RAG can compare against the current corpus, including this run's additions.
        index_ws, ws_id_map = db.rebuild_working_set_index(conn, all_embeddings)
        ws_papers = db.get_working_set_papers(conn)
        ws_embs = {p["id"]: all_embeddings[p["id"]] for p in ws_papers if p["id"] in all_embeddings}
        if len(ws_embs) >= rag.CLUSTER_MINIMUM:
            rag.cluster_working_set(conn, ws_embs)

        # ── RAG deep analysis ──
        analyses = []
        for i, p in enumerate(s2, 1):
            pid = p["id"]
            if pid in paper_emb:
                retrieved = rag.retrieve_context(conn, paper_emb[pid], index_ws, ws_id_map, INGEST_RETRIEVAL_K, exclude_id=pid)
            else:
                retrieved = []
            try:
                a = llm.prompt_rag_analysis(p["title"], p["abstract"], retrieved, profile)
                rec = apply_review_policy(build_analysis_record(pid, a, [r["id"] for r in retrieved]), p)
                db.insert_analysis(conn, rec)
                analyses.append({**rec, "title": p["title"], "paper": p})
                logger.info(f"  [{i}/{total_s2}] Analyzed: {a.get('recommendation', '?').upper()} - {p['title'][:50]}")
            except Exception as e:
                _record_stage_error(conn, run_id, stats, f"  [{i}/{total_s2}] Analysis error: {e}")
        stats["papers_analyzed"] = len(analyses)
        db.update_pipeline_run(conn, run_id, papers_analyzed=stats["papers_analyzed"])

        # ── Selective verification for high-relevance papers ──
        verified = 0
        papers_by_id = {p["id"]: p for p in s2}
        total_analyses = len(analyses)
        for i, a in enumerate(analyses, 1):
            pid = a["paper_id"]
            p = papers_by_id.get(pid)
            if not p or not should_verify_analysis(a, p):
                continue
            if pid in paper_emb:
                retrieved = rag.retrieve_context(conn, paper_emb[pid], index_ws, ws_id_map, INGEST_RETRIEVAL_K, exclude_id=pid)
            else:
                retrieved = []
            try:
                v = llm.prompt_verification(a, p["abstract"], retrieved)
                persist_verification(conn, pid, v, a)
                verified += 1
                logger.info(f"  [{i}/{total_analyses}] Verified: {p['title'][:50]}")
            except Exception as e:
                _record_stage_error(conn, run_id, stats, f"  [{i}/{total_analyses}] Verify error: {e}")
        stats["papers_verified"] = verified
        db.update_pipeline_run(conn, run_id, papers_verified=stats["papers_verified"])

        # ── Clustering maintenance (uses ALL working set embeddings, not just current batch) ──
        ws_papers = db.get_working_set_papers(conn)
        ws_embs = {p["id"]: all_embeddings[p["id"]] for p in ws_papers if p["id"] in all_embeddings}
        if len(ws_embs) >= rag.CLUSTER_MINIMUM:
            rag.cluster_working_set(conn, ws_embs)

        # ── Interest vector update (uses ALL working set embeddings) ──
        ws_vecs = [all_embeddings[p["id"]] for p in ws_papers if p["id"] in all_embeddings]
        if ws_vecs:
            new_iv = embed.compute_interest_vector(ws_vecs, previous_vector=embed.load_interest_vector())
            embed.save_interest_vector(new_iv)

        # ── Pruning ──
        prune_result = None
        current_iv = embed.load_interest_vector()
        if current_iv is not None:
            candidate = rag.select_prune_candidate(conn, current_iv, all_embeddings)
            if candidate:
                summary = db.get_compressed_summary(conn, candidate["id"])
                if summary:
                    try:
                        prune_result = llm.prompt_pruning(
                            candidate["title"], summary,
                            candidate.get("relevance_score", 5),
                            candidate.get("added_to_ws_at", ""),
                            profile,
                        )
                        prune_result["paper_id"] = candidate["id"]
                        prune_result["title"] = candidate["title"]
                        prune_result["preview"] = _build_prune_preview(conn, candidate, summary, prune_result)
                        action_id = db.insert_prune_action(conn, {
                            "paper_id": candidate["id"],
                            "pipeline_run_id": run_id,
                            "title": candidate["title"],
                            "recommendation": prune_result.get("prune_recommendation", "unsure"),
                            "reason": prune_result.get("reason", ""),
                            "risk_if_removed": prune_result.get("risk_if_removed", ""),
                            "preview": prune_result["preview"],
                            "status": "pending",
                        })
                        db.update_pipeline_run(
                            conn,
                            run_id,
                            prune_suggested=json.dumps({
                                "action_id": action_id,
                                "paper_id": candidate["id"],
                                "title": candidate["title"],
                                "recommendation": prune_result.get("prune_recommendation", "unsure"),
                            }),
                        )
                    except Exception as e:
                        _record_stage_error(conn, run_id, stats, f"Prune error: {e}")

        # ── Output ──
        from src.output import generate_daily_digest, generate_paper_notes
        generate_daily_digest(conn, analyses, papers_by_id, stats, prune_result, run_type=run_type)
        generate_paper_notes(conn, analyses, papers_by_id)

        # ── Persist all state ──
        db.save_index(index_all, "index_all")
        db.save_index(index_ws, "index_ws")
        db.save_ws_id_map(ws_id_map)
        db.save_embeddings(all_embeddings)
        _mark_ingestion_success(conn, until)
        db.complete_pipeline_run(conn, run_id, "success", **stats)

        logger.info(f"\n{'='*60}\nDone! F:{stats['papers_fetched']} S1:{stats['papers_passed_s1']} "
                     f"S2:{stats['papers_passed_s2']} A:{stats['papers_analyzed']} "
                     f"V:{stats['papers_verified']} WS+:{stats['papers_added_ws']}\n{'='*60}")

    except KeyboardInterrupt:
        logger.warning("Pipeline cancelled.")
        db.complete_pipeline_run(conn, run_id, "cancelled", **stats)
        raise
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        stats["error_count"] += 1
        db.complete_pipeline_run(conn, run_id, "failed", error_details=json.dumps([str(e)]), **stats)
        raise
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Research Radar ingestion pipeline.")
    parser.add_argument(
        "run_type",
        nargs="?",
        default="manual",
        help="Pipeline run label, usually 'manual' or 'scheduled'.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Use an existing pipeline_runs id instead of creating a new row.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(args.run_type, run_id=args.run_id)
