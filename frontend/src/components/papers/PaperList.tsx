import React from 'react';
import { Eye, EyeOff, EyeOff as EyeOffIcon, Folder, Minus, Plus, X } from 'lucide-react';
import type { Paper, PaperFolder, ReadingStatus } from '../../types';
import { activateCard, recommendationLabel } from '../../utils';
import { EmptyState } from '../ui/EmptyState';

export function ProjectDropdown(props: {
  paper: Paper;
  folders: PaperFolder[];
  compact?: boolean;
  onToggleFolder: (id: string, folder: PaperFolder, inFolder: boolean) => void;
}) {
  const folderIds = new Set(props.paper.folders.map((folder) => folder.id));
  return (
    <label className={props.compact ? 'project-dropdown compact' : 'project-dropdown'}>
      <Folder size={props.compact ? 13 : 15} />
      <select
        value=""
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => {
          event.stopPropagation();
          const folder = props.folders.find((item) => item.id === Number(event.target.value));
          if (!folder) return;
          props.onToggleFolder(props.paper.id, folder, !folderIds.has(folder.id));
          event.currentTarget.value = '';
        }}
        disabled={props.folders.length === 0}
        aria-label="Change project membership"
      >
        <option value="" disabled hidden>{props.folders.length === 0 ? 'No projects' : 'Project'}</option>
        {props.folders.map((folder) => (
          <option key={folder.id} value={folder.id}>
            {folderIds.has(folder.id) ? `Remove from ${folder.name}` : `Add to ${folder.name}`}
          </option>
        ))}
      </select>
    </label>
  );
}

export function PaperCardBody(props: {
  paper: Paper;
  folders: PaperFolder[];
  onRead: (id: string, read: boolean) => void;
  onReadingStatus: (id: string, status: ReadingStatus) => void;
  onToggleFolder: (id: string, folder: PaperFolder, inFolder: boolean) => void;
}) {
  return (
    <>
      <div className="paper-card-top">
        <div className="paper-card-meta">
          <span className="score">{props.paper.relevance_score ?? '?'}</span>
          {props.paper.semantic_score != null && (
            <span className="chip semantic-match">{Math.round(props.paper.semantic_score * 100)}% match</span>
          )}
          {props.paper.recommendation && <span className={`chip intent ${props.paper.recommendation}`}>{recommendationLabel(props.paper.recommendation)}</span>}
          <span className={props.paper.read ? 'chip status read' : 'chip status unread'}>{props.paper.read ? 'Read' : 'Unread'}</span>
        </div>
        <div className="paper-card-actions">
          <button
            className={props.paper.read ? 'read-toggle read' : 'read-toggle'}
            title={props.paper.read ? 'Mark unread' : 'Mark read'}
            aria-pressed={props.paper.read}
            onClick={(event) => {
              event.stopPropagation();
              props.onRead(props.paper.id, !props.paper.read);
            }}
          >
            {props.paper.read ? <Eye size={15} /> : <EyeOff size={15} />}
          </button>
          <button
            className={props.paper.reading_status === 'reading_list' ? 'reading-list-icon-toggle active' : 'reading-list-icon-toggle'}
            title={props.paper.reading_status === 'reading_list' ? 'Remove from reading list' : 'Add to reading list'}
            aria-label={props.paper.reading_status === 'reading_list' ? 'Remove from reading list' : 'Add to reading list'}
            aria-pressed={props.paper.reading_status === 'reading_list'}
            onClick={(event) => {
              event.stopPropagation();
              props.onReadingStatus(props.paper.id, props.paper.reading_status === 'reading_list' ? '' : 'reading_list');
            }}
          >
            {props.paper.reading_status === 'reading_list' ? <Minus size={14} /> : <Plus size={14} />}
          </button>
        </div>
      </div>
      <h2>{props.paper.title}</h2>
      {props.paper.semantic_reason && <div className="semantic-reason">{props.paper.semantic_reason}</div>}
      <p>{props.paper.summary_snippet}</p>
      <ProjectDropdown
        paper={props.paper}
        folders={props.folders}
        compact
        onToggleFolder={props.onToggleFolder}
      />
      <div className="chips">
        {props.paper.folders.slice(0, 2).map((folder) => (
          <span className="chip project-chip removable" key={folder.id}>
            <Folder size={12} />
            {folder.name}
            <button
              className="chip-remove"
              onClick={(event) => {
                event.stopPropagation();
                props.onToggleFolder(props.paper.id, folder, false);
              }}
              aria-label={`Remove from ${folder.name}`}
              title={`Remove from ${folder.name}`}
            >
              <X size={10} />
            </button>
          </span>
        ))}
        {props.paper.tags.slice(0, 4).map((tag) => <span className="chip" key={tag}>{tag}</span>)}
      </div>
    </>
  );
}

export function PaperList(props: {
  loading: boolean;
  error: string | null;
  papers: Paper[];
  folders: PaperFolder[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRead: (id: string, read: boolean) => void;
  onReadingStatus: (id: string, status: ReadingStatus) => void;
  onToggleFolder: (id: string, folder: PaperFolder, inFolder: boolean) => void;
}) {
  if (props.loading && props.papers.length === 0) return <EmptyState title="Loading papers" body="Fetching local research data." />;
  if (props.error && props.papers.length === 0) return <EmptyState title="Could not load papers" body={props.error} />;
  if (props.papers.length === 0) return <EmptyState title="No matching papers" body="Adjust filters or search terms." />;

  const selectedPaper = props.selectedId ? props.papers.find((paper) => paper.id === props.selectedId) ?? null : null;
  const remainingPapers = selectedPaper ? props.papers.filter((paper) => paper.id !== selectedPaper.id) : props.papers;
  const orderedPapers = selectedPaper ? [selectedPaper, ...remainingPapers] : remainingPapers;

  return (
    <div className="paper-list-shell">
      {props.error && (
        <div className="paper-list-warning">
          Showing last loaded papers. Refresh failed: {props.error}
        </div>
      )}
      <div className="paper-list-scroll">
        <div className="paper-list">
          {orderedPapers.map((paper) => (
            <article
              key={paper.id}
              className={paper.id === selectedPaper?.id ? 'paper-card selected pinned' : 'paper-card'}
              onClick={() => props.onSelect(paper.id)}
              onKeyDown={(event) => activateCard(event, () => props.onSelect(paper.id))}
              role="button"
              tabIndex={0}
              aria-label={`Open ${paper.title}`}
            >
              <PaperCardBody
                paper={paper}
                folders={props.folders}
                onRead={props.onRead}
                onReadingStatus={props.onReadingStatus}
                onToggleFolder={props.onToggleFolder}
              />
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
