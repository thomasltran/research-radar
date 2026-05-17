"""Workspace maintenance helpers."""

from __future__ import annotations

import logging
import argparse
import json

from src import db, embed, llm, output, rag
from src.config import load_config
from src.pipeline_policy import WORKING_SET_ENTRY_THRESHOLD
from src.profile import canonicalize_tags, load_research_profile
from src.services.analysis_normalization import build_analysis_record
from src.services.analysis_verification import persist_verification
from src.services.recommendation_policy import apply_review_policy, should_verify_analysis

logger = logging.getLogger(__name__)
_CONFIG = load_config()
MAX_CONSECUTIVE_RESCORING_FAILURES = _CONFIG.int("maintenance.max_consecutive_rescoring_failures", 5)


def _refresh_interest_vector(ws_papers: list[dict], embeddings_by_id: dict) -> None:
    ws_vecs = [embeddings_by_id[paper["id"]] for paper in ws_papers if paper["id"] in embeddings_by_id]
    if ws_vecs:
        embed.save_interest_vector(embed.compute_interest_vector(ws_vecs, previous_vector=embed.load_interest_vector()))


def _rescore_papers(conn, profile: dict, run_id: int | None = None) -> dict:
    rows = conn.execute("""
        SELECT id, title, abstract, in_working_set
        FROM papers
        WHERE run_id IS NOT NULL AND source != 'bootstrap'
        ORDER BY ingested_at DESC
    """).fetchall()

    rescored = 0
    skipped = 0
    ws_added = 0
    ws_removed = 0
    consecutive_failures = 0

    total = len(rows)
    for index, row in enumerate(rows, 1):
        try:
            logger.info("[%s/%s] Rescoring: %s", index, total, row["title"][:70])
            res = llm.prompt_relevance_scoring(row["title"], row["abstract"], profile)
            score = int(res.get("relevance_score", 0) or 0)
            conn.execute(
                "UPDATE papers SET relevance_score=?, paper_type=?, matching_topics=? WHERE id=?",
                (
                    score,
                    res.get("paper_type", "other"),
                    json.dumps(res.get("matching_topics", [])),
                    row["id"],
                ),
            )
            desired_ws = score >= WORKING_SET_ENTRY_THRESHOLD
            current_ws = bool(row["in_working_set"])
            if desired_ws != current_ws:
                db.mark_working_set(conn, row["id"], desired_ws)
                if desired_ws:
                    ws_added += 1
                else:
                    ws_removed += 1
            if score < WORKING_SET_ENTRY_THRESHOLD:
                conn.execute("""
                    UPDATE analyses
                    SET recommendation = 'track',
                        recommendation_reason = TRIM(
                            COALESCE(recommendation_reason, '') || ' Demoted from Review because relevance score '
                            || ? || ' is below the working-set threshold ' || ? || '.'
                        )
                    WHERE paper_id = ?
                      AND LOWER(COALESCE(recommendation, '')) = 'read'
                      AND COALESCE(recommendation_reason, '') NOT LIKE '%Demoted from Review%'
                """, (score, WORKING_SET_ENTRY_THRESHOLD, row["id"]))
            rescored += 1
            consecutive_failures = 0
            if run_id is not None:
                db.update_pipeline_run(conn, run_id, papers_fetched=rescored, error_count=skipped)
            logger.info("[%s/%s] Rescored %s -> %s", index, total, score, row["title"][:70])
        except Exception:
            logger.exception("Failed to rescore paper %s", row["id"])
            skipped += 1
            consecutive_failures += 1
            if run_id is not None:
                db.update_pipeline_run(conn, run_id, papers_fetched=rescored, error_count=skipped)
            if consecutive_failures >= MAX_CONSECUTIVE_RESCORING_FAILURES:
                raise RuntimeError(
                    f"Stopping relink after {consecutive_failures} consecutive relevance scoring failures"
                )

    conn.commit()
    return {
        "rescored_count": rescored,
        "skipped_count": skipped,
        "working_set_added": ws_added,
        "working_set_removed": ws_removed,
    }


