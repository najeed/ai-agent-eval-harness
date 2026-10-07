/**
 * Pure telemetry, waterfall, and diagnostic logic for the LiveDebugger.
 * Fully decoupled from React DOM / CSS dependencies for pure unit testability.
 */

import dagre from 'dagre';
export interface LogEvent {
  _seq?: number;
  timestamp?: string;
  event: string;
  scenario_node_id?: string;
  node_id?: string;
  task_id?: string;
  execution_instance_id?: string;
  parent_execution_id?: string | null;
  iteration?: number;
  attempt?: number;
  status?: string;
  duration_ms?: number;
  category?: string;
  message?: string;
  tool_name?: string;
  error?: string;
  result?: string;
  [key: string]: any;
}

export interface WaterfallMarker {
  t: number;
  kind: 'tool_call' | 'tool_result' | 'evaluation' | 'error';
}

export interface WaterfallRow {
  execId: string;
  nodeId: string;
  parentExecutionId: string | null;
  iteration: number;
  status: string;
  durationMs: number | null;
  startTs: number | null;
  endTs: number | null;
  depth: number;
  markers: WaterfallMarker[];
  isReplayed?: boolean;
  originalDurationMs?: number | null;
  splitDuration?: {
    preMs: number;
    waitMs: number;
    postMs: number;
    totalComputeMs: number;
  };
}

export const normalizeEventSequence = (events: LogEvent[]): LogEvent[] => {
  if (!events || events.length <= 1) return events || [];
  const seqIndexed = events.map((e, arrivalIdx) => {
    const rawSeq = e._seq ?? e.seq;
    const seqNum = typeof rawSeq === 'number' && Number.isFinite(rawSeq) ? rawSeq : null;
    const ts = e.timestamp ? Date.parse(e.timestamp) : NaN;
    return {
      ev: e,
      arrivalIdx,
      seq: seqNum,
      ts: Number.isFinite(ts) ? ts : null,
    };
  });
  seqIndexed.sort((a, b) => {
    if (a.seq !== null && b.seq !== null && a.seq !== b.seq) return a.seq - b.seq;
    if (a.seq !== null && b.seq === null) return -1;
    if (a.seq === null && b.seq !== null) return 1;
    if (a.ts !== null && b.ts !== null && a.ts !== b.ts) return a.ts - b.ts;
    return a.arrivalIdx - b.arrivalIdx;
  });
  return seqIndexed.map(x => x.ev);
};

export const getSequenceOrderedEvents = normalizeEventSequence;

export type GraphLayerMode = 'planned' | 'executed' | 'divergence';

export interface TraceGraphTopology {
  scenarioNodes: Record<string, any>[];
  runtimeNodes: Record<string, any>[];
  visibleNodes: Record<string, any>[];
  executedNodeIds: Set<string>;
  graphNodeEvents: LogEvent[];
}

/**
 * Project the canonical scenario and execution records into one graph layer.
 * This deliberately contains no ReactFlow or JSX concerns so that the
 * planned/executed/divergence truth contract is independently testable.
 */
export const projectTraceGraphTopology = (
  allEvents: LogEvent[],
  scenario: any,
  mode: GraphLayerMode,
): TraceGraphTopology => {
  const scenarioNodes = Array.isArray(scenario?.workflow?.nodes)
    ? scenario.workflow.nodes
    : Array.isArray(scenario?.workflow?.tasks)
      ? scenario.workflow.tasks
      : [];
  const graphNodeEvents = normalizeEventSequence(allEvents).filter(
    event => event.event === 'execution_graph_node',
  );
  const executedNodeIds = new Set(
    graphNodeEvents
      .map(event => event.scenario_node_id)
      .filter((nodeId): nodeId is string => typeof nodeId === 'string' && nodeId.length > 0),
  );
  const scenarioNodeIds = new Set(
    scenarioNodes.map((node: Record<string, any>) =>
      String(node.id || node.scenario_node_id || node.task_id),
    ),
  );
  const runtimeNodes: Record<string, any>[] = [];
  for (const nodeId of executedNodeIds) {
    if (!scenarioNodeIds.has(nodeId)) {
      runtimeNodes.push({ id: nodeId, task_description: nodeId, __runtime_discovered: true });
    }
  }

  const visibleNodes =
    mode === 'planned'
      ? scenarioNodes
      : mode === 'executed'
        ? [...scenarioNodes, ...runtimeNodes].filter(node =>
            executedNodeIds.has(String(node.id || node.scenario_node_id || node.task_id)),
          )
        : [...scenarioNodes, ...runtimeNodes];

  return { scenarioNodes, runtimeNodes, visibleNodes, executedNodeIds, graphNodeEvents };
};

