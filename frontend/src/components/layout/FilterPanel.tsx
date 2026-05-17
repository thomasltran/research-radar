import React, { useEffect, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import type { ReadFilter, Report, TagStat } from '../../types';
import { recommendationLabel } from '../../utils';

export function CollapsibleFilterGroup(props: {
  title: string;
  active?: boolean;
  defaultOpen?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(Boolean(props.defaultOpen));
  useEffect(() => {
    if (props.active) setOpen(true);
  }, [props.active]);
  useEffect(() => {
    if (props.defaultOpen) setOpen(true);
  }, [props.defaultOpen]);
  return (
    <div className={props.className ? `filter-group ${props.className}` : 'filter-group'}>
      <button className="filter-group-toggle" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span>{props.title}</span>
        <ChevronDown className={open ? 'chevron open' : 'chevron'} size={14} />
      </button>
      {open && <div className="filter-group-body">{props.children}</div>}
    </div>
  );
}

export function GlobalFilterPanel(props: {
  tags: TagStat[];
  reports: Report[];
  selectedTags: string[];
  selectedReadFilter: ReadFilter;
  selectedRecommendation: string | null;
  selectedReportFilter: string | null;
  onToggleTag: (tag: string) => void;
  onSetReadFilter: (filter: ReadFilter) => void;
  onSetRecommendation: (recommendation: string | null) => void;
  onSetReport: (report: string | null) => void;
  onClear: () => void;
}) {
  const topTags = props.tags.slice(0, 12);
  const recommendationOptions = ['read', 'track'];
  const activeCount = props.selectedTags.length
    + (props.selectedRecommendation ? 1 : 0)
    + (props.selectedReportFilter ? 1 : 0)
    + (props.selectedReadFilter !== 'all' ? 1 : 0);
  const visibleReports = props.reports.filter((report) => (report.ingested_count ?? 0) > 0 || report.run_type === 'bootstrap');

  return (
    <div className="filter-panel">
      <div className="filter-header">
        <div className="filter-header-left">
          <span>Filters</span>
          {activeCount > 0 && (
            <button className="count-clear" onClick={props.onClear} aria-label="Clear filters">
              <span>{activeCount}</span>
              <X size={11} />
            </button>
          )}
        </div>
      </div>
      <CollapsibleFilterGroup title="Recommendation" active={Boolean(props.selectedRecommendation)} defaultOpen>
        <div className="toggle-grid">
          {recommendationOptions.map((option) => (
            <button
              key={option}
              className={props.selectedRecommendation === option ? `toggle-chip active intent ${option}` : `toggle-chip intent ${option}`}
              onClick={() => props.onSetRecommendation(props.selectedRecommendation === option ? null : option)}
              aria-pressed={props.selectedRecommendation === option}
            >
              {recommendationLabel(option)}
            </button>
          ))}
        </div>
      </CollapsibleFilterGroup>
      <CollapsibleFilterGroup title="Read state" active={props.selectedReadFilter !== 'all'} defaultOpen>
        <div className="toggle-grid">
          {[
            { value: 'all', label: 'All' },
            { value: 'unread', label: 'Unread' },
            { value: 'read', label: 'Read' },
          ].map((option) => (
            <button
              key={option.value}
              className={props.selectedReadFilter === option.value ? `toggle-chip active status ${option.value}` : `toggle-chip status ${option.value}`}
              onClick={() => props.onSetReadFilter(option.value as ReadFilter)}
              aria-pressed={props.selectedReadFilter === option.value}
            >
              {option.label}
            </button>
          ))}
        </div>
      </CollapsibleFilterGroup>
      <CollapsibleFilterGroup title="Report" active={Boolean(props.selectedReportFilter)} defaultOpen={visibleReports.length > 0 && visibleReports.length <= 4} className="report-filter-group">
        <div className="toggle-grid">
          {visibleReports.map((report) => {
            const id = report.run_type === 'bootstrap' ? 'seed' : String(report.id);
            const runNumber = report.run_number ?? report.id;
            const label = report.run_type === 'bootstrap' ? `Bootstrap ${runNumber}` : `Run ${runNumber}`;
            return (
              <button
                key={id}
                className={props.selectedReportFilter === id ? 'toggle-chip active' : 'toggle-chip'}
                onClick={() => props.onSetReport(props.selectedReportFilter === id ? null : id)}
                title={`${report.ingested_count ?? 0} papers, ${report.unread_count ?? 0} unread`}
                aria-pressed={props.selectedReportFilter === id}
              >
                {label} ({report.ingested_count ?? 0})
              </button>
            );
          })}
        </div>
      </CollapsibleFilterGroup>
      <CollapsibleFilterGroup title="Tags" active={props.selectedTags.length > 0} defaultOpen>
        <div className="toggle-grid">
          {topTags.map((tag) => (
            <button
              key={tag.tag}
              className={props.selectedTags.includes(tag.tag) ? 'toggle-chip active' : 'toggle-chip'}
              onClick={() => props.onToggleTag(tag.tag)}
              title={`${tag.count} papers, ${tag.unread_count} unread`}
              aria-pressed={props.selectedTags.includes(tag.tag)}
            >
              {tag.tag}
            </button>
          ))}
        </div>
      </CollapsibleFilterGroup>
    </div>
  );
}
