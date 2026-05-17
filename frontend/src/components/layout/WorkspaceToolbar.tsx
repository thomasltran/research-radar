import { PanelRightClose, PanelRightOpen, Search, X } from 'lucide-react';

import { SORT_OPTIONS } from '../../api';
import type { SortMode, View } from '../../types';

type Props = {
  view: View;
  query: string;
  visiblePaperCount: number;
  sortMode: SortMode;
  isDetailCollapsed: boolean;
  hasSelectedPaper: boolean;
  hasSelectedReport: boolean;
  onSetQuery: (query: string) => void;
  onSetSortMode: (mode: SortMode) => void;
  onToggleDetail: () => void;
  onCloseActiveDetail: () => void;
};

export function WorkspaceToolbar(props: Props) {
  const searchView = !['reports', 'graph'].includes(props.view);
  const canCloseDetail = (props.view === 'reports' && props.hasSelectedReport)
    || (props.view !== 'reports' && props.hasSelectedPaper);

  return (
    <header className="toolbar">
      <div className="toolbar-left">
        <div className="search">
          <Search size={17} />
          <input
            value={props.query}
            onChange={(event) => props.onSetQuery(event.target.value)}
            placeholder="Search papers, abstracts, tags"
          />
        </div>
        {props.query && searchView && (
          <span className="search-result-count" title="Search results">
            {props.visiblePaperCount} {props.visiblePaperCount === 1 ? 'result' : 'results'} found
          </span>
        )}
        {searchView && (
          <label className="sort-control toolbar-sort">
            <span>Sort</span>
            <select value={props.sortMode} onChange={(event) => props.onSetSortMode(event.target.value as SortMode)}>
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="toolbar-actions">
        <button
          className="ghost-button icon-button pane-toggle"
          onClick={props.onToggleDetail}
          title={props.isDetailCollapsed ? 'Show detail' : 'Hide detail'}
          aria-label={props.isDetailCollapsed ? 'Show detail' : 'Hide detail'}
        >
          {props.isDetailCollapsed ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
        </button>
        {canCloseDetail && (
          <button
            className="ghost-button icon-button deselect-paper-button"
            onClick={props.onCloseActiveDetail}
            title={props.view === 'reports' ? 'Close report' : 'Deselect paper'}
            aria-label={props.view === 'reports' ? 'Close report' : 'Deselect paper'}
          >
            <X size={16} />
          </button>
        )}
      </div>
    </header>
  );
}
