import React from 'react';
import type { Report } from '../types';

/* ── Date/Time Utilities ── */

export function formatDateTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    year: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function toDateTimeLocalValue(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function dateTimeLocalToIso(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

/* ── Text Utilities ── */

export function truncateAtWord(value: string, limit: number) {
  if (value.length <= limit) return value;
  const words = value.split(/\s+/).filter(Boolean);
  let output = '';
  for (const word of words) {
    const next = output ? `${output} ${word}` : word;
    if (next.length > limit) return output || word;
    output = next;
  }
  return output;
}

export function recommendationLabel(recommendation?: string | null) {
  if (recommendation === 'read') return 'Review';
  if (recommendation === 'track') return 'Track';
  if (!recommendation) return '';
  return recommendation.charAt(0).toUpperCase() + recommendation.slice(1);
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/* ── Keyboard Utilities ── */

export function activateCard(event: React.KeyboardEvent<HTMLElement>, action: () => void) {
  if (event.target !== event.currentTarget) return;
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  action();
}

/* ── Report Utilities ── */

export function pipelineProgress(report: Report) {
  const stages = report.stages ?? [];
  if (stages.length === 0) return 0;
  const done = stages.filter((stage) => stage.status === 'done').length;
  const active = stages.some((stage) => stage.status === 'active') ? 0.5 : 0;
  return Math.min(100, Math.round(((done + active) / stages.length) * 100));
}

export function isMaintenanceReport(report: Report) {
  return report.run_type === 'relink' || report.run_type === 'reanalyze' || report.run_type === 'bootstrap';
}

export function reportTitle(report: Report) {
  const runNumber = report.run_number ?? report.id;
  if (report.run_type === 'bootstrap') return `Bootstrap Job ${runNumber}`;
  if (report.run_type === 'relink') return `Relink Job ${runNumber}`;
  if (report.run_type === 'reanalyze') return `Reanalysis Job ${runNumber}`;
  return `Pipeline Run ${runNumber}`;
}

export function reportCount(report: Report) {
  if (report.run_type === 'relink') return report.papers_analyzed ?? report.papers_fetched ?? 0;
  if (report.run_type === 'reanalyze') return report.papers_analyzed ?? report.papers_passed_s2 ?? report.papers_fetched ?? 0;
  return report.ingested_count ?? report.papers_fetched ?? 0;
}

export function reportProgressLabel(report: Report) {
  const progress = (verb: string, current: number, total: number, emptyLabel: string) => {
    if (total <= 0) return emptyLabel;
    return `${verb} ${current}/${total}`;
  };

  if (report.run_type === 'bootstrap') {
    const fetched = report.papers_fetched ?? 0;
    const added = report.papers_added_ws ?? 0;
    if (report.status === 'success') return `Bootstrapped ${added} seeds`;
    if (report.status === 'cancelled') return `Cancelled`;
    if (report.status === 'failed') return `Failed`;
    if (added > 0) return `Embedded ${added}`;
    if (fetched > 0) return `Found ${fetched} seeds`;
    return 'Waiting';
  }

  if (report.run_type === 'relink') {
    const rescored = report.papers_fetched ?? 0;
    const workingSet = report.papers_passed_s1 ?? 0;
    const refreshed = report.papers_analyzed ?? 0;
    if (report.status === 'success') return `Relinked ${refreshed} relationships`;
    if (report.status === 'cancelled') return `Cancelled after ${refreshed} refreshed`;
    if (report.status === 'failed') return `Stopped after ${refreshed} refreshed`;
    if (refreshed > 0) return `Refreshed ${refreshed}`;
    if (workingSet > 0) return `Indexed ${workingSet} working-set papers`;
    if (rescored > 0) return `Rescored ${rescored}`;
    return 'Waiting';
  }

  if (report.run_type === 'reanalyze') {
    const target = report.papers_fetched ?? 0;
    const compressed = report.papers_passed_s2 ?? 0;
    const analyzed = report.papers_analyzed ?? 0;
    const verified = report.papers_verified ?? 0;
    if (report.status === 'success') return progress('Reanalyzed', analyzed, target, 'No active papers');
    if (report.status === 'cancelled') return `Cancelled after ${analyzed} analyzed`;
    if (report.status === 'failed') return `Stopped after ${analyzed} analyzed`;
    if (verified > 0) return `Analyzed ${analyzed}/${Math.max(target, analyzed)}, verified ${verified}`;
    if (analyzed > 0) return progress('Analyzed', analyzed, target, `Analyzed ${analyzed}`);
    if (compressed > 0) return progress('Compressed', compressed, target, `Compressed ${compressed}`);
    if (target > 0) return `Queued ${target}`;
    return 'Waiting';
  }

  const fetched = report.papers_fetched ?? 0;
  const similarity = report.papers_passed_s1 ?? 0;
  const scored = report.papers_passed_s2 ?? 0;
  const analyzed = report.papers_analyzed ?? 0;
  const verified = report.papers_verified ?? 0;

  if (report.status === 'success') {
    return progress('Done', analyzed, Math.max(scored, analyzed), 'Done, no new papers');
  }
  if (report.status === 'cancelled') {
    return progress('Cancelled', analyzed, Math.max(scored, analyzed), `Cancelled after ${analyzed} analyzed`);
  }
  if (report.status === 'failed') {
    return progress('Stopped', analyzed, Math.max(scored, analyzed), `Stopped after ${analyzed} analyzed`);
  }
  if (verified > 0) return `Verified ${verified}/${Math.max(analyzed, verified)}`;
  if (analyzed > 0) return `Analyzed ${analyzed}/${Math.max(scored, analyzed)}`;
  if (scored > 0) return `Scored ${scored}/${Math.max(similarity, scored)}`;
  if (similarity > 0) return `Screened ${similarity}/${Math.max(fetched, similarity)}`;
  if (fetched > 0) return `Scanned ${fetched}`;
  return 'Waiting';
}

export function scanWindowLabel(start: string, end: string) {
  const since = start ? formatDateTime(dateTimeLocalToIso(start)) : 'Beginning';
  return `${since} -> ${formatDateTime(dateTimeLocalToIso(end))}`;
}