def relink_workspace(conn, run_id: int | None = None) -> dict:
    profile = load_research_profile()
    logger.info("Relink: rescoring papers against research profile")
    rescoring = _rescore_papers(conn, profile, run_id=run_id)
    if run_id is not None:
        db.update_pipeline_run(conn, run_id, papers_fetched=rescoring["rescored_count"])

    logger.info("Relink: rebuilding library and working-set indexes")
    all_embeddings = db.load_embeddings()
    db.rebuild_all_papers_index(conn, all_embeddings)
    index_ws, ws_id_map = db.rebuild_working_set_index(conn, all_embeddings)

    logger.info("Relink: organizing the working set")
    ws_papers = db.get_working_set_papers(conn)
    ws_embs = {paper["id"]: all_embeddings[paper["id"]] for paper in ws_papers if paper["id"] in all_embeddings}
    clusters_recomputed = False
    if ws_papers:
        clusters_recomputed = bool(rag.cluster_working_set(conn, ws_embs))
    _refresh_interest_vector(ws_papers, all_embeddings)
    if run_id is not None:
        db.update_pipeline_run(
            conn,
            run_id,
            papers_passed_s1=len(ws_papers),
            papers_passed_s2=1 if clusters_recomputed else 0,
        )

    logger.info("Relink: refreshing relationship context for decision-relevant papers")
    target_rows = conn.execute("""
        SELECT p.id
        FROM papers p
        LEFT JOIN paper_read_state prs ON prs.paper_id = p.id
        WHERE p.run_id IS NOT NULL
          AND (
              p.in_working_set = 1
              OR
              COALESCE(prs.read, 0) = 1
              OR COALESCE(prs.reading_status, '') IN ('reading_list', 'currently_reading')
              OR EXISTS (
                  SELECT 1
                  FROM analyses a
                  WHERE a.paper_id = p.id
                    AND LOWER(COALESCE(a.recommendation, '')) IN ('read', 'track')
              )
          )
        ORDER BY p.relevance_score DESC, p.ingested_at DESC
    """).fetchall()

    refreshed = 0
    skipped = 0
    for row in target_rows:
        paper = db.get_paper(conn, row["id"])
        analysis = db.get_analysis(conn, row["id"])
        if not paper or not analysis:
            skipped += 1
            continue
        paper_id = row["id"]
        paper_emb = all_embeddings.get(paper_id)
        if paper_emb is None:
            skipped += 1
            continue
        retrieved = rag.retrieve_context(conn, paper_emb, index_ws, ws_id_map, rag.DEFAULT_RETRIEVAL_K, exclude_id=paper_id)
        refreshed_analysis = llm.prompt_relationship_update(paper["title"], paper["abstract"], retrieved, profile, existing_analysis=analysis)
        updated = {
            "paper_id": paper_id,
            "summary": analysis.get("summary", ""),
            "key_contributions": analysis.get("key_contributions", "[]"),
            "is_novel": analysis.get("is_novel"),
            "novelty_explanation": analysis.get("novelty_explanation", ""),
            "extends": json.dumps(refreshed_analysis.get("extends", [])),
            "overlaps_with": json.dumps(refreshed_analysis.get("overlaps_with", [])),
            "relation_to_research": refreshed_analysis.get("relationship_rationale", analysis.get("relation_to_research", "")),
            "recommendation": analysis.get("recommendation", "track"),
            "recommendation_reason": analysis.get("recommendation_reason", ""),
            "confidence": refreshed_analysis.get("confidence", analysis.get("confidence", "medium")),
            "retrieved_paper_ids": json.dumps([paper_item["id"] for paper_item in retrieved]),
        }
        db.insert_analysis(conn, updated)
        refreshed += 1
        if run_id is not None:
            db.update_pipeline_run(conn, run_id, papers_analyzed=refreshed)

    logger.info(
        "Relinked workspace: rescored=%s added=%s removed=%s index=%s papers, refreshed=%s, skipped=%s, organized=%s",
        rescoring["rescored_count"],
        rescoring["working_set_added"],
        rescoring["working_set_removed"],
        len(ws_papers),
        refreshed,
        skipped,
        clusters_recomputed,
    )
    return {
        **rescoring,
        "working_set_count": len(ws_papers),
        "refreshed_count": refreshed,
        "skipped_count": skipped,
        "clusters_recomputed": clusters_recomputed,
    }


