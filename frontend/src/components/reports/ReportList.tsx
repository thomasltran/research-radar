import React from 'react';
import { Check, Minus, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import type {
  MaintenanceMode, PipelinePreview, PipelineSource, PruneAction,
  Report, ReportDetail, ReportMode, WorkspaceStats, PipelineLogs,
} from '../../types';
import {
  activateCard, formatDateTime, isMaintenanceReport, pipelineProgress,
  reportCount, reportProgressLabel, reportTitle,
} from '../../utils';
import { EmptyState, ProgressBar, PipelineStages } from '../ui/EmptyState';
import { MarkdownBlock } from '../ui/Markdown';
import { TerminalLog } from '../ui/TerminalLog';

export function ReportList(props: {
  reports: Report[];
  selected: string | null;
  mode: ReportMode;
  onModeChange: (mode: ReportMode) => void;
  onSelect: (id: number | null) => void;
  preview?: PipelinePreview | null;
  onRun: () => void;
  onCancel: (id: number) => void;
  isStarting: boolean;
  error: string | null;
  stats?: WorkspaceStats | null;
  pruneActions: PruneAction[];
  sources: PipelineSource[];
  previewNow: Date;
  scanStart: string;
  scanEnd: string;
  scheduleEnabled: boolean;
  scheduleTime: string;
  onSetScanStart: (value: string) => void;
  onSetScanEnd: (value: string) => void;
  onSetScheduleEnabled: (enabled: boolean) => void;
  onSetScheduleTime: (value: string) => void;
  onPruneAction: (id: number, status: 'applied' | 'kept') => void;
  onToggleSource: (source: PipelineSource) => void;
  maintenanceMode: MaintenanceMode;
  onMaintenanceModeChange: (mode: MaintenanceMode) => void;
  onRunMaintenance: (mode?: MaintenanceMode) => void;
  isMaintaining: boolean;
}) {
  const runningReport = props.reports.find((report) => report.status === 'running' && !isMaintenanceReport(report));
  const runningMaintenance = props.reports.find((report) => report.status === 'running' && report.run_type === props.maintenanceMode);
  const anyRunningMaintenance = props.reports.some((report) => report.status === 'running' && isMaintenanceReport(report));
  const anyRunning = props.isStarting || props.isMaintaining || Boolean(props.preview?.running) || Boolean(runningReport) || anyRunningMaintenance;
  const intakeReports = props.reports.filter((report) => !isMaintenanceReport(report));
  const maintenanceReports = props.reports.filter((report) => report.run_type === props.maintenanceMode);
  const activeReports = props.mode === 'maintenance' ? maintenanceReports : intakeReports;
  const maintenanceJobName = props.maintenanceMode === 'relink'
    ? 'relink'
    : props.maintenanceMode === 'reanalyze'
      ? 'reanalysis'
      : 'bootstrap';
  const maintenanceCopy = props.maintenanceMode === 'relink'
    ? {
      title: 'Relink Workspace',
      body: 'Rescore papers, rebuild indexes/clusters, and refresh paper-to-paper relationships. Does not rewrite summaries.',
      button: 'Relink',
    }
    : props.maintenanceMode === 'reanalyze'
    ? {
      title: 'Reanalyze Library',
      body: 'Rerun compression, summaries, novelty/relation analysis, high-score verification, and note generation from stored abstracts. No fetch.',
      button: 'Reanalyze',
    }
    : {
      title: 'Bootstrap Database',
      body: 'Fetch seed papers, generate their initial embeddings, and set the baseline interest vector. Usually run once on fresh setup.',
      button: 'Bootstrap',
    };

  function switchMode(mode: ReportMode) {
    props.onModeChange(mode);
    const nextReport = mode === 'maintenance' ? maintenanceReports[0] : intakeReports[0];
    props.onSelect(nextReport?.id ?? null);
  }

  function switchMaintenanceMode(mode: MaintenanceMode) {
    props.onMaintenanceModeChange(mode);
    if (props.mode !== 'maintenance') return;
    const nextReport = props.reports.find((report) => report.run_type === mode);
    props.onSelect(nextReport?.id ?? null);
  }

  return (
    <div className="report-list-shell">
      <div className="report-mode-tabs" role="tablist" aria-label="Report type">
        <button className={props.mode === 'intake' ? 'active' : ''} onClick={() => switchMode('intake')} role="tab" aria-selected={props.mode === 'intake'}>
          Runs
        </button>
        <button className={props.mode === 'maintenance' ? 'active' : ''} onClick={() => switchMode('maintenance')} role="tab" aria-selected={props.mode === 'maintenance'}>
          Maintenance
        </button>
      </div>
      {props.mode === 'intake' ? (
        <section className="pipeline-run-card">
          <div className="pipeline-run-main">
            <span className="eyebrow">Manual pipeline</span>
            <h2>Run Intake</h2>
            <div className="source-selector" aria-label="Pipeline source">
              {([
                ['semantic_scholar', 'Semantic Scholar'],
                ['arxiv', 'arXiv'],
              ] as Array<[PipelineSource, string]>).map(([value, label]) => (
                <button
                  key={value}
                  className={props.sources.includes(value) ? 'source-option active' : 'source-option'}
                  onClick={() => props.onToggleSource(value)}
                  disabled={anyRunning}
                  aria-pressed={props.sources.includes(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            {runningReport?.stages && runningReport.stages.length > 0 && (
              <ProgressBar value={pipelineProgress(runningReport)} label={reportProgressLabel(runningReport)} />
            )}
            <div className="range-stack">
              <label>
                <span>Start</span>
                <input type="datetime-local" value={props.scanStart} onChange={(event) => props.onSetScanStart(event.target.value)} disabled={anyRunning} />
              </label>
              <label>
                <span>End</span>
                <input type="datetime-local" value={props.scanEnd} onChange={(event) => props.onSetScanEnd(event.target.value)} disabled={anyRunning} />
              </label>
            </div>
            <div className="schedule-row compact">
              <label className="schedule-toggle">
                <input type="checkbox" checked={props.scheduleEnabled} onChange={(event) => props.onSetScheduleEnabled(event.target.checked)} />
                <span>Daily schedule</span>
              </label>
              {props.scheduleEnabled && (
                <input type="time" value={props.scheduleTime} onChange={(event) => props.onSetScheduleTime(event.target.value)} />
              )}
            </div>
            {props.error && <div className="error-text">{props.error}</div>}
          </div>
          <div className="pipeline-run-actions">
            {runningReport && (
              <button className="ghost-button cancel-button" onClick={() => props.onCancel(runningReport.id)}>
                <Square size={15} /> Cancel
              </button>
            )}
            <button className="ghost-button pipeline-run-button" onClick={props.onRun} disabled={anyRunning}>
              <Play size={16} /> {props.isStarting ? 'Starting' : 'Run'}
            </button>
          </div>
        </section>
      ) : (
        <section className="pipeline-run-card relink-run-card">
          <div className="pipeline-run-main">
            <span className="eyebrow">Maintenance job</span>
            <h2>{maintenanceCopy.title}</h2>
            <div className="source-selector" aria-label="Maintenance job">
              {([
                ['relink', 'Relink'],
                ['reanalyze', 'Reanalyze'],
                ['bootstrap', 'Bootstrap'],
              ] as Array<[MaintenanceMode, string]>).map(([value, label]) => (
                <button
                  key={value}
                  className={props.maintenanceMode === value ? 'source-option active' : 'source-option'}
                  onClick={() => switchMaintenanceMode(value)}
                  disabled={anyRunning}
                  aria-pressed={props.maintenanceMode === value}
                >
                  {label}
                </button>
              ))}
            </div>
            <p>{maintenanceCopy.body}</p>
            {runningMaintenance?.stages && runningMaintenance.stages.length > 0 && (
              <ProgressBar value={pipelineProgress(runningMaintenance)} label={reportProgressLabel(runningMaintenance)} />
            )}
          </div>
          <div className="pipeline-run-actions">
            {runningMaintenance && (
              <button className="ghost-button cancel-button" onClick={() => props.onCancel(runningMaintenance.id)}>
                <Square size={15} /> Cancel
              </button>
            )}
            <button 
              className="ghost-button" 
              onClick={() => props.onRunMaintenance(props.maintenanceMode)} 
              disabled={anyRunning || (props.maintenanceMode === 'bootstrap' && (props.stats?.working_set_count ?? 0) > 0)}
              title={props.maintenanceMode === 'bootstrap' && (props.stats?.working_set_count ?? 0) > 0 ? "Database already bootstrapped. Clear data to re-bootstrap." : undefined}
            >
              <RefreshCw size={15} /> {props.isMaintaining ? 'Starting' : maintenanceCopy.button}
            </button>
          </div>
        </section>
      )}
      <section className="workspace-status-panel">
        <div>
          <span className="eyebrow">Working set</span>
          <strong>{props.stats?.working_set_count ?? 0}</strong>
        </div>
        <div>
          <span className="eyebrow">Pending prune</span>
          <strong>{props.stats?.pending_prune_count ?? props.pruneActions.length}</strong>
        </div>
      </section>
      {props.pruneActions.length > 0 && (
        <section className="prune-panel">
          <div className="section-heading">
            <h2>Prune Review</h2>
          </div>
          {props.pruneActions.map((action) => (
            <article className="prune-action" key={action.id}>
              <div>
                <strong>{action.title}</strong>
                <p>{action.reason || action.risk_if_removed || 'Review this working-set candidate.'}</p>
              </div>
              <div className="prune-actions">
                <button className="ghost-button" onClick={() => props.onPruneAction(action.id, 'kept')}>
                  <Check size={15} /> Keep
                </button>
                <button className="ghost-button cancel-button" onClick={() => props.onPruneAction(action.id, 'applied')}>
                  <Minus size={15} /> Remove
                </button>
              </div>
            </article>
          ))}
        </section>
      )}
      <div className="paper-list-scroll">
        <div className="paper-list">
          {activeReports.length === 0 && (
            <EmptyState
              title={props.mode === 'maintenance' ? `No ${maintenanceJobName} jobs` : 'No reports'}
              body={props.mode === 'maintenance' ? `Run ${maintenanceJobName} to create a maintenance report.` : 'Run the pipeline to create reports.'}
            />
          )}
          {activeReports.map((report) => (
            <article
              key={String(report.id)}
              className={props.selected === String(report.id) ? 'paper-card selected' : 'paper-card'}
              onClick={() => props.onSelect(report.id)}
              onKeyDown={(event) => activateCard(event, () => props.onSelect(report.id))}
              role="button"
              tabIndex={0}
              aria-label={isMaintenanceReport(report) ? `Open ${report.run_type} job ${report.id}` : `Open pipeline run ${report.id}`}
            >
              <div className="paper-card-top">
                <span className="score">{reportCount(report)}</span>
              </div>
              <h2>{reportTitle(report)}</h2>
              <p>{formatDateTime(report.completed_at ?? report.started_at) || 'Seed papers loaded before pipeline reports.'} {report.status ? `Status: ${report.status}` : ''}</p>
              {report.stages && report.stages.length > 0 && <PipelineStages stages={report.stages} compact />}
              <div className="chips">
                <span className="chip">{report.run_type ?? 'manual'}</span>
                {!isMaintenanceReport(report) && <span className="chip">{report.unread_count ?? 0} unread</span>}
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ReportDetailPanel(props: {
  detail: ReportDetail | null;
  logs?: PipelineLogs | null;
  loading?: boolean;
  onCancel: (id: number) => void;
  onSelectPaper: (id: string) => void;
}) {
  if (props.loading) return <EmptyState title="Loading report" body="Fetching the selected report and logs." />;
  if (!props.detail) return <EmptyState title="No report selected" body="Select a report to inspect its digest and papers." />;
  return (
    <div className="detail-scroll">
      <div className="detail-header">
        <div>
          <span className="eyebrow">{props.detail.report.run_type ?? 'report'}</span>
          <h1>{props.detail.report.title ?? reportTitle(props.detail.report)}</h1>
          <p>
            {props.detail.report.run_type === 'relink'
              ? `${props.detail.report.papers_analyzed ?? 0} relationships refreshed`
              : props.detail.report.run_type === 'reanalyze'
                ? `${props.detail.report.papers_analyzed ?? 0} papers reanalyzed`
                : `${props.detail.papers.length} papers ingested`}
          </p>
        </div>
        {props.detail.report.status === 'running' && (
          <div className="detail-actions">
            <button className="ghost-button cancel-button" onClick={() => props.onCancel(props.detail!.report.id)}>
              <Square size={15} /> Cancel
            </button>
          </div>
        )}
      </div>
      {props.detail.report.stages && props.detail.report.stages.length > 0 && (
        <section className="section">
          <h2>{isMaintenanceReport(props.detail.report) ? 'Maintenance' : 'Pipeline'}</h2>
          <ProgressBar value={pipelineProgress(props.detail.report)} label={reportProgressLabel(props.detail.report)} />
          <PipelineStages stages={props.detail.report.stages} />
          <div className="pipeline-metrics">
            {props.detail.report.run_type === 'relink' ? (
              <>
                <span>Rescored <strong>{props.detail.report.papers_fetched ?? 0}</strong></span>
                <span>Working set <strong>{props.detail.report.papers_passed_s1 ?? 0}</strong></span>
                <span>Relations <strong>{props.detail.report.papers_analyzed ?? 0}</strong></span>
              </>
            ) : props.detail.report.run_type === 'reanalyze' ? (
              <>
                <span>Active targets <strong>{props.detail.report.papers_fetched ?? 0}</strong></span>
                <span>Working set <strong>{props.detail.report.papers_passed_s1 ?? 0}</strong></span>
                <span>Compressed <strong>{props.detail.report.papers_passed_s2 ?? 0}</strong></span>
                <span>Analyzed <strong>{props.detail.report.papers_analyzed ?? 0}</strong></span>
                <span>Verified <strong>{props.detail.report.papers_verified ?? 0}</strong></span>
              </>
            ) : props.detail.report.run_type === 'bootstrap' ? (
              <>
                <span>Seeds <strong>{props.detail.report.papers_fetched ?? 0}</strong></span>
                <span>Embedded <strong>{props.detail.report.papers_added_ws ?? 0}</strong></span>
              </>
            ) : (
              <>
                <span>Fetched <strong>{props.detail.report.papers_fetched ?? 0}</strong></span>
                <span>Similarity <strong>{props.detail.report.papers_passed_s1 ?? 0}</strong></span>
                <span>Scored <strong>{props.detail.report.papers_passed_s2 ?? 0}</strong></span>
                <span>Analyzed <strong>{props.detail.report.papers_analyzed ?? 0}</strong></span>
                <span>Verified <strong>{props.detail.report.papers_verified ?? 0}</strong></span>
              </>
            )}
          </div>
        </section>
      )}
      <section className="section">
        <div className="section-heading">
          <h2>Logs</h2>
          <span className="chip"><Terminal size={12} /> terminal</span>
        </div>
        <TerminalLog log={props.logs?.log} />
      </section>
      {props.detail.report.status === 'success' && (
        <section className="section">
          <h2>Digest</h2>
          <div className="section-body">
            <MarkdownBlock content={props.detail.report.digest || 'No digest Markdown was found for this report.'} />
          </div>
        </section>
      )}
      {!isMaintenanceReport(props.detail.report) && (
        <section className="section">
          <h2>Papers From This Report</h2>
          <div className="compact-paper-list">
            {props.detail.papers.map((paper) => (
              <button key={paper.id} onClick={() => props.onSelectPaper(paper.id)}>
                <span>{paper.title}</span>
                <strong>{paper.relevance_score ?? '?'}</strong>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