export const buildWaterfall = (
  allEvents: LogEvent[]
): { rows: WaterfallRow[]; tMin: number | null; tMax: number | null } => {
  const orderedEvents = getSequenceOrderedEvents(allEvents);
  const byExec = new Map<string, WaterfallRow>();

  // Index HITL pauses and resumes for split timing computation
  const hitlPauses = new Map<string, { pauseTs: number; prePauseDurationMs?: number }>();
  const hitlResumes = new Map<string, { resumeTs: number }>();
  for (const e of orderedEvents) {
    const rawTaskId = e.task_id || e.scenario_node_id || e.node_id;
    const tId = rawTaskId ? String(rawTaskId) : undefined;
    const ts = e.timestamp ? Date.parse(e.timestamp) : (e.pause_start_ts ? e.pause_start_ts * 1000 : NaN);
    if ((e.event === 'hitl_pause' || e.event === 'HITL_PAUSE') && tId) {
      hitlPauses.set(tId, {
        pauseTs: Number.isFinite(ts) ? ts : Date.now(),
        prePauseDurationMs: typeof e.pre_pause_duration_ms === 'number' ? e.pre_pause_duration_ms : undefined,
      });
    } else if ((e.event === 'hitl_resume' || e.event === 'HITL_RESUME') && tId) {
      const rTs = e.timestamp ? Date.parse(e.timestamp) : (e.resume_ts ? e.resume_ts * 1000 : NaN);
      hitlResumes.set(tId, {
        resumeTs: Number.isFinite(rTs) ? rTs : Date.now(),
      });
    }
  }

  for (const e of orderedEvents) {
    if (e.event !== 'execution_graph_node') continue;
    const nodeId = e.scenario_node_id || e.node_id || '?';
    const execId = e.execution_instance_id || `${nodeId}#${e.iteration ?? e.attempt ?? 1}`;
    let row = byExec.get(execId);
    if (!row) {
      row = {
        execId,
        nodeId,
        parentExecutionId: e.parent_execution_id ?? null,
        iteration: e.iteration ?? 1,
        status: e.status || 'pending',
        durationMs: typeof e.duration_ms === 'number' ? e.duration_ms : null,
        startTs: null,
        endTs: null,
        depth: 0,
        markers: [],
      };
      byExec.set(execId, row);
    }

    const isReplayedEvent = e.is_replayed === true;
    if (isReplayedEvent) {
      row.isReplayed = true;
      if (typeof e.original_duration_ms === 'number') {
        row.originalDurationMs = e.original_duration_ms;
        if (row.durationMs === null || row.durationMs === 0) {
          row.durationMs = e.original_duration_ms;
        }
      }
    } else {
      if (e.status) row.status = e.status;
      if (typeof e.duration_ms === 'number' && e.duration_ms > 0) row.durationMs = e.duration_ms;
      const ts = Date.parse(e.timestamp || '');
      if (!Number.isNaN(ts)) {
        if (e.status === 'running' && row.startTs === null) row.startTs = ts;
        row.endTs = row.endTs === null ? ts : Math.max(row.endTs, ts);
        if (row.startTs === null) row.startTs = ts;
      }
    }
  }

  // Compute split timing metrics for nodes that paused for human review
  for (const r of byExec.values()) {
    const pauseInfo = hitlPauses.get(r.nodeId);
    const resumeInfo = hitlResumes.get(r.nodeId);
    if (pauseInfo) {
      const waitMs = resumeInfo && resumeInfo.resumeTs > pauseInfo.pauseTs
        ? resumeInfo.resumeTs - pauseInfo.pauseTs
        : 0;
      const preMs = pauseInfo.prePauseDurationMs ?? 0;
      const postMs = r.durationMs ?? 0;
      r.splitDuration = {
        preMs,
        waitMs,
        postMs,
        totalComputeMs: preMs + postMs,
      };
      r.durationMs = r.splitDuration.totalComputeMs;
    }
  }

  const rows = [...byExec.values()];
  const byId = new Map(rows.map(r => [r.execId, r]));
  for (const r of rows) {
    let d = 0;
    let p = r.parentExecutionId;
    const seen = new Set<string>([r.execId]);
    while (p && byId.has(p) && !seen.has(p)) {
      d += 1;
      seen.add(p);
      p = byId.get(p)!.parentExecutionId;
    }
    r.depth = d;
  }

  rows.sort((a, b) =>
    (a.startTs ?? Infinity) - (b.startTs ?? Infinity) || a.execId.localeCompare(b.execId)
  );

  const rowsByNode = new Map<string, WaterfallRow[]>();
  for (const r of rows) {
    const list = rowsByNode.get(r.nodeId) || [];
    list.push(r);
    rowsByNode.set(r.nodeId, list);
  }

  // Attach tool/assertion/failure ticks via authoritative execution_instance_id
  const rowsByExecId = byId;
  for (const e of allEvents) {
    if (
      e.event !== 'tool_call' &&
      e.event !== 'tool_result' &&
      e.event !== 'evaluation' &&
      e.event !== 'error'
    ) {
      continue;
    }
    const execId = e.execution_instance_id;
    const nodeId = e.scenario_node_id || e.node_id || e.task_id;
    const ts = Date.parse(e.timestamp || '');
    if (Number.isNaN(ts)) continue;

    let target: WaterfallRow | undefined;
    if (execId && rowsByExecId.has(execId)) {
      target = rowsByExecId.get(execId);
    } else if (nodeId) {
      const candidates = rowsByNode.get(nodeId);
      if (candidates?.length) {
        if (typeof e.iteration === 'number') {
          target = candidates.find(r => r.iteration === e.iteration);
        }
        if (!target) {
          target = candidates.find(
            r => r.startTs !== null && r.endTs !== null && ts >= r.startTs && ts <= r.endTs
          );
        }
      }
    }

    if (target) {
      target.markers.push({
        t: ts,
        kind:
          e.event === 'tool_call'
            ? 'tool_call'
            : e.event === 'tool_result'
              ? 'tool_result'
              : e.event === 'evaluation'
                ? 'evaluation'
                : 'error',
      });
    }
  }

  for (const r of rows) r.markers.sort((a, b) => a.t - b.t);

  const starts = rows.map(r => r.startTs).filter((v): v is number => v !== null);
  const ends = rows.map(r => r.endTs).filter((v): v is number => v !== null);
  const tMin = starts.length ? Math.min(...starts) : null;
  const tMax = ends.length ? Math.max(...ends) : null;
  return { rows, tMin, tMax };
};

