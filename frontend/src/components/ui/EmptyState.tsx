import React from 'react';

export function EmptyState(props: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <h2>{props.title}</h2>
      <p>{props.body}</p>
    </div>
  );
}

export function ProgressBar(props: { value: number; label?: string }) {
  const value = Math.max(0, Math.min(props.value, 100));
  return (
    <div
      className="progress-shell"
      role="progressbar"
      aria-label={props.label ?? 'Pipeline progress'}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div className="progress-fill" style={{ width: `${value}%` }} />
      <span>{props.label ? `${props.label} · ${value}%` : `${value}%`}</span>
    </div>
  );
}

export function PipelineStages(props: { stages: Array<{ key: string; label: string; status: string }>; compact?: boolean }) {
  return (
    <div className={props.compact ? 'pipeline-stages compact' : 'pipeline-stages'}>
      {props.stages.map((stage) => (
        <div className={`pipeline-stage ${stage.status}`} key={stage.key}>
          <span />
          <strong>{stage.label}</strong>
        </div>
      ))}
    </div>
  );
}
