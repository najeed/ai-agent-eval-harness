/**
 * Pure telemetry, waterfall, and diagnostic logic for the LiveDebugger.
 * Fully decoupled from React DOM / CSS dependencies for pure unit testability.
 */

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
}

export const buildWaterfall = (
  allEvents: LogEvent[]
): { rows: WaterfallRow[]; tMin: number | null; tMax: number | null } => {
  const byExec = new Map<string, WaterfallRow>();
  for (const e of allEvents) {
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
    if (e.status) row.status = e.status;
    if (typeof e.duration_ms === 'number' && e.duration_ms > 0) row.durationMs = e.duration_ms;
    const ts = Date.parse(e.timestamp || '');
    if (!Number.isNaN(ts)) {
      if (e.status === 'running' && row.startTs === null) row.startTs = ts;
      row.endTs = row.endTs === null ? ts : Math.max(row.endTs, ts);
      if (row.startTs === null) row.startTs = ts;
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

  // Single O(N) pass to index events by nodeId and collect canonical nodes
  for (const e of allEvents) {
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
    if (group.some(e =>
      e.event === 'error' ||
      (e.event === 'evaluation' && e.status === 'failed') ||
      e.category === 'PARITY_STATE_DIVERGENCE' ||
      (e.status && e.status.toLowerCase() === 'failed')
    )) {
      suspectedStatus = 'failed';
      signals.push('structured error or failed verdict in telemetry');
    } else if (group.some(e =>
      (e.status && e.status.toLowerCase() === 'completed') ||
      e.event === 'maneuver_end' ||
      e.event === 'node_end' ||
      e.result === 'success'
    )) {
      suspectedStatus = 'completed';
      signals.push('completion signal in telemetry');
    } else if (group.some(e =>
      (e.status && e.status.toLowerCase() === 'running') ||
      e.event === 'node_start' ||
      e.event === 'maneuver_start'
    )) {
      suspectedStatus = 'running';
      signals.push('activity signal in telemetry');
    }

    if (suspectedStatus) {
      const firstMatch = group[0];
      diagnostics.push({
        nodeId,
        suspectedStatus,
        signals,
        firstMatchingSeq: firstMatch?._seq,
      });
    }
    if (diagnostics.length >= 50) break;
  }
  return diagnostics;
};
