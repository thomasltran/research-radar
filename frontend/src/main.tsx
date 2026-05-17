import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

import type {
  View, Theme, SortMode, ReadFilter, ReadingStatus,
  PipelineSource, ReportMode, MaintenanceMode,
  Paper, PaperDetail, PaperFolder, Report, ReportDetail,
  TagStat, PipelinePreview, PipelineSchedule, PipelineLogs,
  WorkspaceStats, PruneAction, GraphPayload,
} from './types';
import { fetchJson, sortPapers } from './api';
import { useAsync } from './hooks/useAsync';
import { toDateTimeLocalValue, dateTimeLocalToIso, errorMessage } from './utils';
import { buildPaperCountPath, buildPaperPath, filterPapersByTags, getNavCounts, paperMatchesViewState } from './state/paperViews';
import { countVisibleGraphPapers } from './state/graphFilters';
import { ConfirmModal } from './components/ui/ConfirmModal';
import { EmptyState } from './components/ui/EmptyState';
import { AppSidebar } from './components/layout/AppSidebar';
import { WorkspaceToolbar } from './components/layout/WorkspaceToolbar';
import { PaperList } from './components/papers/PaperList';
import { PaperDetailPanel } from './components/papers/PaperDetail';
import { ReportList, ReportDetailPanel } from './components/reports/ReportList';
import { GraphView } from './components/graph/GraphView';