export interface SeqGap { from: number; to: number }

export const mergeSeqGap = (existing: SeqGap[], next: SeqGap): SeqGap[] => {
  const merged = [...existing, next].sort((a, b) => a.from - b.from);
  const out: SeqGap[] = [];
  for (const g of merged) {
    const last = out[out.length - 1];
    if (last && g.from <= last.to + 1) {
      last.to = Math.max(last.to, g.to);
    } else {
      out.push({ ...g });
    }
  }
  return out.slice(-10);
};

/** Remove one recovered sequence from a gap interval, retaining both sides. */
export const subtractSeqFromGaps = (gaps: SeqGap[], seq: number): SeqGap[] =>
  gaps.flatMap(gap => {
    if (seq < gap.from || seq > gap.to) return [{ ...gap }];
    const result: SeqGap[] = [];
    if (gap.from < seq) result.push({ from: gap.from, to: seq - 1 });
    if (seq < gap.to) result.push({ from: seq + 1, to: gap.to });
    return result;
  });

export interface NodeDiagnostic {
  nodeId: string;
  suspectedStatus: 'failed' | 'completed' | 'running';
  signals: string[];
  firstMatchingSeq: number | undefined;
}

const resolveTelemetryNodeId = (e: LogEvent): string | undefined =>
  e.scenario_node_id || e.node_id || e.task_id;

export const computeTelemetryDiagnostics = (allEvents: LogEvent[]): NodeDiagnostic[] => {
  const diagnostics: NodeDiagnostic[] = [];
  const canonicallyCovered = new Set<string>();
  const eventsByNode = new Map<string, LogEvent[]>();
  const orderedEvents = getSequenceOrderedEvents(allEvents);

  // Single O(N) pass to index events by nodeId and collect canonical nodes
  for (const e of orderedEvents) {
    if (e.event === 'execution_graph_node') {
      if (e.scenario_node_id) canonicallyCovered.add(e.scenario_node_id);
    } else {
      const nodeId = resolveTelemetryNodeId(e);
      if (nodeId) {
        let list = eventsByNode.get(nodeId);
        if (!list) {
          list = [];
          eventsByNode.set(nodeId, list);
        }
        list.push(e);
      }
    }
  }

  for (const [nodeId, group] of eventsByNode.entries()) {
    if (canonicallyCovered.has(nodeId)) continue;

    const signals: string[] = [];
    let suspectedStatus: NodeDiagnostic['suspectedStatus'] | undefined;

    // Structured failure/verdict evidence check first
    let matchingEvent: any = null;
    const failEvent = group.find(
      (e) =>
        e.event === 'error' ||
        (e.event === 'evaluation' && e.status === 'failed') ||
        e.category === 'PARITY_STATE_DIVERGENCE' ||
        (e.status && e.status.toLowerCase() === 'failed')
    );
    if (failEvent) {
      suspectedStatus = 'failed';
      signals.push('structured error or failed verdict in telemetry');
      matchingEvent = failEvent;
    } else {
      const compEvent = group.find(
        (e) =>
          (e.status && e.status.toLowerCase() === 'completed') ||
          e.event === 'maneuver_end' ||
          e.event === 'node_end' ||
          e.result === 'success'
      );
      if (compEvent) {
        suspectedStatus = 'completed';
        signals.push('completion signal in telemetry');
        matchingEvent = compEvent;
      } else {
        const runEvent = group.find(
          (e) =>
            (e.status && e.status.toLowerCase() === 'running') ||
            e.event === 'node_start' ||
            e.event === 'maneuver_start'
        );
        if (runEvent) {
          suspectedStatus = 'running';
          signals.push('activity signal in telemetry');
          matchingEvent = runEvent;
        }
      }
    }

    if (suspectedStatus && matchingEvent) {
      diagnostics.push({
        nodeId,
        suspectedStatus,
        signals,
        firstMatchingSeq: matchingEvent._seq ?? matchingEvent.seq ?? group[0]?._seq,
      });
    }
    if (diagnostics.length >= 50) break;
  }
  return diagnostics;
};


// ---------------------------------------------------------------------------
// [B2] Compositional trace-integrity flags.
// ---------------------------------------------------------------------------


export interface TraceIntegrityFlags {
  hasEvents: boolean;
  recovered: boolean;
  gaps: boolean;
  reordered: boolean;
  missingStart: boolean;
  missingEnd: boolean;
  missingSequences: boolean;
  hasValidSequences: boolean;
  issues: string[];
}

const MAX_LISTED_GAPS = 5;

