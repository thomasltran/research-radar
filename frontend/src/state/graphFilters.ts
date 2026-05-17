import type { GraphPayload, ReadFilter } from '../types';

export type GraphFilterState = {
  selectedTags: string[];
  selectedReportFilter: string | null;
  selectedRecommendation: string | null;
  selectedReadFilter: ReadFilter;
};

type GraphNode = GraphPayload['nodes'][number];

export function isBootstrapPaperNode(node: GraphNode): boolean {
  return node.type === 'paper' && (node.source === 'bootstrap' || node.run_type === 'bootstrap');
}

export function paperNodeMatchesGraphFilters(node: GraphNode, filters: GraphFilterState): boolean {
  if (node.type !== 'paper') return false;
  const tagMatch = filters.selectedTags.length === 0
    || filters.selectedTags.every((tag) => (node.tags ?? []).includes(tag));
  const reportMatch = !filters.selectedReportFilter || Boolean(
    filters.selectedReportFilter === 'seed'
      ? isBootstrapPaperNode(node)
      : String(node.run_id) === filters.selectedReportFilter
  );
  const recommendationMatch = !filters.selectedRecommendation
    || node.recommendation === filters.selectedRecommendation;
  const readMatch = filters.selectedReadFilter === 'all'
    || (filters.selectedReadFilter === 'read' ? Boolean(node.read) : !node.read);
  return tagMatch && reportMatch && recommendationMatch && readMatch;
}

export function countVisibleGraphPapers(graph: GraphPayload | null | undefined, filters: GraphFilterState): number {
  if (!graph) return 0;
  return graph.nodes.filter((node) => paperNodeMatchesGraphFilters(node, filters)).length;
}
