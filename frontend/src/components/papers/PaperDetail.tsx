import React, { useEffect, useState } from 'react';
import { Download, ExternalLink, Eye, EyeOff, Folder, Minus, Plus, Save, X } from 'lucide-react';
import type { PaperDetail, PaperFolder, ReadingStatus } from '../../types';
import { API, fetchJson } from '../../api';
import { recommendationLabel } from '../../utils';
import { Section, ListSection, RelationBlock, MarkdownInlineBlock } from '../ui/Markdown';
import { ProjectDropdown } from './PaperList';

function NotesEditor(props: { paperId: string; notePath?: string; onSaved: () => void }) {
  const [notes, setNotes] = useState('');
  const [initial, setInitial] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    let alive = true;
    fetchJson<{ notes: string }>(`/api/papers/${props.paperId}/notes`)
      .then((data) => {
        if (!alive) return;
        setNotes(data.notes);
        setInitial(data.notes);
        setStatus('idle');
      })
      .catch(() => {
        if (alive) setStatus('error');
      });
    return () => {
      alive = false;
    };
  }, [props.paperId]);

  async function save() {
    setStatus('saving');
    try {
      await fetchJson(`/api/papers/${props.paperId}/notes`, {
        method: 'PUT',
        body: JSON.stringify({ notes }),
      });
      setInitial(notes);
      setStatus('saved');
      props.onSaved();
    } catch {
      setStatus('error');
    }
  }

  const dirty = notes !== initial;
  return (
    <section className="section notes">
      <div className="section-heading">
        <h2>My Notes</h2>
        <button className="save-button" disabled={!dirty || status === 'saving'} onClick={(event) => {
          event.preventDefault();
          save();
        }}>
          <Save size={16} /> {status === 'saving' ? 'Saving' : dirty ? 'Save' : 'Saved'}
        </button>
      </div>
      <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add local Markdown notes." />
      {props.notePath && <div className="path-label">{props.notePath}</div>}
      {status === 'error' && <div className="error-text">Could not save notes.</div>}
    </section>
  );
}

export function PaperDetailPanel(props: {
  paper: PaperDetail;
  folders: PaperFolder[];
  onRead: (id: string, read: boolean) => void;
  onReadingStatus: (id: string, status: ReadingStatus) => void;
  onToggleFolder: (id: string, folder: PaperFolder, inFolder: boolean) => void;
  onOpenPaper: (id: string) => void;
  onSaved: () => void;
}) {
  return (
    <div className="detail-scroll">
      <div className="detail-header">
          <div>
            <span className="eyebrow">{props.paper.source ?? 'paper'} {props.paper.published_date ? `· ${props.paper.published_date}` : ''}</span>
            <h1>{props.paper.title}</h1>
            <p>{props.paper.authors.join(', ')}</p>
            <div className="detail-meta-chips">
              <span className="score">{props.paper.relevance_score ?? '?'}</span>
              {props.paper.recommendation && <span className={`chip intent ${props.paper.recommendation}`}>{recommendationLabel(props.paper.recommendation)}</span>}
              <span className={props.paper.read ? 'chip status read' : 'chip status unread'}>{props.paper.read ? 'Read' : 'Unread'}</span>
            {props.paper.tags.slice(0, 5).map((tag) => <span className="chip" key={tag}>{tag}</span>)}
          </div>
        </div>
        <div className="detail-actions">
          <ProjectDropdown paper={props.paper} folders={props.folders} onToggleFolder={props.onToggleFolder} />
          <button
            className="ghost-button icon-button subtle-action"
            onClick={() => props.onRead(props.paper.id, !props.paper.read)}
            title={props.paper.read ? 'Mark unread' : 'Mark read'}
            aria-label={props.paper.read ? 'Mark unread' : 'Mark read'}
            aria-pressed={props.paper.read}
          >
            {props.paper.read ? <Eye size={16} /> : <EyeOff size={16} />}
          </button>
          <button
            className={props.paper.reading_status === 'reading_list' ? 'ghost-button icon-button subtle-action reading-list-action active' : 'ghost-button icon-button subtle-action reading-list-action'}
            onClick={() => props.onReadingStatus(props.paper.id, props.paper.reading_status === 'reading_list' ? '' : 'reading_list')}
            aria-pressed={props.paper.reading_status === 'reading_list'}
            aria-label={props.paper.reading_status === 'reading_list' ? 'Remove from reading list' : 'Add to reading list'}
            title={props.paper.reading_status === 'reading_list' ? 'Remove from reading list' : 'Add to reading list'}
          >
            {props.paper.reading_status === 'reading_list' ? <Minus size={16} /> : <Plus size={16} />}
          </button>
          {props.paper.url && (
            <a className="ghost-button icon-button" href={props.paper.url} target="_blank" rel="noreferrer" title="Open source" aria-label="Open source">
              <ExternalLink size={16} />
            </a>
          )}
          <a className="ghost-button icon-button" href={`${API}/api/papers/${props.paper.id}/note-file`} target="_blank" rel="noreferrer" title="Download note" aria-label="Download note">
            <Download size={16} />
          </a>
        </div>
      </div>

      <Section title="Summary">{props.paper.analysis?.summary ?? props.paper.summary ?? 'No generated summary available.'}</Section>
      <ListSection title="Key Contributions" items={props.paper.analysis?.key_contributions ?? props.paper.summary_detail?.contributions ?? []} />
      <Section title="Method">{props.paper.summary_detail?.method ?? 'No method summary available.'}</Section>
      <Section title="Novelty">{props.paper.analysis?.novelty_explanation ?? 'No novelty assessment available.'}</Section>
      <Section title="Relation To Research">{props.paper.analysis?.relation_to_research ?? 'No relation analysis available.'}</Section>
      <section className="section">
        <h2>Projects</h2>
        <div className="folder-picker dropdown-mode">
          <div className="chips">
            {props.paper.folders.length === 0 ? (
              <span className="chip">No projects</span>
            ) : props.paper.folders.map((folder) => (
              <span className="chip project-chip removable" key={folder.id}>
                <Folder size={12} />
                {folder.name}
                <button
                  className="chip-remove"
                  onClick={() => props.onToggleFolder(props.paper.id, folder, false)}
                  aria-label={`Remove from ${folder.name}`}
                  title={`Remove from ${folder.name}`}
                >
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        </div>
      </section>
      <RelationBlock related={props.paper.related_papers ?? []} onOpenPaper={props.onOpenPaper} />
      {props.paper.verification && !props.paper.verification.verified && (
        <ListSection title="Verification Issues" items={props.paper.verification.issues.map((issue) => `${issue.problem ?? 'Issue'}: ${issue.detail ?? issue.claim ?? ''}`)} />
      )}
      <Section title="Abstract">{props.paper.abstract ?? 'No abstract available.'}</Section>
      <NotesEditor paperId={props.paper.id} onSaved={props.onSaved} notePath={props.paper.note?.path} />
    </div>
  );
}
