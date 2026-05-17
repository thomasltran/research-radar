import {
  BookOpen,
  Circle,
  GitBranch,
  Library,
  Moon,
  Network,
  Plus,
  RefreshCw,
  Sun,
} from 'lucide-react';

import type { PaperFolder, ReadFilter, Report, TagStat, Theme, View } from '../../types';
import type { NavCounts } from '../../state/paperViews';
import { NavButton } from '../ui/NavButton';
import { ProjectPanel } from './ProjectPanel';
import { GlobalFilterPanel } from './FilterPanel';

type Props = {
  view: View;
  navCounts: NavCounts;
  folders: PaperFolder[];
  selectedFolderId: number | null;
  newFolderName: string;
  tags: TagStat[];
  reports: Report[];
  selectedTags: string[];
  selectedReadFilter: ReadFilter;
  selectedRecommendation: string | null;
  selectedReportFilter: string | null;
  theme: Theme;
  isRefreshing: boolean;
  onChangeView: (view: View) => void;
  onSelectFolder: (folderId: number | null) => void;
  onSetNewFolderName: (name: string) => void;
  onCreateFolder: (event: React.FormEvent<HTMLFormElement>) => void;
  onDeleteFolder: (folderId: number) => void;
  onToggleTag: (tag: string) => void;
  onSetReadFilter: (filter: ReadFilter) => void;
  onSetRecommendation: (recommendation: string | null) => void;
  onSetReportFilter: (reportId: string | null) => void;
  onClearFilters: () => void;
  onToggleTheme: () => void;
  onRefresh: () => void;
};

export function AppSidebar(props: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <img src="/brand/research-radar-logo.png" alt="" />
        </div>
        <div>
          <strong>Research Radar</strong>
        </div>
      </div>
      <nav className="nav">
        <NavButton view="all" active={props.view} icon={<Library size={17} />} label="All Papers" count={props.navCounts.all} onClick={props.onChangeView} />
        <NavButton view="unread" active={props.view} icon={<Circle size={17} />} label="Unread" count={props.navCounts.unread} onClick={props.onChangeView} />
        <NavButton view="review" active={props.view} icon={<BookOpen size={17} />} label="Review" count={props.navCounts.review} onClick={props.onChangeView} />
        <NavButton view="reading-list" active={props.view} icon={<Plus size={17} />} label="Reading List" count={props.navCounts.readingList} onClick={props.onChangeView} />
        <NavButton view="reports" active={props.view} icon={<GitBranch size={17} />} label="Runs" count={props.navCounts.reports} onClick={props.onChangeView} />
        <NavButton view="graph" active={props.view} icon={<Network size={17} />} label="Graph" count={props.navCounts.graph} onClick={props.onChangeView} />
      </nav>
      <ProjectPanel
        folders={props.folders}
        selectedFolderId={props.selectedFolderId}
        newFolderName={props.newFolderName}
        onSelectFolder={props.onSelectFolder}
        onSetNewFolderName={props.onSetNewFolderName}
        onCreateFolder={props.onCreateFolder}
        onDeleteFolder={props.onDeleteFolder}
      />
      <GlobalFilterPanel
        tags={props.tags}
        reports={props.reports}
        selectedTags={props.selectedTags}
        selectedReadFilter={props.selectedReadFilter}
        selectedRecommendation={props.selectedRecommendation}
        selectedReportFilter={props.selectedReportFilter}
        onToggleTag={props.onToggleTag}
        onSetReadFilter={props.onSetReadFilter}
        onSetRecommendation={props.onSetRecommendation}
        onSetReport={props.onSetReportFilter}
        onClear={props.onClearFilters}
      />
      <div className="sidebar-footer-actions">
        <button
          className="ghost-button icon-button"
          onClick={props.onToggleTheme}
          title={props.theme === 'dark' ? 'Light mode' : 'Dark mode'}
          aria-label={props.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {props.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          className={props.isRefreshing ? 'ghost-button icon-button refreshing' : 'ghost-button icon-button'}
          onClick={props.onRefresh}
          title="Refresh"
          aria-label="Refresh"
        >
          <RefreshCw size={16} />
        </button>
      </div>
    </aside>
  );
}
