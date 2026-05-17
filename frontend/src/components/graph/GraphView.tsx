import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import type { GraphPayload, NodePosition, ReadFilter } from '../../types';
import { truncateAtWord } from '../../utils';
import { isBootstrapPaperNode, paperNodeMatchesGraphFilters } from '../../state/graphFilters';
import { EmptyState } from '../ui/EmptyState';

type GraphViewProps = {
  graph?: GraphPayload | null;
  selectedPaperId: string | null;
  selectedTags: string[];
  selectedReportFilter: string | null;
  selectedRecommendation: string | null;
  selectedReadFilter: ReadFilter;
  onToggleTag: (tag: string) => void;
  onOpenPaper: (paperId: string) => void;
  onDeselectPaper: () => void;
  onClearTags: () => void;
};

type GraphNode = GraphPayload['nodes'][number];
type GraphEdge = GraphPayload['edges'][number];
type Viewport = { scale: number; x: number; y: number };

const GRAPH_WIDTH = 900;
const GRAPH_HEIGHT = 720;
const GRAPH_PADDING = 36;
const GRAPH_LABEL_PADDING = 190;
const MAX_REPULSION_PAIRS = 1400;
const DEFAULT_VIEWPORT: Viewport = { scale: 1, x: 0, y: 0 };

function clampPosition(point: Pick<NodePosition, 'x' | 'y'>): NodePosition {
  return {
    x: Math.min(GRAPH_WIDTH - GRAPH_LABEL_PADDING, Math.max(GRAPH_PADDING, point.x)),
    y: Math.min(GRAPH_HEIGHT - GRAPH_PADDING, Math.max(GRAPH_PADDING, point.y)),
    vx: 0,
    vy: 0,
  };
}

function initialNodePosition(node: GraphNode, index: number, total: number): NodePosition {
  const angle = (index / Math.max(total, 1)) * Math.PI * 2;
  const radius = node.type === 'paper' ? 260 : node.type === 'tag' ? 150 : 80;
  return clampPosition({
    x: GRAPH_WIDTH / 2 + Math.cos(angle) * radius,
    y: GRAPH_HEIGHT / 2 + Math.sin(angle) * radius,
  });
}

function fallbackPosition(): Pick<NodePosition, 'x' | 'y'> {
  return { x: GRAPH_WIDTH / 2, y: GRAPH_HEIGHT / 2 };
}

function edgeKey(edge: GraphEdge, index: number) {
  return `${edge.source}>${edge.target}:${edge.type}:${index}`;
}

function viewportTransform(viewport: Viewport) {
  return `translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`;
}

function pairFromIndex(pairIndex: number, nodeCount: number) {
  const row = Math.floor((2 * nodeCount - 1 - Math.sqrt((2 * nodeCount - 1) ** 2 - 8 * pairIndex)) / 2);
  const pairsBeforeRow = (row * (2 * nodeCount - row - 1)) / 2;
  return {
    sourceIndex: row,
    targetIndex: row + 1 + Math.round(pairIndex - pairsBeforeRow),
  };
}

