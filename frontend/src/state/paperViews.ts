import type { Paper, ReadFilter, SortMode, View } from '../types';

export type PaperQueryState = {
  query: string;
  selectedReportFilter: string | null;
  selectedFolderId: number | null;
  selectedReadFilter: ReadFilter;
  selectedRecommendation: string | null;
  sortMode: SortMode;
  view: View;
};

export type NavCounts = {
  all: number;
  unread: number;
  review: number;
  readingList: number;
  reports: number;
  graph: number;
};

function appendSharedPaperParams(params: URLSearchParams, state: PaperQueryState) {
  if (state.query) params.set('q', state.query);
  if (state.query) params.set('semantic', 'true');
  if (state.selectedReportFilter) params.set('run_id', state.selectedReportFilter);
  if (state.selectedFolderId !== null) params.set('folder_id', String(state.selectedFolderId));
}

export function buildPaperPath(state: PaperQueryState): string {
  const params = new URLSearchParams();
  appendSharedPaperParams(params, state);
  if (state.view === 'review') {
    params.set('recommendation', 'read');
    params.set('read', 'false');
  } else {
    if (state.view === 'reading-list') params.set('reading_status', 'reading_list');
    if (state.view === 'unread') {
      params.set('read', 'false');
    } else if (state.selectedReadFilter !== 'all') {
      params.set('read', state.selectedReadFilter === 'read' ? 'true' : 'false');
    }
    if (state.selectedRecommendation) params.set('recommendation', state.selectedRecommendation);
  }
  params.set('sort', state.sortMode);
  return `/api/papers?${params.toString()}`;
}

export function buildPaperCountPath(state: PaperQueryState): string {
  const params = new URLSearchParams();
  appendSharedPaperParams(params, state);
  params.set('sort', 'relevance');
  return `/api/papers?${params.toString()}`;
}

export function filterPapersByTags(papers: Paper[], selectedTags: string[]): Paper[] {
  if (selectedTags.length === 0) return papers;
  return papers.filter((paper) => selectedTags.every((tag) => paper.tags.includes(tag)));
}

export function paperMatchesViewState(paper: Paper, state: PaperQueryState): boolean {
  if (state.view === 'review') {
    return !paper.read && paper.recommendation === 'read';
  }
  if (state.view === 'unread' && paper.read) return false;
  if (state.view === 'reading-list' && paper.reading_status !== 'reading_list') return false;
  if (state.view !== 'unread' && state.selectedReadFilter !== 'all') {
    if (state.selectedReadFilter === 'read' && !paper.read) return false;
    if (state.selectedReadFilter === 'unread' && paper.read) return false;
  }
  if (state.selectedRecommendation && paper.recommendation !== state.selectedRecommendation) return false;
  return true;
}

export function getNavCounts(papers: Paper[], reportCount: number, graphCount: number): NavCounts {
  return {
    all: papers.length,
    unread: papers.filter((paper) => !paper.read).length,
    review: papers.filter((paper) => (
      !paper.read
      && paper.recommendation === 'read'
    )).length,
    readingList: papers.filter((paper) => paper.reading_status === 'reading_list').length,
    reports: reportCount,
    graph: graphCount,
  };
}