export const computeTraceIntegrity = (
  events: LogEvent[],
  sourcedFromMaster: boolean
): TraceIntegrityFlags => {
  if (!events || events.length === 0) {
    return {
      hasEvents: false,
      recovered: false,
      gaps: false,
      reordered: false,
      missingStart: false,
      missingEnd: false,
      missingSequences: false,
      hasValidSequences: false,
      issues: ['No events received.'],
    };
  }

  const issues: string[] = [];
  const validSeqEntries = events
    .map((e, idx) => ({ seq: e._seq !== undefined && e._seq !== null ? Number(e._seq) : NaN, idx }))
    .filter(item => !Number.isNaN(item.seq));
  const seqs = validSeqEntries.map(item => item.seq);

  let reordered = false;
  let gaps = false;
  let missingSequences = false;

  if (seqs.length === 0) {
    missingSequences = true;
    gaps = true;
    issues.push('Events lack server-assigned _seq identifiers.');
  } else {
    if (seqs.length < events.length) {
      missingSequences = true;
      gaps = true;
      issues.push(`${events.length - seqs.length} event(s) lack server-assigned _seq identifiers.`);
    }

    const sorted = [...seqs].sort((a, b) => a - b);
    const uniq = Array.from(new Set(sorted));

    reordered = seqs.some((v, i) => i > 0 && v < seqs[i - 1]);
    if (reordered) {
      issues.push('Events arrived out of monotonic _seq order (client-side reorder buffer applied).');
    }

    const hasGapsOrDups =
      uniq[uniq.length - 1] - uniq[0] + 1 !== uniq.length ||
      uniq.length !== sorted.length;
    if (hasGapsOrDups) {
      gaps = true;
      const missing: number[] = [];
      for (let s = uniq[0]; s <= uniq[uniq.length - 1]; s++) {
        if (!uniq.includes(s)) missing.push(s);
        if (missing.length > MAX_LISTED_GAPS) {
          missing.push(-1);
          break;
        }
      }
      const duplicates = sorted.length - uniq.length;
      const parts: string[] = [];
      if (missing.some(m => m >= 0)) {
        parts.push(
          `missing _seq ${missing.filter(m => m >= 0).join(', ')}${missing.includes(-1) ? ', …' : ''}`
        );
      }
      if (duplicates > 0) parts.push(`${duplicates} duplicate frame(s)`);
      issues.push(`Sequence discontinuity detected: ${parts.join('; ')}.`);
    }
  }

  const hasValidSequences = seqs.length === events.length && seqs.length > 0 && !gaps && !reordered;

  const recovered = !!sourcedFromMaster;
  if (recovered) {
    issues.push('Trace recovered from master log; per-run stream was incomplete.');
  }

  const hasStart = events.some(e => e.event === 'run_start');
  const terminalEventTypes = new Set([
    'run_end',
    'run_completed',
    'trace_sealed',
    'verification_certificate_issued',
    'certification_failed',
  ]);
  const hasEnd = events.some(e => terminalEventTypes.has(e.event));
  const missingStart = !hasStart;
  const missingEnd = !hasEnd;
  if (missingEnd) issues.push('Missing terminal event (run_end, trace_sealed, or verification_certificate_issued).');
  else if (missingStart) issues.push('Missing run_start event.');

  return {
    hasEvents: true,
    recovered,
    gaps,
    reordered,
    missingStart,
    missingEnd,
    missingSequences,
    hasValidSequences,
    issues,
  };
};

// ---------------------------------------------------------------------------
// [B4] Typed telemetry taxonomy
// ---------------------------------------------------------------------------

export type TelemetryLevel = 'PHASE' | 'SUBTASK' | 'ACTION' | 'STEP';

const TELEMETRY_TAXONOMY: Record<Exclude<TelemetryLevel, 'STEP'>, ReadonlySet<string>> = {
  PHASE: new Set(['phase_start', 'phase_end']),
  SUBTASK: new Set([
    'strategy_start',
    'strategy_end',
    'maneuver_start',
    'maneuver_end',
    'subtask_start',
    'subtask_end',
  ]),
  ACTION: new Set([
    'action_start',
    'action_end',
    'tool_call',
    'tool_result',
    'agent_request',
    'agent_response',
    'chain_start',
    'chain_end',
    'node_start',
    'node_end',
    'adapter_debug',
  ]),
};

export const filterEventsByTelemetryLevel = (
  events: LogEvent[],
  level: TelemetryLevel
): LogEvent[] => {
  if (level === 'STEP') return events;
  const taxonomy = TELEMETRY_TAXONOMY[level];
  const critical = new Set(['error', 'evaluation_failed', 'PARITY_STATE_DIVERGENCE', 'evaluator_finalization', 'certification_failed', 'trace_integrity_failure', 'run_end']);
  return events.filter(e => taxonomy.has(e.event) || critical.has(e.event) || e.passed === false || String(e.status || '').toLowerCase() === 'failed');
};


// ---------------------------------------------------------------------------
// Graph builder — pure ReactFlow data derivation (no JSX).
// Owned here so it is independently unit-testable in a plain Node environment.
// LiveDebugger.tsx maps the returned FlowNodeData scalars onto JSX labels.
// ---------------------------------------------------------------------------