function App() {
  const [view, setView] = useState<View>('all');
  const [query, setQuery] = useState('');
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [paperSelectionCleared, setPaperSelectionCleared] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [reportSelectionCleared, setReportSelectionCleared] = useState(false);
  const [reportMode, setReportMode] = useState<ReportMode>('intake');
  const [maintenanceMode, setMaintenanceMode] = useState<MaintenanceMode>('relink');
  const [selectedReportFilter, setSelectedReportFilter] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [selectedRecommendation, setSelectedRecommendation] = useState<string | null>(null);
  const [selectedReadFilter, setSelectedReadFilter] = useState<ReadFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('relevance');
  const [pipelineSources, setPipelineSources] = useState<PipelineSource[]>(['semantic_scholar', 'arxiv']);
  const [scanStartInput, setScanStartInput] = useState('');
  const [scanEndInput, setScanEndInput] = useState('');
  const [scanStartDirty, setScanStartDirty] = useState(false);
  const [scanEndDirty, setScanEndDirty] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleTime, setScheduleTime] = useState('09:00');
  const [scheduleDirty, setScheduleDirty] = useState(false);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [previewNow, setPreviewNow] = useState(() => new Date());
  const [refreshKey, setRefreshKey] = useState(0);
  const [reportRefreshKey, setReportRefreshKey] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isStartingPipeline, setIsStartingPipeline] = useState(false);
  const [isMaintaining, setIsMaintaining] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [showSemanticRelinkPrompt, setShowSemanticRelinkPrompt] = useState(false);
  const [semanticRelinkDismissedKey, setSemanticRelinkDismissedKey] = useState('');
  const [isDetailCollapsed, setIsDetailCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => {
    return window.localStorage.getItem('research-theme') === 'dark' ? 'dark' : 'light';
  });
  const hadRunningJobRef = useRef(false);

  const paperQueryState = useMemo(() => ({
    query,
    selectedReportFilter,
    selectedFolderId,
    selectedReadFilter,
    selectedRecommendation,
    sortMode,
    view,
  }), [query, selectedFolderId, selectedReadFilter, selectedRecommendation, selectedReportFilter, sortMode, view]);

  const paperPath = useMemo(() => buildPaperPath(paperQueryState), [paperQueryState]);
  const countPath = useMemo(() => buildPaperCountPath(paperQueryState), [paperQueryState]);

  const papers = useAsync<{ papers: Paper[] }>(() => fetchJson(paperPath), [paperPath, refreshKey]);
  const countPapers = useAsync<{ papers: Paper[] }>(() => fetchJson(countPath), [countPath, refreshKey]);
  const reports = useAsync<{ runs: Report[] }>(() => fetchJson('/api/runs'), [refreshKey, reportRefreshKey]);
  const stats = useAsync<WorkspaceStats>(() => fetchJson('/api/stats'), [refreshKey, reportRefreshKey]);
  const pruneActions = useAsync<{ actions: PruneAction[] }>(() => fetchJson('/api/prune-actions?status=pending&limit=5'), [refreshKey, reportRefreshKey]);
  const folders = useAsync<{ folders: PaperFolder[] }>(() => fetchJson('/api/folders'), [refreshKey]);
  const pipelineSourceMode = pipelineSources.length === 2 ? 'both' : pipelineSources[0];
  const pipelinePreview = useAsync<PipelinePreview>(() => fetchJson(`/api/pipeline/preview?source_mode=${pipelineSourceMode}`), [pipelineSourceMode, refreshKey, reportRefreshKey]);
  const tags = useAsync<{ tags: TagStat[] }>(() => fetchJson('/api/tags'), [refreshKey]);
  const graph = useAsync<GraphPayload>(() => fetchJson('/api/graph'), [refreshKey]);

  const selectedPaper = useAsync<PaperDetail | null>(
    () => selectedPaperId ? fetchJson(`/api/papers/${selectedPaperId}`) : Promise.resolve(null),
    [selectedPaperId, refreshKey],
  );

  const selectedReport = useAsync<ReportDetail | null>(
    () => selectedReportId ? fetchJson(`/api/runs/${selectedReportId}`) : Promise.resolve(null),
    [selectedReportId, refreshKey, reportRefreshKey],
  );

  const selectedReportLogs = useAsync<PipelineLogs>(
    () => selectedReportId
      ? fetchJson(`/api/pipeline/runs/${selectedReportId}/logs`, { timeoutMs: 5000 })
      : Promise.resolve({ run_id: 0, log: '', exists: false }),
    [selectedReportId, refreshKey, reportRefreshKey],
  );

  const visiblePapers = useMemo(() => {
    const raw = papers.data?.papers ?? [];
    const filtered = filterPapersByTags(raw, selectedTags)
      .filter((paper) => paperMatchesViewState(paper, paperQueryState));
    return sortPapers(filtered, sortMode, Boolean(query.trim() && sortMode === 'relevance'));
  }, [paperQueryState, papers.data, query, selectedTags, sortMode]);

  const semanticUnavailable = Boolean(
    query.trim() && (papers.data?.papers ?? []).some((paper) => paper.semantic_unavailable),
  );
  const semanticPromptKey = `${query.trim()}|${selectedFolderId ?? ''}|${selectedReportFilter ?? ''}`;

  const countBasePapers = useMemo(() => {
    return filterPapersByTags(countPapers.data?.papers ?? [], selectedTags);
  }, [countPapers.data, selectedTags]);

  const currentSelectedReport = useMemo(() => {
    if (!selectedReportId || !selectedReport.data) return null;
    return String(selectedReport.data.report.id) === selectedReportId ? selectedReport.data : null;
  }, [selectedReport.data, selectedReportId]);

  const currentSelectedPaper = useMemo(() => {
    if (!selectedPaperId || !selectedPaper.data) return null;
    return selectedPaper.data.id === selectedPaperId ? selectedPaper.data : null;
  }, [selectedPaper.data, selectedPaperId]);

  const currentSelectedReportLogs = useMemo(() => {
    if (!selectedReportId || !selectedReportLogs.data) return null;
    return String(selectedReportLogs.data.run_id) === selectedReportId ? selectedReportLogs.data : null;
  }, [selectedReportId, selectedReportLogs.data]);

  const graphCount = useMemo(() => countVisibleGraphPapers(graph.data, {
    selectedTags,
    selectedReportFilter,
    selectedRecommendation,
    selectedReadFilter,
  }), [graph.data, selectedReadFilter, selectedRecommendation, selectedReportFilter, selectedTags]);

  const navCounts = useMemo(
    () => getNavCounts(countBasePapers, (reports.data?.runs ?? []).length, graphCount),
    [countBasePapers, graphCount, reports.data],
  );

  useEffect(() => {
    if (!selectedPaperId && !paperSelectionCleared && visiblePapers.length > 0 && !['reports', 'graph'].includes(view)) {
      setSelectedPaperId(visiblePapers[0].id);
    }
  }, [paperSelectionCleared, selectedPaperId, visiblePapers, view]);

  useEffect(() => {
    if (semanticUnavailable && semanticPromptKey !== semanticRelinkDismissedKey) {
      setShowSemanticRelinkPrompt(true);
    }
  }, [semanticPromptKey, semanticRelinkDismissedKey, semanticUnavailable]);

  useEffect(() => {
    if (view !== 'reports') return;
    const available = reports.data?.runs ?? [];
    if (!available.length) return;
    const modeReports = reportMode === 'maintenance'
      ? available.filter((report) => report.run_type === maintenanceMode)
      : available.filter((report) => (report.run_type !== 'relink' && report.run_type !== 'reanalyze' && report.run_type !== 'bootstrap'));
    const preferred = modeReports.find((report) => (report.ingested_count ?? 0) > 0 || report.run_type === maintenanceMode) ?? modeReports[0] ?? available[0];
    if (!selectedReportId && !reportSelectionCleared) {
      setSelectedReportId(String(preferred.id));
    }
  }, [view, reports.data, selectedReportId, reportMode, maintenanceMode, reportSelectionCleared]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem('research-theme', theme);
  }, [theme]);

  useEffect(() => {
    const timer = window.setInterval(() => setPreviewNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!pipelinePreview.data) return;
    if (!scanStartDirty) setScanStartInput(toDateTimeLocalValue(pipelinePreview.data.scan_since));
  }, [pipelinePreview.data, scanStartDirty]);

  useEffect(() => {
    if (!scanEndDirty) setScanEndInput(toDateTimeLocalValue(previewNow.toISOString()));
  }, [previewNow, scanEndDirty]);

  useEffect(() => {
    if (!pipelinePreview.data?.schedule || scheduleDirty) return;
    setScheduleEnabled(Boolean(pipelinePreview.data.schedule.enabled));
    setScheduleTime(pipelinePreview.data.schedule.time || '09:00');
  }, [pipelinePreview.data?.schedule]);

  useEffect(() => {
    const hasRunningReport = (reports.data?.runs ?? []).some((report) => report.status === 'running');
    if (hadRunningJobRef.current && !hasRunningReport) {
      setRefreshKey((key) => key + 1);
    }
    hadRunningJobRef.current = hasRunningReport;
    if (!hasRunningReport) return;
    const timer = window.setInterval(() => setReportRefreshKey((key) => key + 1), 2500);
    return () => window.clearInterval(timer);
  }, [reports.data]);

  useEffect(() => {
    if (!scheduleDirty) return;
    const timer = window.setTimeout(() => {
      saveSchedule(scheduleEnabled, scheduleTime, pipelineSourceMode);
    }, 650);
    return () => window.clearTimeout(timer);
  }, [scheduleDirty, scheduleEnabled, scheduleTime, pipelineSourceMode]);

  function changeView(next: View) {
    setView(next);
    if (next === 'reports') {
      setReportSelectionCleared(false);
      setSelectedReportId(null);
    }
    setSelectedFolderId(null);
  }

  function selectFolder(folderId: number | null) {
    setSelectedFolderId(folderId);
    setView('all');
  }

  function toggleTag(tag: string) {
    setSelectedTags((current) => (
      current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]
    ));
  }

  function openPaperFromGraph(paperId: string) {
    setPaperSelectionCleared(false);
    setIsDetailCollapsed(false);
    setSelectedPaperId(paperId);
  }

  function deselectPaper() {
    setPaperSelectionCleared(true);
    setSelectedPaperId(null);
  }

  function findCachedPaper(paperId: string): Paper | null {
    if (selectedPaper.data?.id === paperId) return selectedPaper.data;
    return papers.data?.papers.find((paper) => paper.id === paperId)
      ?? countPapers.data?.papers.find((paper) => paper.id === paperId)
      ?? null;
  }

  function closeActiveDetail() {
    if (view === 'reports') {
      setReportSelectionCleared(true);
      setSelectedReportId(null);
      return;
    }
    deselectPaper();
  }

  function selectPaper(paperId: string) {
    setPaperSelectionCleared(false);
    setIsDetailCollapsed(false);
    setSelectedPaperId(paperId);
  }

  function refresh() {
    setIsRefreshing(true);
    setRefreshKey((key) => key + 1);
    setReportRefreshKey((key) => key + 1);
    window.setTimeout(() => setIsRefreshing(false), 650);
  }

  async function setRead(paperId: string, read: boolean) {
    updatePaperCaches(paperId, { read });
    try {
      await fetchJson(`/api/papers/${paperId}/read`, {
        method: 'PATCH',
        body: JSON.stringify({ read }),
      });
    } catch (error) {
      updatePaperCaches(paperId, { read: !read });
      setPipelineError(errorMessage(error));
    }
  }

  async function setReadingStatus(paperId: string, readingStatus: ReadingStatus) {
    const previous = findCachedPaper(paperId)?.reading_status ?? '';
    updatePaperCaches(paperId, { reading_status: readingStatus });
    try {
      await fetchJson(`/api/papers/${paperId}/reading-status`, {
        method: 'PATCH',
        body: JSON.stringify({ reading_status: readingStatus }),
      });
    } catch (error) {
      updatePaperCaches(paperId, { reading_status: previous });
      setPipelineError(errorMessage(error));
    }
  }

  async function createFolder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newFolderName.trim();
    if (!name) return;
    setPipelineError(null);
    try {
      const result = await fetchJson<{ folder: PaperFolder }>('/api/folders', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });
      setNewFolderName('');
      setSelectedFolderId(result.folder.id);
      setView('all');
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    }
  }

  async function deleteFolder(folderId: number) {
    setPipelineError(null);
    try {
      await fetchJson(`/api/folders/${folderId}`, { method: 'DELETE' });
      if (selectedFolderId === folderId) setSelectedFolderId(null);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    }
  }

  async function togglePaperFolder(paperId: string, folder: PaperFolder, inFolder: boolean) {
    const patchFolders = (currentFolders: PaperFolder[] = []) => {
      if (inFolder) {
        return currentFolders.some((item) => item.id === folder.id) ? currentFolders : [...currentFolders, folder];
      }
      return currentFolders.filter((item) => item.id !== folder.id);
    };
    const applyFolders = <T extends Paper>(paper: T): T => (
      paper.id === paperId ? { ...paper, folders: patchFolders(paper.folders) } : paper
    );
    papers.setData((current) => current ? { papers: current.papers.map(applyFolders) } : current);
    countPapers.setData((current) => current ? { papers: current.papers.map(applyFolders) } : current);
    selectedPaper.setData((current) => current && current.id === paperId ? { ...current, folders: patchFolders(current.folders) } : current);
    setPipelineError(null);
    try {
      await fetchJson(`/api/folders/${folder.id}/papers/${paperId}`, {
        method: 'PUT',
        body: JSON.stringify({ in_folder: inFolder }),
      });
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setRefreshKey((key) => key + 1);
      setPipelineError(errorMessage(error));
    }
  }

  function updatePaperCaches(paperId: string, patch: Partial<Paper>) {
    const applyPatch = <T extends Paper>(paper: T): T => paper.id === paperId ? { ...paper, ...patch } : paper;
    papers.setData((current) => current ? { papers: current.papers.map(applyPatch) } : current);
    countPapers.setData((current) => current ? { papers: current.papers.map(applyPatch) } : current);
    selectedPaper.setData((current) => current && current.id === paperId ? { ...current, ...patch } : current);
  }

  async function startPipeline() {
    setIsStartingPipeline(true);
    setPipelineError(null);
    try {
      const result = await fetchJson<{ run_id: number }>('/api/pipeline/run', {
        method: 'POST',
        body: JSON.stringify({
          run_type: 'manual',
          source_mode: pipelineSourceMode,
          scan_start: dateTimeLocalToIso(scanStartInput),
          scan_end: scanEndDirty ? dateTimeLocalToIso(scanEndInput) : previewNow.toISOString(),
        }),
      });
      setView('reports');
      setReportMode('intake');
      setReportSelectionCleared(false);
      setSelectedReportId(String(result.run_id));
      setReportRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    } finally {
      setIsStartingPipeline(false);
    }
  }

  async function cancelPipeline(runId: number) {
    setPipelineError(null);
    try {
      await fetchJson(`/api/pipeline/runs/${runId}/cancel`, { method: 'POST' });
      setReportRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    }
  }

  async function saveSchedule(enabled = scheduleEnabled, time = scheduleTime, sourceMode = pipelineSourceMode) {
    setIsSavingSchedule(true);
    setPipelineError(null);
    try {
      const result = await fetchJson<{ schedule: PipelineSchedule }>('/api/pipeline/schedule', {
        method: 'PUT',
        body: JSON.stringify({
          enabled,
          time,
          source_mode: sourceMode,
        }),
      });
      setScheduleEnabled(Boolean(result.schedule.enabled));
      setScheduleTime(result.schedule.time || '09:00');
      setScheduleDirty(false);
    } catch (error) {
      setPipelineError(errorMessage(error));
    } finally {
      setIsSavingSchedule(false);
    }
  }

  async function runMaintenance(mode: MaintenanceMode = maintenanceMode) {
    setIsMaintaining(true);
    setPipelineError(null);
    try {
      const endpoint = mode === 'bootstrap' ? '/api/workspace/bootstrap' : '/api/workspace/maintenance';
      const body = mode === 'bootstrap' ? undefined : JSON.stringify({ mode });
      const result = await fetchJson<{ run_id: number }>(endpoint, {
        method: 'POST',
        body,
      });
      setView('reports');
      setReportMode('maintenance');
      setReportSelectionCleared(false);
      setSelectedReportId(String(result.run_id));
      setReportRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    } finally {
      setIsMaintaining(false);
    }
  }

  function relinkWorkspace() {
    runMaintenance('relink');
  }

  async function updatePruneAction(actionId: number, status: 'applied' | 'kept') {
    setPipelineError(null);
    try {
      await fetchJson(`/api/prune-actions/${actionId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setPipelineError(errorMessage(error));
    }
  }

  return (
    <div className="app-shell">
      {showSemanticRelinkPrompt && semanticUnavailable && (
        <ConfirmModal
          title="Rebuild semantic search?"
          body="Semantic search fell back to text search because the library index is unavailable. Relink will rebuild the library index in the background."
          confirmLabel={isMaintaining ? 'Starting' : 'Relink'}
          onCancel={() => {
            setSemanticRelinkDismissedKey(semanticPromptKey);
            setShowSemanticRelinkPrompt(false);
          }}
          onConfirm={() => {
            setSemanticRelinkDismissedKey(semanticPromptKey);
            setShowSemanticRelinkPrompt(false);
            relinkWorkspace();
          }}
        />
      )}
      <AppSidebar
        view={view}
        navCounts={navCounts}
        folders={folders.data?.folders ?? []}
        selectedFolderId={selectedFolderId}
        newFolderName={newFolderName}
        tags={tags.data?.tags ?? []}
        reports={reports.data?.runs ?? []}
        selectedTags={selectedTags}
        selectedReadFilter={selectedReadFilter}
        selectedRecommendation={selectedRecommendation}
        selectedReportFilter={selectedReportFilter}
        theme={theme}
        isRefreshing={isRefreshing}
        onChangeView={changeView}
        onSelectFolder={selectFolder}
        onSetNewFolderName={setNewFolderName}
        onCreateFolder={createFolder}
        onDeleteFolder={deleteFolder}
        onToggleTag={toggleTag}
        onSetReadFilter={setSelectedReadFilter}
        onSetRecommendation={setSelectedRecommendation}
        onSetReportFilter={setSelectedReportFilter}
        onClearFilters={() => {
          setSelectedTags([]);
          setSelectedReadFilter('all');
          setSelectedRecommendation(null);
          setSelectedReportFilter(null);
        }}
        onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        onRefresh={refresh}
      />

      <main className="workspace">
        <WorkspaceToolbar
          view={view}
          query={query}
          visiblePaperCount={visiblePapers.length}
          sortMode={sortMode}
          isDetailCollapsed={isDetailCollapsed}
          hasSelectedPaper={Boolean(selectedPaperId)}
          hasSelectedReport={Boolean(selectedReportId)}
          onSetQuery={setQuery}
          onSetSortMode={setSortMode}
          onToggleDetail={() => setIsDetailCollapsed((value) => !value)}
          onCloseActiveDetail={closeActiveDetail}
        />

        <section className={isDetailCollapsed ? 'content-grid detail-collapsed' : 'content-grid'}>
          <section className="list-pane">
            {view === 'reports' && (
              <ReportList
                reports={reports.data?.runs ?? []}
                selected={selectedReportId}
                mode={reportMode}
                onModeChange={(mode) => {
                  setReportSelectionCleared(false);
                  setReportMode(mode);
                }}
                onSelect={(id) => {
                  setIsDetailCollapsed(false);
                  setReportSelectionCleared(id === null);
                  setSelectedReportId(id === null ? null : String(id));
                }}
                preview={pipelinePreview.data}
                onRun={startPipeline}
                onCancel={cancelPipeline}
                onRunMaintenance={runMaintenance}
                isStarting={isStartingPipeline}
                isMaintaining={isMaintaining}
                error={pipelineError}
                stats={stats.data}
                pruneActions={pruneActions.data?.actions ?? []}
                maintenanceMode={maintenanceMode}
                onMaintenanceModeChange={setMaintenanceMode}
                sources={pipelineSources}
                previewNow={previewNow}
                scanStart={scanStartInput}
                scanEnd={scanEndInput}
                scheduleEnabled={scheduleEnabled}
                scheduleTime={scheduleTime}
                onSetScanStart={(value) => {
                  setScanStartDirty(true);
                  setScanStartInput(value);
                }}
                onSetScanEnd={(value) => {
                  setScanEndDirty(true);
                  setScanEndInput(value);
                }}
                onSetScheduleEnabled={(enabled) => {
                  setScheduleEnabled(enabled);
                  setScheduleDirty(true);
                }}
                onSetScheduleTime={(time) => {
                  setScheduleTime(time);
                  setScheduleDirty(true);
                }}
                onPruneAction={updatePruneAction}
                onToggleSource={(source) => {
                  setPipelineSources((current) => {
                    if (current.includes(source)) {
                      return current.length === 1 ? current : current.filter((item) => item !== source);
                    }
                    return [...current, source];
                  });
                  if (scheduleEnabled) setScheduleDirty(true);
                }}
              />
            )}
            {view === 'graph' && (
              <GraphView
                graph={graph.data}
                selectedPaperId={selectedPaperId}
                selectedTags={selectedTags}
                selectedReportFilter={selectedReportFilter}
                selectedRecommendation={selectedRecommendation}
                selectedReadFilter={selectedReadFilter}
                onToggleTag={toggleTag}
                onOpenPaper={openPaperFromGraph}
                onDeselectPaper={deselectPaper}
                onClearTags={() => setSelectedTags([])}
              />
            )}
            {!['reports', 'graph'].includes(view) && (
              <PaperList
                loading={papers.loading}
                error={papers.error}
                papers={visiblePapers}
                folders={folders.data?.folders ?? []}
                selectedId={selectedPaperId}
                onSelect={selectPaper}
                onRead={setRead}
                onReadingStatus={setReadingStatus}
                onToggleFolder={togglePaperFolder}
              />
            )}
          </section>

          {!isDetailCollapsed && (
            <aside className="detail-pane">
              {view === 'reports' ? (
                <ReportDetailPanel
                  detail={currentSelectedReport}
                  logs={currentSelectedReportLogs}
                  loading={Boolean(selectedReportId && selectedReport.loading && !currentSelectedReport)}
                  onCancel={cancelPipeline}
                  onSelectPaper={(id) => {
                    setPaperSelectionCleared(false);
                    setIsDetailCollapsed(false);
                    setSelectedPaperId(id);
                    setView('all');
                  }}
                />
              ) : currentSelectedPaper ? (
                <PaperDetailPanel
                  paper={currentSelectedPaper}
                  folders={folders.data?.folders ?? []}
                  onRead={setRead}
                  onReadingStatus={setReadingStatus}
                  onToggleFolder={togglePaperFolder}
                  onOpenPaper={selectPaper}
                  onSaved={() => setRefreshKey((key) => key + 1)}
                />
              ) : selectedPaperId && selectedPaper.loading ? (
                <EmptyState title="Loading paper" body="Fetching the selected paper." />
              ) : (
                <EmptyState title="No paper selected" body="Select a paper to inspect its analysis and notes." />
              )}
            </aside>
          )}
        </section>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