function sameStringArray(left: string[], right: string[]) {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function graphViewPropsEqual(previous: GraphViewProps, next: GraphViewProps) {
  return previous.graph === next.graph
    && previous.selectedPaperId === next.selectedPaperId
    && previous.selectedReportFilter === next.selectedReportFilter
    && previous.selectedRecommendation === next.selectedRecommendation
    && previous.selectedReadFilter === next.selectedReadFilter
    && sameStringArray(previous.selectedTags, next.selectedTags);
}

function GraphViewComponent(props: GraphViewProps) {
  const graph = props.graph;
  const positionsRef = useRef<Record<string, NodePosition>>({});
  const nodeElementRefs = useRef<Map<string, SVGGElement>>(new Map());
  const edgeElementRefs = useRef<Map<string, SVGLineElement>>(new Map());
  const viewportGroupRef = useRef<SVGGElement | null>(null);
  const renderGraphRef = useRef<(() => void) | null>(null);
  const pinnedRef = useRef<Set<string>>(new Set());
  const dragRef = useRef<{ id: string; dx: number; dy: number; startX: number; startY: number; moved: boolean } | null>(null);
  const panRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number; moved: boolean } | null>(null);
  const viewportRef = useRef<Viewport>(DEFAULT_VIEWPORT);
  const wheelRef = useRef<{ frame: number; point: { x: number; y: number }; factor: number } | null>(null);
  const suppressNextClickRef = useRef(false);
  const simulationTokenRef = useRef(0);
  const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);

  const filteredGraph = useMemo(() => {
    if (!graph) return null;
    const graphNodesById = new Map(graph.nodes.map((node) => [node.id, node]));
    const paperNodeIds = new Set<string>();
    const tagNodeIds = new Set<string>();
    const contextNodeIds = new Set<string>();

    graph.nodes.forEach((node) => {
      if (paperNodeMatchesGraphFilters(node, props)) paperNodeIds.add(node.id);
    });

    graph.edges.forEach((edge) => {
      if (!paperNodeIds.has(edge.source)) return;
      const target = graphNodesById.get(edge.target);
      if (!target) return;
      if (target.type === 'tag') {
        if (props.selectedTags.length === 0 || props.selectedTags.includes(target.label)) {
          tagNodeIds.add(target.id);
        }
      } else if (target.type === 'paper' && paperNodeIds.has(target.id)) {
        contextNodeIds.add(target.id);
      }
    });

    const allowed = new Set([...paperNodeIds, ...tagNodeIds, ...contextNodeIds]);
    const nodes = graph.nodes.filter((node) => allowed.has(node.id));
    return {
      nodes,
      edges: graph.edges.filter((edge) => allowed.has(edge.source) && allowed.has(edge.target)),
    };
  }, [graph, props.selectedTags, props.selectedReportFilter, props.selectedRecommendation, props.selectedReadFilter]);

  const layoutKey = useMemo(() => {
    if (!filteredGraph) return '';
    const nodeKey = filteredGraph.nodes.map((node) => node.id).sort().join('|');
    const edgeKey = filteredGraph.edges
      .map((edge) => `${edge.source}>${edge.target}:${edge.type}`)
      .sort()
      .join('|');
    return `${nodeKey}::${edgeKey}`;
  }, [filteredGraph]);

  const nodes = filteredGraph?.nodes ?? [];
  const lookup = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const visibleEdges = useMemo(
    () => (filteredGraph?.edges ?? []).filter((edge) => lookup.has(edge.source) && lookup.has(edge.target)),
    [filteredGraph, lookup],
  );
  const selectedGraphNode = useMemo(
    () => nodes.find((node) => node.paper_id === props.selectedPaperId) ?? null,
    [nodes, props.selectedPaperId],
  );
  const connectedNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedGraphNode) return ids;
    ids.add(selectedGraphNode.id);
    visibleEdges.forEach((edge) => {
      if (edge.source === selectedGraphNode.id) ids.add(edge.target);
      if (edge.target === selectedGraphNode.id) ids.add(edge.source);
    });
    return ids;
  }, [selectedGraphNode, visibleEdges]);
  const graphSelectionActive = Boolean(selectedGraphNode);

  function applyViewport(next: Viewport, commit = false) {
    viewportRef.current = next;
    viewportGroupRef.current?.setAttribute('transform', viewportTransform(next));
    if (commit) setViewport(next);
  }

  useEffect(() => {
    return () => {
      if (wheelRef.current?.frame) window.cancelAnimationFrame(wheelRef.current.frame);
      wheelRef.current = null;
    };
  }, []);

  useEffect(() => {
    const renderGraph = () => {
      nodes.forEach((node) => {
        const position = positionsRef.current[node.id] ?? fallbackPosition();
        nodeElementRefs.current.get(node.id)?.setAttribute('transform', `translate(${position.x} ${position.y})`);
      });
      visibleEdges.forEach((edge, index) => {
        const source = positionsRef.current[edge.source] ?? fallbackPosition();
        const target = positionsRef.current[edge.target] ?? fallbackPosition();
        const element = edgeElementRefs.current.get(edgeKey(edge, index));
        if (!element) return;
        element.setAttribute('x1', String(source.x));
        element.setAttribute('y1', String(source.y));
        element.setAttribute('x2', String(target.x));
        element.setAttribute('y2', String(target.y));
      });
    };
    renderGraphRef.current = renderGraph;
    renderGraph();
    return () => {
      if (renderGraphRef.current === renderGraph) renderGraphRef.current = null;
    };
  }, [nodes, visibleEdges]);

  useEffect(() => {
    if (!filteredGraph) return;
    const current = positionsRef.current;
    const visibleIds = new Set(filteredGraph.nodes.map((node) => node.id));
    const next: Record<string, NodePosition> = {};
    filteredGraph.nodes.forEach((node, index) => {
      next[node.id] = current[node.id]
        ? clampPosition(current[node.id])
        : initialNodePosition(node, index, filteredGraph.nodes.length);
    });
    Object.keys(current).forEach((id) => {
      if (!visibleIds.has(id)) pinnedRef.current.delete(id);
    });
    positionsRef.current = next;
    renderGraphRef.current?.();
  }, [layoutKey]);

  useEffect(() => {
    if (!filteredGraph) return;
    const token = simulationTokenRef.current + 1;
    simulationTokenRef.current = token;
    let frame = 0;
    const nodes = filteredGraph.nodes;
    const edges = filteredGraph.edges;

    const run = (time: number) => {
      if (simulationTokenRef.current !== token) return;
      const positions = positionsRef.current;
      nodes.forEach((node, index) => {
        positions[node.id] = positions[node.id] ?? initialNodePosition(node, index, nodes.length);
      });

      const totalRepulsionPairs = (nodes.length * Math.max(nodes.length - 1, 0)) / 2;
      const repulsionStride = Math.max(1, Math.ceil(totalRepulsionPairs / MAX_REPULSION_PAIRS));
      const repulsionOffset = Math.floor(time / 16) % repulsionStride;
      for (let pairIndex = repulsionOffset; pairIndex < totalRepulsionPairs; pairIndex += repulsionStride) {
        const { sourceIndex, targetIndex } = pairFromIndex(pairIndex, nodes.length);
        const a = positions[nodes[sourceIndex].id];
        const b = positions[nodes[targetIndex].id];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distanceSq = Math.max(dx * dx + dy * dy, 80);
        const force = 720 / distanceSq;
        const distance = Math.sqrt(distanceSq);
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }

      edges.forEach((edge) => {
        const a = positions[edge.source];
        const b = positions[edge.target];
        if (!a || !b) return;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const target = 105;
        const force = (distance - target) * 0.002;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      });

      nodes.forEach((node, index) => {
        const p = positions[node.id];
        if (!pinnedRef.current.has(node.id)) {
          const driftAngle = (time * 0.0014) + (index * 2.399963);
          p.vx += Math.cos(driftAngle) * 0.012;
          p.vy += Math.sin(driftAngle) * 0.012;
          p.vx += (GRAPH_WIDTH / 2 - p.x) * 0.00065;
          p.vy += (GRAPH_HEIGHT / 2 - p.y) * 0.00065;
          const clamped = clampPosition({ x: p.x + p.vx, y: p.y + p.vy });
          p.x = clamped.x;
          p.y = clamped.y;
        }
        p.vx *= 0.9;
        p.vy *= 0.9;
      });

      renderGraphRef.current?.();
      if (frame !== 0) {
        frame = window.requestAnimationFrame(run);
      }
    };
    frame = window.requestAnimationFrame(run);
    return () => {
      simulationTokenRef.current += 1;
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [layoutKey]);

  function svgPoint(svg: SVGSVGElement, event: Pick<React.PointerEvent, 'clientX' | 'clientY'>) {
    const box = svg.getBoundingClientRect();
    return {
      x: ((event.clientX - box.left) / box.width) * GRAPH_WIDTH,
      y: ((event.clientY - box.top) / box.height) * GRAPH_HEIGHT,
    };
  }

  function graphPoint(svg: SVGSVGElement, event: Pick<React.PointerEvent, 'clientX' | 'clientY'>) {
    const point = svgPoint(svg, event);
    const currentViewport = viewportRef.current;
    return {
      x: (point.x - currentViewport.x) / currentViewport.scale,
      y: (point.y - currentViewport.y) / currentViewport.scale,
    };
  }

  function startDrag(event: React.PointerEvent<SVGGElement>, nodeId: string) {
    const svg = event.currentTarget.ownerSVGElement;
    if (!svg) return;
    const point = graphPoint(svg, event);
    const node = lookup.get(nodeId);
    if (!node) return;
    const position = positionsRef.current[nodeId] ?? fallbackPosition();
    dragRef.current = {
      id: nodeId,
      dx: point.x - position.x,
      dy: point.y - position.y,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    pinnedRef.current.add(nodeId);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function startPan(event: React.PointerEvent<SVGSVGElement>) {
    if (event.target !== event.currentTarget) return;
    panRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: viewportRef.current.x,
      originY: viewportRef.current.y,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function clearSelectionOnBackdrop(event: React.MouseEvent<SVGSVGElement>) {
    if (event.target !== event.currentTarget) return;
    if (suppressNextClickRef.current || panRef.current?.moved) {
      suppressNextClickRef.current = false;
      return;
    }
    if (props.selectedTags.length > 0) props.onClearTags();
    if (props.selectedPaperId) props.onDeselectPaper();
  }

  function moveDrag(event: React.PointerEvent<SVGSVGElement>) {
    if (dragRef.current) {
      const point = graphPoint(event.currentTarget, event);
      const drag = dragRef.current;
      if (Math.abs(event.clientX - drag.startX) <= 3 && Math.abs(event.clientY - drag.startY) <= 3) return;
      drag.moved = true;
      suppressNextClickRef.current = true;
      positionsRef.current[drag.id] = clampPosition({ x: point.x - drag.dx, y: point.y - drag.dy });
      renderGraphRef.current?.();
      return;
    }
    if (panRef.current && panRef.current.pointerId === event.pointerId) {
      const dx = ((event.clientX - panRef.current.startX) / event.currentTarget.getBoundingClientRect().width) * GRAPH_WIDTH;
      const dy = ((event.clientY - panRef.current.startY) / event.currentTarget.getBoundingClientRect().height) * GRAPH_HEIGHT;
      if (Math.abs(event.clientX - panRef.current.startX) > 3 || Math.abs(event.clientY - panRef.current.startY) > 3) {
        panRef.current.moved = true;
        suppressNextClickRef.current = true;
      }
      applyViewport({
        ...viewportRef.current,
        x: panRef.current!.originX + dx,
        y: panRef.current!.originY + dy,
      });
    }
  }

  function handleWheel(event: React.WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const svg = event.currentTarget;
    const point = svgPoint(svg, event);
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    if (wheelRef.current?.frame) {
      wheelRef.current.point = point;
      wheelRef.current.factor *= factor;
      return;
    }
    wheelRef.current = {
      frame: window.requestAnimationFrame(() => {
        const pending = wheelRef.current;
        if (!pending) return;
        wheelRef.current = null;
        const current = viewportRef.current;
        const scale = Math.min(2.4, Math.max(0.45, Number((current.scale * pending.factor).toFixed(3))));
        const graphX = (pending.point.x - current.x) / current.scale;
        const graphY = (pending.point.y - current.y) / current.scale;
        applyViewport({
          scale,
          x: pending.point.x - graphX * scale,
          y: pending.point.y - graphY * scale,
        }, true);
      }),
      point,
      factor,
    };
  }

  function zoomBy(delta: number) {
    const current = viewportRef.current;
    const point = { x: GRAPH_WIDTH / 2, y: GRAPH_HEIGHT / 2 };
    const scale = Math.min(2.4, Math.max(0.45, Number((current.scale + delta).toFixed(2))));
    const graphX = (point.x - current.x) / current.scale;
    const graphY = (point.y - current.y) / current.scale;
    applyViewport({
      scale,
      x: point.x - graphX * scale,
      y: point.y - graphY * scale,
    }, true);
  }

  function endDrag() {
    if (dragRef.current) pinnedRef.current.delete(dragRef.current.id);
    if (panRef.current?.moved) setViewport(viewportRef.current);
    dragRef.current = null;
    panRef.current = null;
  }

  function handleNodeClick(node: GraphPayload['nodes'][number]) {
    if (suppressNextClickRef.current || dragRef.current?.moved) {
      suppressNextClickRef.current = false;
      return;
    }
    if (node.type === 'paper' && node.paper_id) {
      if (node.paper_id === props.selectedPaperId) {
        props.onDeselectPaper();
        return;
      }
      props.onOpenPaper(node.paper_id);
    }
    if (node.type === 'tag') {
      props.onToggleTag(node.label);
    }
  }

  function nodeRadius(node: GraphPayload['nodes'][number]) {
    if (node.type !== 'paper') return node.type === 'tag' ? 6.2 : 5;
    const score = Math.max(0, Math.min(node.relevance_score ?? 0, 10));
    const normalized = Math.max(0, Math.min((score - 6) / 4, 1));
    const tagBoost = props.selectedTags.length > 0 && props.selectedTags.some((tag) => (node.tags ?? []).includes(tag)) ? 0.8 : 0;
    return Math.min(13.8, 5.2 + normalized * 8 + tagBoost);
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      if (props.selectedTags.length > 0) props.onClearTags();
      if (props.selectedPaperId) {
        props.onDeselectPaper();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [props.selectedPaperId, props.selectedTags.length, props.onDeselectPaper, props.onClearTags]);

  if (!filteredGraph) return <EmptyState title="Loading graph" body="Building local relationship graph." />;

  return (
    <div className="graph-wrap">
      <div className="graph-toolbar">
        <button
          className="graph-help-button"
          title="Drag nodes to disturb the layout. Click a paper node to open its detail and notes; click a tag node to toggle that global filter."
          aria-label="Graph help: drag nodes to disturb the layout. Click a paper node to open its detail and notes; click a tag node to toggle that global filter."
        >
          ?
        </button>
        <div className="graph-zoom-controls">
          <button className="ghost-button graph-zoom-button" onClick={() => zoomBy(-0.12)} aria-label="Zoom out">
            <Minus size={15} />
          </button>
          <span className="graph-zoom-label">{Math.round(viewport.scale * 100)}%</span>
          <button className="ghost-button graph-zoom-button" onClick={() => zoomBy(0.12)} aria-label="Zoom in">
            <Plus size={15} />
          </button>
        </div>
      </div>
      <div className="graph-canvas">
        <svg
          viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
          role="img"
          aria-label="Research relationship graph"
          onPointerDown={startPan}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerLeave={endDrag}
          onWheel={handleWheel}
          onClick={clearSelectionOnBackdrop}
        >
          <g ref={viewportGroupRef} transform={viewportTransform(viewport)}>
            {visibleEdges.map((edge, index) => {
              const source = lookup.get(edge.source);
              const target = lookup.get(edge.target);
              if (!source || !target) return null;
              const key = edgeKey(edge, index);
              const sourcePosition = positionsRef.current[edge.source] ?? fallbackPosition();
              const targetPosition = positionsRef.current[edge.target] ?? fallbackPosition();
              const isConnected = !selectedGraphNode
                || edge.source === selectedGraphNode.id
                || edge.target === selectedGraphNode.id;
              return (
                <line
                  key={key}
                  ref={(element) => {
                    if (element) edgeElementRefs.current.set(key, element);
                    else edgeElementRefs.current.delete(key);
                  }}
                  x1={sourcePosition.x}
                  y1={sourcePosition.y}
                  x2={targetPosition.x}
                  y2={targetPosition.y}
                  className={[
                    'edge',
                    edge.type,
                    selectedGraphNode ? (isConnected ? 'highlighted' : 'dimmed') : '',
                  ].filter(Boolean).join(' ')}
                />
              );
            })}
            {nodes.map((node) => {
              const position = positionsRef.current[node.id] ?? fallbackPosition();
              return (
                <g
                  key={node.id}
                  ref={(element) => {
                    if (element) nodeElementRefs.current.set(node.id, element);
                    else nodeElementRefs.current.delete(node.id);
                  }}
                  transform={`translate(${position.x} ${position.y})`}
                  className="graph-node"
                  onPointerDown={(event) => startDrag(event, node.id)}
                  onClick={() => handleNodeClick(node)}
                >
                  <circle
                    className={[
                      'node',
                      node.type,
                      isBootstrapPaperNode(node) ? 'seed' : '',
                      node.type === 'tag' && props.selectedTags.includes(node.label) ? 'tag-active' : '',
                      node.type === 'paper' && node.read ? 'read' : '',
                      node.type === 'paper' && node.recommendation ? `rec-${node.recommendation}` : '',
                      node.paper_id === props.selectedPaperId ? 'selected' : '',
                      selectedGraphNode ? (connectedNodeIds.has(node.id) ? 'highlighted' : 'dimmed') : '',
                    ].filter(Boolean).join(' ')}
                    r={nodeRadius(node)}
                  />
                  <title>{node.label}</title>
                  <text
                    x="12"
                    y="4"
                    className={[
                      props.selectedTags.includes(node.label) ? 'active-tag-label' : '',
                      graphSelectionActive && connectedNodeIds.has(node.id) ? 'graph-label-highlighted' : '',
                      graphSelectionActive && !connectedNodeIds.has(node.id) ? 'graph-label-dimmed' : '',
                    ].filter(Boolean).join(' ')}
                  >
                    {truncateAtWord(node.label, 42)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </div>
  );
}

export const GraphView = React.memo(GraphViewComponent, graphViewPropsEqual);