/** Structured scalar payload for a single graph node. No JSX. */
export interface FlowNodeData {
  /** Canonical node ID string */
  id: string;
  /** Human-readable task description */
  label: string;
  /** Aggregated status string ('pending' | 'running' | 'completed' | 'failed' | …) */
  status: string;
  /** Display-ready status label (e.g. "Completed (2/3 with retries)") */
  statusLabel: string;
  /** Highest attempt number observed across all execution_graph_node events */
  maxAttempt: number;
  /** True if at least one execution_graph_node event exists for this node */
  hasCanonicalEvent: boolean;
  /** True when mode===divergence, run is terminal, node was planned but never executed */
  isSkipped: boolean;
  /** True when node was discovered at runtime (not in the scenario DAG) */
  isUnplanned: boolean;
  /** Duration in ms from latest execution_graph_node event, if present */
  durationMs: number | undefined;
  /** Graph layer mode, forwarded to the renderer for divergence-overlay logic */
  mode: GraphLayerMode;
  /** Count of 'completed' status events — nonzero only when retries occurred */
  passCount: number;
  /** Count of failure-class status events */
  failCount: number;
  /** failure_class field from the latest execution_graph_node event */
  failureClass: string | undefined;
  /** failure_reason field from the latest execution_graph_node event */
  failureReason: string | undefined;
  /** Whether the node is currently highlighted (matches the selected event) */
  isHighlighted: boolean;
  /** True if this node was fast-forwarded / replayed from a resume checkpoint */
  isReplayed?: boolean;
  /** Original duration in ms before pause/resume */
  originalDurationMs?: number;
  /** Replayed fast-forward duration in ms (typically ~0.00ms) */
  replayedDurationMs?: number;
  /** Split execution metrics for nodes paused by HITL */
  splitDuration?: {
    preMs: number;
    waitMs: number;
    postMs: number;
    totalComputeMs: number;
  };
}

/** A single ReactFlow node with typed data (label is a scalar string). */
export interface FlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: FlowNodeData;
  style: Record<string, unknown>;
}

/** A single ReactFlow edge with provenance and parallel-edge geometry. */
export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  label: string | undefined;
  animated: boolean;
  type: string | undefined;
  pathOptions: { offset: number; borderRadius: number } | undefined;
  style: Record<string, unknown>;
  data: {
    parallelIndex: number;
    parallelTotal: number;
    pathOffset: number | undefined;
  };
  /** Provenance tag — 'planned' | 'executed'. Consumed by the filter pass. */
  provenance: 'planned' | 'executed';
}

export interface TraceGraphResult {
  flowNodes: FlowNode[];
  flowEdges: FlowEdge[];
  provenance: 'CANONICAL' | 'TOPOLOGY_UNAVAILABLE';
  scenarioNodeCount: number;
  runtimeNodeCount: number;
  droppedEdgeCount: number;
}

const _GRAPH_NODE_WIDTH = 180;
const _GRAPH_NODE_HEIGHT = 70;

/**
 * Build the complete ReactFlow node+edge arrays from raw trace events.
 *
 * This function is intentionally dependency-free from React / JSX so that
 * every derivation (status aggregation, retry detection, edge projection,
 * parallel-edge geometry, dagre layout, position persistence) can be
 * regression-tested in a plain Node process.
 *
 * @param allEvents      Raw log events in arrival order.
 * @param scenario       The active AES 1.4 scenario object (may be null/undefined
 *                       while still hydrating — returns TOPOLOGY_UNAVAILABLE).
 * @param selection      Currently selected event (for highlight derivation).
 * @param mode           Graph layer mode — 'planned' | 'executed' | 'divergence'.
 * @param isTerminalRun  True once the run has reached a terminal status.
 * @param positions      Mutable Map used to persist dragged node positions across
 *                       renders. Keyed by the value returned from posKeyFn.
 * @param posKeyFn       Returns the cache key for a given node id. Injected so
 *                       that the caller (LiveDebugger) can encode run+scenario
 *                       context into the key without coupling this function to
 *                       component state.
 */
