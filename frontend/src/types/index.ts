export type View = 'all' | 'unread' | 'review' | 'reading-list' | 'reports' | 'graph';
export type Theme = 'dark' | 'light';
export type SortMode = 'relevance' | 'title' | 'published' | 'new' | 'unread';
export type ReadFilter = 'all' | 'unread' | 'read';
export type ReadingStatus = '' | 'reading_list' | 'currently_reading';
export type PipelineSource = 'arxiv' | 'semantic_scholar';
export type ReportMode = 'intake' | 'maintenance';
export type MaintenanceMode = 'relink' | 'reanalyze' | 'bootstrap';

export type Paper = {
  id: string;
  title: string;
  authors: string[];
  source?: string;
  run_type?: string | null;
  url?: string;
  published_date?: string;
  ingested_at?: string;
  relevance_score?: number;
  recommendation?: string;
  confidence?: string;
  read: boolean;
  reading_status?: ReadingStatus;
  in_working_set: boolean;
  cluster_id?: number | null;
  summary?: string;
  summary_snippet?: string;
  tags: string[];
  folders: PaperFolder[];
  run_id?: number | null;
  semantic_score?: number | null;
  semantic_reason?: string | null;
  semantic_unavailable?: boolean;
};

export type PaperFolder = {
  id: number;
  name: string;
  paper_count?: number;
  created_at?: string;
};

export type PaperDetail = Paper & {
  abstract?: string;
  doi?: string;
  summary_detail?: {
    contributions?: string[];
    method?: string;
    key_terms?: string[];
    domain?: string;
  } | null;
  analysis?: {
    summary?: string;
    key_contributions?: string[];
    novelty_explanation?: string;
    relation_to_research?: string;
    recommendation_reason?: string;
    extends?: string[];
    overlaps_with?: string[];
    retrieved_paper_ids?: string[];
  } | null;
  verification?: {
    verified: boolean;
    issues: Array<{ problem?: string; claim?: string; detail?: string }>;
  } | null;
  related_papers?: Array<{ type: 'extends' | 'overlaps_with'; title: string; paper_id?: string | null }>;
  note?: { exists: boolean; path: string };
};

export type Report = {
  id: number;
  run_number?: number | null;
  run_type?: string;
  status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  papers_fetched?: number;
  papers_passed_s1?: number;
  papers_passed_s2?: number;
  papers_analyzed?: number;
  papers_verified?: number;
  papers_added_ws?: number;
  ingested_count?: number;
  unread_count?: number;
  digest_available?: boolean;
  digest_date?: string | null;
  log_available?: boolean;
  stages?: Array<{ key: string; label: string; status: string }>;
};

export type ReportDetail = {
  report: Report & { title?: string; digest?: string };
  papers: Paper[];
};

export type TagStat = {
  tag: string;
  count: number;
  unread_count: number;
  working_set_count: number;
};

export type PipelinePreview = {
  run_type: string;
  source_mode: string;
  sources: string[];
  scan_since?: string | null;
  scan_until: string;
  running: number;
  schedule?: PipelineSchedule;
};

export type PipelineSchedule = {
  enabled: boolean;
  time: string;
  source_mode: string;
  last_started_at?: string | null;
  last_run_id?: number | null;
};

export type PipelineLogs = {
  run_id: number;
  log: string;
  exists: boolean;
};

export type WorkspaceStats = {
  working_set_count: number;
  pending_prune_count: number;
};

export type PruneAction = {
  id: number;
  paper_id: string;
  pipeline_run_id?: number | null;
  title: string;
  recommendation: string;
  reason?: string;
  risk_if_removed?: string;
  status: string;
  created_at?: string;
  preview?: {
    relevance_score?: number;
    similarity?: number;
    key_terms?: string[];
    note_path?: string;
  };
};

export type GraphPayload = {
  nodes: Array<{
    id: string;
    label: string;
    type: string;
    paper_id?: string;
    read?: boolean;
    relevance_score?: number;
    tags?: string[];
    run_id?: number | null;
    run_type?: string | null;
    source?: string;
    recommendation?: string | null;
    reading_status?: ReadingStatus;
  }>;
  edges: Array<{ source: string; target: string; type: string }>;
};

export type NodePosition = {
  x: number;
  y: number;
  vx: number;
  vy: number;
};