def reanalyze_workspace(conn, run_id: int | None = None, working_set_only: bool = False, all_papers: bool = False) -> dict:
    """
    Regenerate summaries/analyses from stored paper metadata.

    This intentionally does not fetch from arXiv/S2. It uses the title, abstract,
    metadata, and embeddings already persisted in SQLite/data files.
    """
    profile = load_research_profile()
    all_embeddings = db.load_embeddings()
    index_ws, ws_id_map = db.rebuild_working_set_index(conn, all_embeddings)

    ws_papers = db.get_working_set_papers(conn)
    ws_embs = {paper["id"]: all_embeddings[paper["id"]] for paper in ws_papers if paper["id"] in all_embeddings}
    if len(ws_embs) >= rag.CLUSTER_MINIMUM:
        rag.cluster_working_set(conn, ws_embs)
    _refresh_interest_vector(ws_papers, all_embeddings)

    if all_papers:
        papers = db.get_reanalyzable_papers(conn)
        target_scope = "all_non_bootstrap"
    elif working_set_only:
        papers = db.get_reanalyzable_working_set_papers(conn)
        target_scope = "working_set"
    else:
        papers = db.get_reanalysis_target_papers(conn)
        target_scope = "active"
    analyses = []
    papers_by_id = {paper["id"]: paper for paper in papers}
    compressed = 0
    analyzed = 0
    verified = 0
    skipped = 0

    if run_id is not None:
        db.update_pipeline_run(conn, run_id, papers_fetched=len(papers), papers_passed_s1=len(ws_papers))

    logger.info("Reanalyze: regenerating compression and analysis for %s %s papers", len(papers), target_scope)
    for index, paper in enumerate(papers, 1):
        paper_id = paper["id"]
        paper_emb = all_embeddings.get(paper_id)

        try:
            comp = llm.prompt_compression(paper["title"], paper["abstract"], profile)
            key_terms = canonicalize_tags(comp.get("key_terms", []), profile.get("tags", []))
            db.insert_compressed_summary(conn, {
                "paper_id": paper_id,
                "contributions": json.dumps(comp.get("contributions", [])),
                "method": comp.get("method", ""),
                "key_terms": json.dumps(key_terms),
                "domain": comp.get("domain", ""),
            })
            compressed += 1

            if paper_emb is None:
                logger.warning("[%s/%s] Missing embedding, analyzing without retrieval context: %s", index, len(papers), paper["title"][:70])
                retrieved = []
            else:
                retrieved = rag.retrieve_context(conn, paper_emb, index_ws, ws_id_map, rag.DEFAULT_RETRIEVAL_K, exclude_id=paper_id)
            analysis = llm.prompt_rag_analysis(paper["title"], paper["abstract"], retrieved, profile)
            rec = apply_review_policy(build_analysis_record(paper_id, analysis, [item["id"] for item in retrieved]), paper)
            db.insert_analysis(conn, rec)
            analyses.append({**rec, "title": paper["title"], "paper": paper})
            analyzed += 1

            if should_verify_analysis(rec, paper):
                verification = llm.prompt_verification(rec, paper["abstract"], retrieved)
                corrected = persist_verification(conn, paper_id, verification, rec)
                if corrected:
                    analyses[-1]["recommendation"] = corrected
                verified += 1

            logger.info("[%s/%s] Reanalyzed: %s", index, len(papers), paper["title"][:70])
        except Exception:
            logger.exception("[%s/%s] Reanalysis failed: %s", index, len(papers), paper["title"][:70])
            skipped += 1

        if run_id is not None:
            db.update_pipeline_run(
                conn,
                run_id,
                papers_passed_s2=compressed,
                papers_analyzed=analyzed,
                papers_verified=verified,
                error_count=skipped,
            )

    if analyses:
        output.generate_paper_notes(conn, analyses, papers_by_id)

    result = {
        "target_count": len(papers),
        "working_set_count": len(ws_papers),
        "compressed_count": compressed,
        "reanalyzed_count": analyzed,
        "verified_count": verified,
        "skipped_count": skipped,
        "working_set_only": working_set_only,
        "target_scope": target_scope,
    }
    logger.info("Reanalyze complete: %s", result)
    return result


def run_relink_job(run_id: int) -> None:
    conn = db.get_connection()
    db.init_schema(conn)
    try:
        result = relink_workspace(conn, run_id=run_id)
        db.complete_pipeline_run(
            conn,
            run_id,
            "success",
            papers_fetched=result["rescored_count"],
            papers_passed_s1=result["working_set_count"],
            papers_passed_s2=1 if result["clusters_recomputed"] else 0,
            papers_analyzed=result["refreshed_count"],
            papers_verified=0,
            error_details=json.dumps(result),
        )
    except KeyboardInterrupt:
        logger.warning("Relink cancelled.")
        db.complete_pipeline_run(conn, run_id, "cancelled")
        raise
    except Exception as exc:
        logger.exception("Relink failed")
        db.complete_pipeline_run(conn, run_id, "failed", error_details=json.dumps([str(exc)]))
        raise


def run_reanalyze_job(run_id: int, working_set_only: bool = False, all_papers: bool = False) -> None:
    conn = db.get_connection()
    db.init_schema(conn)
    try:
        result = reanalyze_workspace(conn, run_id=run_id, working_set_only=working_set_only, all_papers=all_papers)
        db.complete_pipeline_run(
            conn,
            run_id,
            "success",
            papers_fetched=result["target_count"],
            papers_passed_s1=result["working_set_count"],
            papers_passed_s2=result["compressed_count"],
            papers_analyzed=result["reanalyzed_count"],
            papers_verified=result["verified_count"],
            error_count=result["skipped_count"],
            error_details=json.dumps(result),
        )
    except KeyboardInterrupt:
        logger.warning("Reanalysis cancelled.")
        db.complete_pipeline_run(conn, run_id, "cancelled")
        raise
    except Exception as exc:
        logger.exception("Reanalysis failed")
        db.complete_pipeline_run(conn, run_id, "failed", error_details=json.dumps([str(exc)]))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run workspace maintenance.")
    parser.add_argument("mode", nargs="?", choices=("relink", "reanalyze"), default="relink")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--working-set-only", action="store_true")
    parser.add_argument("--all-papers", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = db.get_connection()
    db.init_schema(conn)
    run_id = args.run_id or db.create_pipeline_run(conn, args.mode)
    if args.mode == "reanalyze":
        run_reanalyze_job(run_id, working_set_only=args.working_set_only, all_papers=args.all_papers)
    else:
        run_relink_job(run_id)