export const buildTraceGraph = (
  allEvents: LogEvent[],
  scenario: Record<string, any> | null | undefined,
  selection: LogEvent | null,
  mode: GraphLayerMode,
  isTerminalRun: boolean,
  positions: Map<string, { x: number; y: number }>,
  posKeyFn: (nodeId: string) => string,
): TraceGraphResult => {
  // Runtime evidence can decorate a scenario topology, but must not create a
  // renderable topology before the canonical scenario has hydrated.
  if (!scenario) {
    return {
      flowNodes: [],
      flowEdges: [],
      provenance: 'TOPOLOGY_UNAVAILABLE',
      scenarioNodeCount: 0,
      runtimeNodeCount: 0,
      droppedEdgeCount: 0,
    };
  }

  // 0. Canonical event normalization
  const normalizedEvents = normalizeEventSequence(allEvents);

  // 1. Topology projection (pure, independently regression-tested)
  const topology = projectTraceGraphTopology(normalizedEvents, scenario, mode);
  const scenarioNodesRaw = topology.scenarioNodes;
  const graphNodeEventsAll = topology.graphNodeEvents;
  const executedNodeIds = topology.executedNodeIds;
  const runtimeDiscoveredNodes = topology.runtimeNodes;
  const workflowNodes = topology.visibleNodes;
  const workflowEdges: Record<string, any>[] =
    Array.isArray(scenario?.workflow?.edges) ? scenario!.workflow.edges : [];

  if (workflowNodes.length === 0) {
    return {
      flowNodes: [],
      flowEdges: [],
      provenance: 'TOPOLOGY_UNAVAILABLE',
      scenarioNodeCount: 0,
      runtimeNodeCount: 0,
      droppedEdgeCount: 0,
    };
  }

  // 2. Per-node status + retry aggregation via O(1) index.
  // Status derives SOLELY from execution_graph_node events; no string heuristics.
  const eventsByNodeId = new Map<string, LogEvent[]>();
  for (const ev of graphNodeEventsAll) {
    if (ev.scenario_node_id) {
      const nid = String(ev.scenario_node_id);
      const list = eventsByNodeId.get(nid);
      if (list) list.push(ev);
      else eventsByNodeId.set(nid, [ev]);
    }
  }

  // Index HITL pauses and resumes for split timing computation across graph nodes
  const hitlPauseMap = new Map<string, { pauseTs: number; prePauseDurationMs?: number }>();
  const hitlResumeMap = new Map<string, { resumeTs: number }>();
  for (const ev of normalizedEvents) {
    const rawTaskId = ev.task_id || ev.scenario_node_id || ev.node_id;
    const tId = rawTaskId ? String(rawTaskId) : undefined;
    const ts = ev.timestamp ? Date.parse(ev.timestamp) : (ev.pause_start_ts ? ev.pause_start_ts * 1000 : NaN);
    if ((ev.event === 'hitl_pause' || ev.event === 'HITL_PAUSE') && tId) {
      hitlPauseMap.set(tId, {
        pauseTs: Number.isFinite(ts) ? ts : Date.now(),
        prePauseDurationMs: typeof ev.pre_pause_duration_ms === 'number' ? ev.pre_pause_duration_ms : undefined,
      });
    } else if ((ev.event === 'hitl_resume' || ev.event === 'HITL_RESUME') && tId) {
      const rTs = ev.timestamp ? Date.parse(ev.timestamp) : (ev.resume_ts ? ev.resume_ts * 1000 : NaN);
      hitlResumeMap.set(tId, {
        resumeTs: Number.isFinite(rTs) ? rTs : Date.now(),
      });
    }
  }

  const selectedId =
    selection?.scenario_node_id || selection?.node_id || selection?.task_id;

  const flowNodes: FlowNode[] = workflowNodes.map((n: Record<string, any>) => {
    const id = String(n.id || n.scenario_node_id || n.task_id);
    const label = String(n.task_description || n.description || n.label || id);

    const graphNodeEvents = eventsByNodeId.get(id) || [];

    let status = 'pending';
    let hasCanonicalEvent = false;
    let failureClass: string | undefined;
    let failureReason: string | undefined;
    let durationMs: number | undefined;
    let maxAttempt = 1;
    let passCount = 0;
    let failCount = 0;
    let isReplayed = false;
    let originalDurationMs: number | undefined;
    let replayedDurationMs: number | undefined;
    let splitDuration: FlowNodeData['splitDuration'] | undefined;

    if (graphNodeEvents.length > 0) {
      for (const ev of graphNodeEvents) {
        const st = ev.status ? ev.status.toLowerCase() : '';
        if (st === 'completed') passCount++;
        else if (st === 'failed' || st === 'error' || st === 'aborted') failCount++;
        if (ev.is_replayed === true) isReplayed = true;
      }
      const latestEv = graphNodeEvents[graphNodeEvents.length - 1];
      if (latestEv.status) status = latestEv.status.toLowerCase();
      failureClass = latestEv.failure_class;
      failureReason = latestEv.failure_reason;
      const attempts = graphNodeEvents.map((e) => e.attempt || 1);
      maxAttempt = attempts.length > 0 ? Math.max(...attempts) : 1;
      hasCanonicalEvent = true;

      // Detect replayed executions (both explicit flag and multiple completed events from resume)
      const completedEvents = graphNodeEvents.filter((e) => String(e.status || '').toLowerCase() === 'completed');
      if (completedEvents.length > 1) {
        const firstComp = completedEvents[0];
        const lastComp = completedEvents[completedEvents.length - 1];
        if (lastComp.is_replayed || (typeof firstComp.duration_ms === 'number' && firstComp.duration_ms > 0 && typeof lastComp.duration_ms === 'number' && lastComp.duration_ms < 50)) {
          isReplayed = true;
          originalDurationMs = firstComp.original_duration_ms ?? firstComp.duration_ms;
          replayedDurationMs = lastComp.duration_ms;
        }
      } else if (latestEv.is_replayed) {
        isReplayed = true;
        originalDurationMs = latestEv.original_duration_ms;
        replayedDurationMs = latestEv.duration_ms;
      }

      // Detect split execution for nodes paused by human review
      const pauseInfo = hitlPauseMap.get(id);
      const resumeInfo = hitlResumeMap.get(id);
      if (pauseInfo) {
        const waitMs = resumeInfo && resumeInfo.resumeTs > pauseInfo.pauseTs
          ? resumeInfo.resumeTs - pauseInfo.pauseTs
          : 0;
        const postMs = typeof latestEv.duration_ms === 'number' ? latestEv.duration_ms : 0;
        const preMs = pauseInfo.prePauseDurationMs ?? 0;
        splitDuration = {
          preMs,
          waitMs,
          postMs,
          totalComputeMs: preMs + postMs,
        };
        durationMs = splitDuration.totalComputeMs;
      } else {
        durationMs = isReplayed && originalDurationMs != null ? originalDurationMs : latestEv.duration_ms;
      }
    }

    const isHighlighted = !!selectedId && selectedId === id;
    const isUnplanned = !!(n.__runtime_discovered);
    const isSkipped =
      mode === 'divergence' &&
      !isUnplanned &&
      isTerminalRun &&
      !executedNodeIds.has(id);

    // Status label — descriptive text scalars only, no JSX
    let statusLabel = 'Pending';
    if (status === 'failed' || status === 'error' || status === 'aborted') {
      statusLabel =
        failureClass ||
        failureReason ||
        (failCount > 1 ? `Failed (${failCount} attempts)` : 'Failed');
    } else if (isReplayed && status === 'completed') {
      statusLabel = originalDurationMs != null
        ? `Replayed (${(originalDurationMs / 1000).toFixed(2)}s)`
        : 'Replayed';
    } else if (status === 'completed') {
      statusLabel =
        failCount > 0
          ? `Completed (${passCount}/${passCount + failCount} with retries)`
          : 'Completed';
    } else if (status === 'running') {
      statusLabel = maxAttempt > 1 ? `Running (att #${maxAttempt})` : 'Running';
    }

    // Visual style — plain CSS property strings, no JSX
    let border = isHighlighted ? '2px solid #818cf8' : '1px solid #334155';
    let background = '#0f172a';

    if (status === 'failed' || status === 'error' || status === 'aborted') {
      border = isHighlighted ? '2px solid #f87171' : '1px solid #ef4444';
      background = 'rgba(127,29,29,0.4)';
    } else if (isReplayed && status === 'completed') {
      // Replayed nodes styled in neutral blue theme
      border = isHighlighted ? '2px solid #60a5fa' : '1px solid #3b82f6';
      background = 'rgba(30,58,138,0.4)';
    } else if (status === 'completed') {
      border = isHighlighted ? '2px solid #34d399' : '1px solid #10b981';
      background = 'rgba(6,78,59,0.4)';
    } else if (status === 'running') {
      border = isHighlighted ? '2px solid #fbbf24' : '1px solid #f59e0b';
      background = 'rgba(120,53,15,0.4)';
    }
    if (isSkipped) {
      border = `${isHighlighted ? '2px' : '1px'} dashed #ef4444`;
    }
    if (isUnplanned && mode === 'divergence') {
      border = `${isHighlighted ? '2px' : '1px'} dashed #f59e0b`;
    }

    return {
      id,
      type: 'default',
      position: { x: 0, y: 0 },
      data: {
        id,
        label,
        status,
        statusLabel,
        maxAttempt,
        hasCanonicalEvent,
        isSkipped,
        isUnplanned,
        durationMs,
        mode,
        passCount,
        failCount,
        failureClass,
        failureReason,
        isHighlighted,
        isReplayed,
        originalDurationMs,
        replayedDurationMs,
        splitDuration,
      },
      style: {
        background,
        color: '#fff',
        border,
        borderRadius: '8px',
        padding: '8px',
        width: _GRAPH_NODE_WIDTH - 10,
        boxShadow: isHighlighted
          ? '0 0 15px rgba(99, 102, 241, 0.7), inset 0 0 0 1px rgba(129, 140, 248, 0.5)'
          : 'none',
        transition:
          'box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease',
      },
    };
  });

  // 3. Edge projection: scenario workflow edges + runtime execution_graph_edge events
  const nodeIdSet = new Set(flowNodes.map((n) => n.id));
  // Use a looser intermediate type during construction before the filter/map pass
  type RawEdge = Omit<FlowEdge, 'data' | 'type' | 'pathOptions'> & {
    data?: Record<string, unknown>;
    type?: string;
    pathOptions?: { offset: number; borderRadius: number };
    provenance: 'planned' | 'executed';
  };
  const flowEdgesMap = new Map<string, RawEdge>();

  // 3a. Planned edges from the scenario workflow definition
  workflowEdges.forEach((e, idx) => {
    const source = String(e.from || e.source || '');
    const target = String(e.to || e.target || '');
    if (nodeIdSet.has(source) && nodeIdSet.has(target)) {
      const edgeId =
        String(e.id || `scen-edge-${source}-${target}-${e.condition || e.type || idx}`);
      flowEdgesMap.set(edgeId, {
        id: edgeId,
        source,
        target,
        label: e.condition || e.label || undefined,
        provenance: 'planned',
        animated: true,
        style: { stroke: '#6366f1', strokeWidth: 2 },
      });
    }
  });

  // 3b. Runtime execution_graph_edge events
  const graphEdgeEvents = normalizedEvents.filter(
    (e) => e.event === 'execution_graph_edge',
  );
  const instanceOwner = new Map<string, string>();
  for (const ev of graphNodeEventsAll) {
    if (ev.execution_instance_id && ev.scenario_node_id) {
      instanceOwner.set(
        String(ev.execution_instance_id),
        String(ev.scenario_node_id),
      );
    }
  }
  let droppedEdgeEvents = 0;
  const seenReplayTransitions = new Set<string>();

  graphEdgeEvents.forEach((e, idx) => {
    const rawSource = e.from_scenario_node_id || e.source_execution_id || e.source;
    const rawTarget = e.to_scenario_node_id || e.target_execution_id || e.target;
    const source: string | undefined = nodeIdSet.has(rawSource)
      ? rawSource
      : instanceOwner.get(String(rawSource));
    const target: string | undefined = nodeIdSet.has(rawTarget)
      ? rawTarget
      : instanceOwner.get(String(rawTarget));
    if (source && target && nodeIdSet.has(source) && nodeIdSet.has(target)) {
      const isRetry = e.edge_type === 'retry';
      const transitionKey = `${source}->${target}:${e.edge_type ?? 'sequential'}:${e.iteration ?? 1}:${e.selected_edge_id ?? ''}`;

      // Deduplicate ONLY replayed transitions.
      // Conditional loops with distinct iterations, retries, and non-replayed transitions are strictly preserved!
      const isReplayed = e.is_replayed === true || (seenReplayTransitions.has(transitionKey) && !isRetry);
      if (isReplayed && seenReplayTransitions.has(transitionKey)) {
        return; // Deduplicate this replayed transition
      }
      seenReplayTransitions.add(transitionKey);

      const edgeId = `exec-edge-${source}-${target}-${e._seq ?? e.execution_edge_id ?? idx}`;
      const label =
        e.edge_type === 'retry'
          ? `retry${e.iteration ? ` #${e.iteration}` : ''}`
          : e.edge_type === 'conditional'
            ? 'if'
            : e.iteration
              ? `#${e.iteration}`
              : undefined;
      flowEdgesMap.set(edgeId, {
        id: edgeId,
        source,
        target,
        label,
        provenance: 'executed',
        animated: true,
        style: {
          stroke: e.edge_type === 'retry' ? '#f59e0b' : '#6366f1',
          strokeWidth: 2,
          strokeDasharray: e.edge_type === 'retry' ? '5,5' : undefined,
        },
      });
    } else if (rawSource != null && rawTarget != null) {
      droppedEdgeEvents++;
    }
  });

  const allEdgesRaw = Array.from(flowEdgesMap.values());

  // 4. Mode filter + parallel-edge offset geometry
  const edgePairCounts = new Map<string, number>();
  const edgePairCurrent = new Map<string, number>();
  for (const e of allEdgesRaw) {
    const pair = `${e.source}->${e.target}`;
    edgePairCounts.set(pair, (edgePairCounts.get(pair) || 0) + 1);
  }

  const flowEdges: FlowEdge[] = allEdgesRaw
    .filter((e) => {
      const isPlanned = e.provenance === 'planned';
      if (mode === 'planned') return isPlanned;
      if (mode === 'executed') return !isPlanned;
      return true; // divergence: show all
    })
    .map((e): FlowEdge => {
      const isPlanned = e.provenance === 'planned';
      const pair = `${e.source}->${e.target}`;
      const total = edgePairCounts.get(pair) || 1;
      const cur = edgePairCurrent.get(pair) || 0;
      edgePairCurrent.set(pair, cur + 1);

      const pathOffset = total > 1 ? Math.round(20 + cur * 16) : undefined;
      const pathOptions =
        total > 1 ? { offset: pathOffset as number, borderRadius: 8 } : undefined;
      const edgeData = { parallelIndex: cur, parallelTotal: total, pathOffset };

      if (!isPlanned) {
        const isDivergence = mode === 'divergence';
        return {
          ...e,
          type: total > 1 ? 'smoothstep' : undefined,
          pathOptions,
          animated: mode !== 'planned',
          data: edgeData,
          style: {
            ...e.style,
            stroke: e.style?.stroke ?? (isDivergence ? '#f59e0b' : '#10b981'),
            strokeWidth: isDivergence ? 2.5 : 2,
          },
        };
      }
      if (mode === 'planned') {
        return {
          ...e,
          type: total > 1 ? 'smoothstep' : undefined,
          pathOptions,
          animated: true,
          data: edgeData,
          style: { stroke: '#6366f1', strokeWidth: 2 },
        };
      }
      // divergence mode: subordinate planned baseline edges visually
      return {
        ...e,
        type: total > 1 ? 'smoothstep' : undefined,
        pathOptions,
        animated: false,
        data: edgeData,
        style: {
          stroke: '#334155',
          strokeWidth: 1,
          strokeDasharray: '4,4',
          opacity: 0.35,
        },
      };
    });

  // 5. Dagre layout with position persistence
  // dagre is a plain JS library with no DOM dependency; safe to import here.
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 80 });

  flowNodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: _GRAPH_NODE_WIDTH,
      height: _GRAPH_NODE_HEIGHT,
    });
  });
  flowEdges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });
  dagre.layout(dagreGraph);

  const layoutedNodes: FlowNode[] = flowNodes.map((node, index) => {
    const savedPos = positions.get(posKeyFn(node.id));
    if (savedPos) {
      return { ...node, position: savedPos };
    }
    const nodeWithPosition = dagreGraph.node(node.id);
    const x = nodeWithPosition
      ? nodeWithPosition.x - _GRAPH_NODE_WIDTH / 2 + 80
      : 80 + index * 220;
    const y = nodeWithPosition
      ? nodeWithPosition.y - _GRAPH_NODE_HEIGHT / 2 + 50
      : 50;
    const pos = { x, y };
    positions.set(posKeyFn(node.id), pos);
    return { ...node, position: pos };
  });

  return {
    flowNodes: layoutedNodes,
    flowEdges,
    provenance: 'CANONICAL',
    scenarioNodeCount: scenarioNodesRaw.length,
    runtimeNodeCount: runtimeDiscoveredNodes.length,
    droppedEdgeCount: droppedEdgeEvents,
  };
};
