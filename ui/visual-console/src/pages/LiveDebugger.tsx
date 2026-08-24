import React, { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { 
  ReactFlow, Controls, Background, useNodesState, useEdgesState 
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Sparkles, AlertTriangle, CheckCircle2
} from 'lucide-react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import dagre from 'dagre';

interface LogEvent {
  event: string;
  timestamp: string;
  run_id?: string;
  scenario_node_id?: string;
  execution_instance_id?: string;
  parent_execution_id?: string | null;
  from_scenario_node_id?: string;
  to_scenario_node_id?: string;
  node_id?: string;
  subtask_id?: string;
  task_id?: string;
  task?: string;
  step?: string;
  message?: string;
  result?: string;
  category?: string;
  is_root_cause?: boolean;
  _seq?: number;
  turn?: number;
  status?: string;
  attempt?: number;
  duration_ms?: number;
  failure_class?: string;
  failure_reason?: string;
  edge_type?: string;
}

// ---------------------------------------------------------------------------
// [B2] Compositional trace-integrity flags.
//
// Each condition is reported independently — detecting one NEVER downgrades or
// masks another (e.g. a trace recovered from the master log still reports its
// sequence gaps alongside RECOVERED instead of collapsing into a single state).
// ---------------------------------------------------------------------------

export interface TraceIntegrityFlags {
  hasEvents: boolean;
  recovered: boolean;
  gaps: boolean;
  reordered: boolean;
  missingStart: boolean;
  missingEnd: boolean;
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
      issues: ['No events received.'],
    };
  }

  const issues: string[] = [];
  const seqs = events.map(e => Number(e._seq)).filter(n => !Number.isNaN(n));

  let reordered = false;
  let gaps = false;

  if (seqs.length === 0) {
    issues.push('Events lack server-assigned _seq identifiers.');
  } else {
    const sorted = [...seqs].sort((a, b) => a - b);
    const uniq = Array.from(new Set(sorted));

    // Arrival-order violation (retransmission/replay artifacts).
    reordered = seqs.some((v, i) => i > 0 && v < seqs[i - 1]);
    if (reordered) {
      issues.push('Events arrived out of monotonic _seq order (client-side reorder buffer applied).');
    }

    // Coverage holes or duplicate frames — independent of arrival order.
    gaps =
      uniq[uniq.length - 1] - uniq[0] + 1 !== uniq.length ||
      uniq.length !== sorted.length;
    if (gaps) {
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

  const recovered = !!sourcedFromMaster;
  if (recovered) {
    issues.push('Trace recovered from master log — per-run stream was incomplete.');
  }

  const hasStart = events.some(e => e.event === 'run_start');
  const hasEnd = events.some(e => e.event === 'run_end');
  const missingStart = !hasStart;
  const missingEnd = !hasEnd;
  if (missingEnd) issues.push('Missing terminal run_end event.');
  else if (missingStart) issues.push('Missing run_start event.');

  return { hasEvents: true, recovered, gaps, reordered, missingStart, missingEnd, issues };
};

// ---------------------------------------------------------------------------
// [B4] Typed telemetry taxonomy — the zoom levels select from an explicit
// event-name taxonomy instead of fragile substring matching.
// ---------------------------------------------------------------------------

type TelemetryLevel = 'PHASE' | 'SUBTASK' | 'ACTION' | 'STEP';

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
  return events.filter(e => taxonomy.has(e.event));
};

// ---------------------------------------------------------------------------
// [B3] Telemetry diagnostics — heuristic status inference is quarantined here.
//
// String/status heuristics over generic telemetry NEVER drive the execution
// graph. They are surfaced exclusively in a clearly-labeled non-authoritative
// diagnostics panel, and only for nodes lacking authoritative
// execution_graph_node coverage.
// ---------------------------------------------------------------------------

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
  const seen = new Set<string>();

  // Nodes with authoritative canonical coverage are excluded: their status is
  // already runtime-authoritative and requires no heuristic assistance.
  const canonicallyCovered = new Set(
    allEvents
      .filter(e => e.event === 'execution_graph_node')
      .map(e => e.scenario_node_id)
      .filter((id): id is string => !!id)
  );

  for (const ev of allEvents) {
    const nodeId = resolveTelemetryNodeId(ev);
    if (!nodeId || seen.has(nodeId) || canonicallyCovered.has(nodeId)) continue;

    const group = allEvents.filter(
      e =>
        e.event !== 'execution_graph_node' &&
        resolveTelemetryNodeId(e) === nodeId
    );
    seen.add(nodeId);

    const signals: string[] = [];
    let suspectedStatus: NodeDiagnostic['suspectedStatus'] | undefined;

    if (group.some(e =>
      e.event === 'error' ||
      e.category === 'PARITY_STATE_DIVERGENCE' ||
      (e.status && e.status.toLowerCase() === 'failed') ||
      e.message?.toLowerCase().includes('error') ||
      e.message?.toLowerCase().includes('fail')
    )) {
      suspectedStatus = 'failed';
      signals.push('error/failure signal in generic telemetry');
    } else if (group.some(e =>
      (e.status && e.status.toLowerCase() === 'completed') ||
      e.event === 'maneuver_end' ||
      e.event === 'node_end' ||
      e.result === 'success'
    )) {
      suspectedStatus = 'completed';
      signals.push('completion signal in generic telemetry');
    } else if (group.some(e =>
      (e.status && e.status.toLowerCase() === 'running') ||
      e.event === 'node_start' ||
      e.event === 'maneuver_start'
    )) {
      suspectedStatus = 'running';
      signals.push('activity signal in generic telemetry');
    }

    if (suspectedStatus) {
      const firstMatch = group.find(e => resolveTelemetryNodeId(e) === nodeId);
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

export const LiveDebugger: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdParam = searchParams.get('run_id');

  const [runId, setRunId] = useState(runIdParam || '');
  const [runsList, setRunsList] = useState<string[]>([]);
  const [status, setStatus] = useState<string>('IDLE');
  const [sourcedFromMaster, setSourcedFromMaster] = useState<boolean>(false);
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [filteredEvents, setFilteredEvents] = useState<LogEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<LogEvent | null>(null);
  
  // 4-level Telemetry controls
  const [telemetryLevel, setTelemetryLevel] = useState<'PHASE' | 'SUBTASK' | 'ACTION' | 'STEP'>('STEP');

  // [B1] Topology provenance authority — reported by buildTraceGraph.
  const [topologyProvenance, setTopologyProvenance] = useState<{
    source: 'CANONICAL' | 'TOPOLOGY_UNAVAILABLE';
    scenarioNodeCount: number;
    runtimeNodeCount: number;
  }>({ source: 'TOPOLOGY_UNAVAILABLE', scenarioNodeCount: 0, runtimeNodeCount: 0 });

  // [B3] Non-authoritative heuristic findings — rendered ONLY in the
  // diagnostics panel; never applied to graph node states.
  const [diagnostics, setDiagnostics] = useState<NodeDiagnostic[]>([]);

  // React Flow State
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [activeScenario, setActiveScenario] = useState<any>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
  
  // AI explain drawer
  const [explainResult, setExplainResult] = useState<string>('');
  const [showExplain, setShowExplain] = useState(false);
  const [analysisData, setAnalysisData] = useState<any>(null);

  // SSE connection resilience (NFR 8.1)
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTED' | 'CONNECTING' | 'RECONNECTING' | 'DISCONNECTED' | 'FINISHED'>('DISCONNECTED');
  const [reconnectCount, setReconnectCount] = useState(0);

  // SSE stream reference
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    // Load runs dropdown
    fetch('/api/runs')
      .then(res => res.json())
      .then(data => {
        const list = (data.runs || []).map((r: any) => r.run_id);
        setRunsList(list);
        if (!runId && list.length > 0) {
          setRunId(list[0]);
        }
      });
  }, []);

  // Run status checker — only responsible for status/scenario state.
  // Graph derivation is handled exclusively by the reactive useEffect below.
  const checkStatus = async (rid: string) => {
    try {
      const res = await fetch(`/api/v1/runs/${rid}`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status || 'COMPLETED');
        setSourcedFromMaster(!!data.sourced_from_master);
        if (data.scenario) {
          setActiveScenario(data.scenario);
        }
      }
    } catch (e) {
      setStatus('UNKNOWN');
      setSourcedFromMaster(false);
    }
  };

  // Independent scenario topology fetcher with exponential backoff retry
  // Decoupled from stream connect to close the race window against session startup
  const fetchScenarioWithRetry = async (rid: string, attempt = 0) => {
    try {
      const res = await fetch(`/api/v1/runs/${rid}`);
      if (res.ok) {
        const data = await res.json();
        if (data.scenario) {
          setActiveScenario(data.scenario);
          return;
        }
      }
      if (attempt < 5) {
        setTimeout(() => fetchScenarioWithRetry(rid, attempt + 1), 500 * (attempt + 1));
      }
    } catch (e) {
      if (attempt < 5) {
        setTimeout(() => fetchScenarioWithRetry(rid, attempt + 1), 500 * (attempt + 1));
      }
    }
  };

  const handleExplain = async () => {
    if (!runId) return;
    setShowExplain(true);
    setExplainResult('AI Engine analyzing evaluation traces...');
    setAnalysisData(null);
    try {
      const res = await fetch(`/api/v1/explain/${runId}`);
      const data = await res.json();
      if (res.ok) {
        let resultText = '';
        if (data.analysis && typeof data.analysis === 'object') {
          setAnalysisData(data.analysis);
          let confStr = 'N/A';
          if (data.analysis.confidence !== undefined && data.analysis.confidence !== null) {
            const confVal = Number(data.analysis.confidence);
            if (!isNaN(confVal)) {
              if (confVal <= 1.0) {
                confStr = `${Math.round(confVal * 100)}%`;
              } else {
                confStr = `${Math.round(confVal)}%`;
              }
            } else {
              confStr = String(data.analysis.confidence);
            }
          }
          resultText = `Root Cause Analysis:\n\n` +
            `• Root Cause: ${data.analysis.root_cause || 'Unknown'}\n` +
            `• Suggestion: ${data.analysis.suggestion || 'N/A'}\n` +
            `• Confidence: ${confStr}`;
        } else {
          resultText = data.analysis || 'Analysis complete. No loop or timeout patterns identified.';
        }
        setExplainResult(resultText);
      } else {
        setExplainResult(`Error: ${data.error || 'Failed to explain trace.'}`);
      }
    } catch (e: any) {
      setExplainResult(`Failed to trigger analysis: ${e.message}`);
    }
  };

  const handleIsolateRootCause = async () => {
    if (!runId) return;
    // [P0-11] Strict priority: authoritative flag > heuristic analysis index >
    // correlated-error heuristic. Whatever route matched is surfaced in the
    // UI as Confirmed vs Suspected — never collapsed into one label.
    let targetIdx = -1;

    // 1. Authoritative runtime designation
    targetIdx = events.findIndex(e => e.is_root_cause === true);

    // 2. Analyzer-provided index (heuristic)
    if (targetIdx < 0 && analysisData && analysisData.index !== undefined && analysisData.index >= 0) {
      targetIdx = analysisData.index;
    } else if (targetIdx < 0) {
      try {
        const res = await fetch(`/api/v1/explain/${runId}`);
        const data = await res.json();
        if (res.ok && data.analysis && data.analysis.index !== undefined) {
          setAnalysisData(data.analysis);
          targetIdx = data.analysis.index;
        }
      } catch (e) {
        console.error('Failed to isolate root cause via API:', e);
      }
    }

    // 3. First-correlated-failure heuristic (explicitly labeled as suspected)
    if (targetIdx < 0) {
      targetIdx = events.findIndex(e =>
        e.event === 'error' ||
        e.category === 'PARITY_STATE_DIVERGENCE' ||
        e.message?.toLowerCase().includes('error') ||
        e.message?.toLowerCase().includes('fail')
      );
    }
    if (targetIdx >= 0 && targetIdx < events.length) {
      setSelectedEvent(events[targetIdx]);
    }
  };

  // [P0-9][B2] Trace-integrity state derived from the authoritative event
  // stream. Compositional flags — no single state downgrade.
  const traceIntegrity: TraceIntegrityFlags = computeTraceIntegrity(events, sourcedFromMaster);

  const integrityLabel = (() => {
    if (!traceIntegrity.hasEvents) return 'UNKNOWN';
    const flags: string[] = [];
    if (traceIntegrity.recovered) flags.push('RECOVERED');
    if (traceIntegrity.reordered) flags.push('REORDERED');
    if (traceIntegrity.gaps) flags.push('PARTIAL');
    if (traceIntegrity.missingEnd) flags.push('NO_END');
    return flags.length ? flags.join('+') : 'COMPLETE';
  })();

  const integrityTone: 'clean' | 'recovered' | 'warn' | 'unknown' = (() => {
    if (!traceIntegrity.hasEvents) return 'unknown';
    if (traceIntegrity.gaps || traceIntegrity.reordered || traceIntegrity.missingEnd) return 'warn';
    if (traceIntegrity.recovered) return 'recovered';
    return 'clean';
  })();

  // Auto-expand Explain Panel if query param is set
  useEffect(() => {
    if (runId && searchParams.get('explain') === 'true') {
      handleExplain();
    }
  }, [runId, searchParams]);

  // Persistent Node Positions Cache to prevent coordinate jitter during telemetry stream
  const nodePositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const lastEventIdRef = useRef<number>(0);

  // Close stream helper
  const closeStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

  // Connect to SSE stream with auto-reconnect backoff (NFR 8.1) and Last-Event-ID catch-up replay
  const connectStream = (rid: string, attempt = 0) => {
    closeStream();
    if (attempt === 0) {
      setEvents([]);
      setSelectedEvent(null);
      setNodes([]);
      setEdges([]);
      nodePositionsRef.current.clear();
      lastEventIdRef.current = 0;
      setReconnectCount(0);
      setConnectionStatus('CONNECTING');
    } else {
      setConnectionStatus('RECONNECTING');
    }
    
    checkStatus(rid);
    fetchScenarioWithRetry(rid, 0);

    // Set query param preserving explain if it exists
    const nextParams: Record<string, string> = { run_id: rid };
    if (searchParams.get('explain') === 'true') {
      nextParams.explain = 'true';
    }
    setSearchParams(nextParams);

    // Server-Sent Events stream initialization with catchup cursor
    const lastId = lastEventIdRef.current;
    const streamUrl = `/api/v1/runs/${rid}/stream${lastId > 0 ? `?last_event_id=${lastId}` : ''}`;
    const source = new EventSource(streamUrl);
    eventSourceRef.current = source;

    source.onopen = () => {
      console.log(`SSE connection to ${rid} opened.`);
      setConnectionStatus('CONNECTED');
      setReconnectCount(0);
    };

    source.onmessage = (event) => {
      try {
        if (event.lastEventId) {
          lastEventIdRef.current = parseInt(event.lastEventId, 10) || lastEventIdRef.current;
        }
        const data: LogEvent = JSON.parse(event.data);
        if (data.event === 'timeout') {
          setStatus('STALLED');
          return;
        }
        if (data.event === 'not_found') {
          console.info('[LiveDebugger] Trace not ready yet:', data.message);
          setConnectionStatus('CONNECTING');
          return;
        }

        // Hydrate scenario topology directly from canonical event envelope if present
        if (data.event === 'run_start' || (data as any).name === 'run_start') {
          const inlineScenario = (data as any).scenario_data || (data as any).scenario_obj;
          const inlineWorkflow = (data as any).workflow;
          if (inlineScenario && typeof inlineScenario === 'object' && Object.keys(inlineScenario).length > 0) {
            setActiveScenario(inlineScenario);
          } else if (inlineWorkflow && typeof inlineWorkflow === 'object') {
            setActiveScenario((prev: any) => {
              if (prev?.workflow?.nodes?.length) return prev;
              return {
                id: (data as any).scenario || 'scenario',
                title: (data as any).scenario || 'Scenario',
                workflow: inlineWorkflow,
              };
            });
          }
        }

        // Append to events stream
        setEvents(prev => [...prev, data]);
      } catch (e) {
        console.error('Failed to parse SSE event data:', e);
      }
    };

    source.onerror = () => {
      console.warn('SSE stream encountered error or finished. Reconnecting/Closing.');
      closeStream();

      const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'ERROR']);

      fetch(`/api/v1/runs/${rid}`)
        .then(res => {
          if (!res.ok) {
            throw new Error(`Status check returned ${res.status}`);
          }
          return res.json();
        })
        .then(data => {
          const runStatus = data.status || 'UNKNOWN';
          setStatus(runStatus);
          setSourcedFromMaster(!!data.sourced_from_master);

          if (TERMINAL_STATUSES.has(runStatus)) {
            setConnectionStatus('FINISHED');
          } else {
            if (attempt < 8) {
              const backoffTime = Math.min(10000, Math.pow(2, attempt) * 1000);
              setReconnectCount(attempt + 1);
              setTimeout(() => {
                connectStream(rid, attempt + 1);
              }, backoffTime);
            } else {
              setConnectionStatus('DISCONNECTED');
            }
          }
        })
        .catch(() => {
          if (attempt < 8) {
            const backoffTime = Math.min(10000, Math.pow(2, attempt) * 1000);
            setReconnectCount(attempt + 1);
            setTimeout(() => connectStream(rid, attempt + 1), backoffTime);
          } else {
            setConnectionStatus('DISCONNECTED');
          }
        });
    };
  };

  useEffect(() => {
    if (runId) {
      connectStream(runId);
    }
    return () => closeStream();
  }, [runId]);

  // [B1][B3] Canonical Graph Builder — provenance-gated (Runtime-Authoritative
  // Truth Model).
  //
  // Node topology is constructed ONLY from canonical sources:
  //   1. The scenario workflow definition (design-time DAG), and/or
  //   2. Authoritative `execution_graph_node` runtime events.
  // Generic telemetry (tool_call, node_start/end, maneuvers, free-text errors)
  // can NEVER fabricate topology, and node status derives SOLELY from
  // execution_graph_node events. Heuristic inference lives exclusively in the
  // non-authoritative Telemetry Diagnostics panel.
  const buildTraceGraph = (
    allEvents: LogEvent[],
    scen: any,
    selection: LogEvent | null
  ): {
    flowNodes: any[];
    flowEdges: any[];
    provenance: 'CANONICAL' | 'TOPOLOGY_UNAVAILABLE';
    scenarioNodeCount: number;
    runtimeNodeCount: number;
  } => {
    const positions = nodePositionsRef.current;

    // 1. Canonical sources only.
    const scenarioNodesRaw = scen?.workflow?.nodes || scen?.workflow?.tasks || [];
    const workflowEdges = scen?.workflow?.edges || [];

    const graphNodeEventsAll = allEvents.filter(e => e.event === 'execution_graph_node');
    const seenRuntimeIds = new Set<string>();
    const runtimeDiscoveredNodes: any[] = [];
    for (const ev of graphNodeEventsAll) {
      const id = ev.scenario_node_id;
      if (!id || seenRuntimeIds.has(id)) continue;
      seenRuntimeIds.add(id);
      const inScenario = scenarioNodesRaw.some(
        (n: any) => String(n.id || n.scenario_node_id || n.task_id) === id
      );
      if (!inScenario) {
        runtimeDiscoveredNodes.push({ id, task_description: id, __runtime_discovered: true });
      }
    }

    const workflowNodes = [...scenarioNodesRaw, ...runtimeDiscoveredNodes];

    if (workflowNodes.length === 0) {
      return {
        flowNodes: [],
        flowEdges: [],
        provenance: 'TOPOLOGY_UNAVAILABLE',
        scenarioNodeCount: 0,
        runtimeNodeCount: 0,
      };
    }

    // 2. Map authoritative state per canonical node — status comes SOLELY from
    // execution_graph_node events (B3). No string heuristics.
    const flowNodes = workflowNodes.map((n: any) => {
      const id = String(n.id || n.scenario_node_id || n.task_id);
      const label = n.task_description || n.description || n.label || id;

      const graphNodeEvents = graphNodeEventsAll.filter(e => e.scenario_node_id === id);

      let status = 'pending';
      let hasCanonicalEvent = false;
      let failureClass: string | undefined;
      let failureReason: string | undefined;
      let durationMs: number | undefined;
      let maxAttempt = 1;

      if (graphNodeEvents.length > 0) {
        const latestEv = graphNodeEvents[graphNodeEvents.length - 1];
        if (latestEv.status) {
          status = latestEv.status.toLowerCase();
        }
        failureClass = latestEv.failure_class;
        failureReason = latestEv.failure_reason;
        durationMs = latestEv.duration_ms;
        const attempts = graphNodeEvents.map(e => e.attempt || 1);
        maxAttempt = attempts.length > 0 ? Math.max(...attempts) : 1;
        hasCanonicalEvent = true;
      }

      // Selection matching: join on scenario_node_id
      const selectedId = selection?.scenario_node_id || selection?.node_id || selection?.task_id;
      const isHighlighted = !!selectedId && selectedId === id;

      let border = isHighlighted ? '2px solid #818cf8' : '1px solid #334155';
      let background = '#0f172a';
      let statusLabel = 'Pending';

      if (status === 'failed' || status === 'error' || status === 'aborted') {
        border = isHighlighted ? '2px solid #f87171' : '1px solid #ef4444';
        background = 'rgba(127,29,29,0.4)';
        statusLabel = failureClass || failureReason || 'Failed';
      } else if (status === 'completed') {
        border = isHighlighted ? '2px solid #34d399' : '1px solid #10b981';
        background = 'rgba(6,78,59,0.4)';
        statusLabel = 'Completed';
      } else if (status === 'running') {
        border = isHighlighted ? '2px solid #fbbf24' : '1px solid #f59e0b';
        background = 'rgba(120,53,15,0.4)';
        statusLabel = 'Running';
      }

      return {
        id,
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-mono font-bold text-[10px] text-slate-200">{id}</span>
                {maxAttempt > 1 && (
                  <span className="px-1 py-0.2 bg-amber-500/20 text-amber-300 text-[8px] rounded font-mono">
                    att#{maxAttempt}
                  </span>
                )}
              </div>
              <div className="text-[9px] text-slate-400 truncate max-w-[130px]" title={label}>
                {statusLabel}
              </div>
              {!hasCanonicalEvent && (
                <div
                  title="No execution_graph_node event recorded for this node yet — status is PENDING by definition, not inferred."
                  className="px-1 py-0.2 bg-slate-800/60 text-slate-500 text-[8px] rounded tracking-wider uppercase"
                >
                  NO GRAPH EVENT
                </div>
              )}
              {durationMs && (
                <div className="text-[8px] text-slate-500 font-mono">
                  {(durationMs / 1000).toFixed(2)}s
                </div>
              )}
            </div>
          )
        },
        style: {
          background,
          color: '#fff',
          border,
          borderRadius: '8px',
          padding: '8px',
          width: 170,
          boxShadow: isHighlighted
            ? '0 0 15px rgba(99, 102, 241, 0.7), inset 0 0 0 1px rgba(129, 140, 248, 0.5)'
            : 'none',
          transition: 'box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease'
        }
      };
    });

    // 3. Edges: Combine Scenario Workflow Edges + Runtime Execution Graph Edge Telemetry
    const nodeIdSet = new Set(flowNodes.map((n: any) => n.id));
    const flowEdgesMap = new Map<string, any>();

    // Initial edges from workflow definition
    workflowEdges.forEach((e: any) => {
      const source = e.from || e.source;
      const target = e.to || e.target;
      if (nodeIdSet.has(source) && nodeIdSet.has(target)) {
        const edgeId = `scen-edge-${source}-${target}`;
        flowEdgesMap.set(edgeId, {
          id: edgeId,
          source,
          target,
          animated: true,
          style: { stroke: '#6366f1', strokeWidth: 2 }
        });
      }
    });

    // Decorate with runtime execution_graph_edge events
    const graphEdgeEvents = allEvents.filter(e => e.event === 'execution_graph_edge');
    graphEdgeEvents.forEach((e: any) => {
      const source = e.from_scenario_node_id || e.source_execution_id || e.source;
      const target = e.to_scenario_node_id || e.target_execution_id || e.target;
      if (source && target && nodeIdSet.has(source) && nodeIdSet.has(target)) {
        const edgeId = `exec-edge-${source}-${target}`;
        flowEdgesMap.set(edgeId, {
          id: edgeId,
          source,
          target,
          label: e.edge_type === 'retry' ? 'retry' : e.edge_type === 'conditional' ? 'if' : undefined,
          animated: true,
          style: {
            stroke: e.edge_type === 'retry' ? '#f59e0b' : '#6366f1',
            strokeWidth: 2,
            strokeDasharray: e.edge_type === 'retry' ? '5,5' : undefined
          }
        });
      }
    });

    const flowEdges = Array.from(flowEdgesMap.values());

    // 4. Dagre Topology Layout (Preserves manual user drag coordinates)
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 80 });

    const nodeWidth = 180;
    const nodeHeight = 70;

    flowNodes.forEach((node: any) => {
      dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
    });

    flowEdges.forEach((edge: any) => {
      dagreGraph.setEdge(edge.source, edge.target);
    });

    dagre.layout(dagreGraph);

    const layoutedNodes = flowNodes.map((node: any, index: number) => {
      const savedPos = positions.get(node.id);
      if (savedPos) {
        return { ...node, position: savedPos };
      }
      const nodeWithPosition = dagreGraph.node(node.id);
      const x = nodeWithPosition ? nodeWithPosition.x - nodeWidth / 2 + 80 : 80 + index * 220;
      const y = nodeWithPosition ? nodeWithPosition.y - nodeHeight / 2 + 50 : 50;
      const pos = { x, y };
      positions.set(node.id, pos);
      return { ...node, position: pos };
    });

    return {
      flowNodes: layoutedNodes,
      flowEdges,
      provenance: 'CANONICAL',
      scenarioNodeCount: scenarioNodesRaw.length,
      runtimeNodeCount: runtimeDiscoveredNodes.length,
    };
  };

  // Node Drag Position Saver to ensure layout state persistence
  const handleNodeDragStop = (_: any, node: any) => {
    if (node && node.id && node.position) {
      nodePositionsRef.current.set(node.id, { x: node.position.x, y: node.position.y });
    }
  };

  useEffect(() => {
    const result = buildTraceGraph(events, activeScenario, selectedEvent);
    setNodes(result.flowNodes);
    setEdges(result.flowEdges);
    setTopologyProvenance({
      source: result.provenance,
      scenarioNodeCount: result.scenarioNodeCount,
      runtimeNodeCount: result.runtimeNodeCount,
    });
    // [B3] Heuristic findings are computed for the diagnostics panel only.
    setDiagnostics(computeTelemetryDiagnostics(events));
  }, [events, activeScenario, selectedEvent]);


  // [B4] Filter events by selected telemetry level via typed taxonomy
  useEffect(() => {
    setFilteredEvents(filterEventsByTelemetryLevel(events, telemetryLevel));
  }, [events, telemetryLevel]);

  // Dynamically fit view when nodes are updated
  useEffect(() => {
    if (reactFlowInstance && nodes.length > 0) {
      const timer = setTimeout(() => {
        reactFlowInstance.fitView({ padding: 0.2, duration: 400 });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [nodes.length, reactFlowInstance]);

  // Focus and zoom on selected node from timeline selection
  useEffect(() => {
    if (selectedEvent && reactFlowInstance) {
      const nodeId = selectedEvent.scenario_node_id || selectedEvent.node_id || selectedEvent.task_id;
      if (nodeId) {
        const targetNode = nodes.find(n => n.id === nodeId);
        if (targetNode) {
          const { x, y } = targetNode.position;
          const currentZoom = reactFlowInstance.getZoom ? reactFlowInstance.getZoom() : 1.0;
          const targetZoom = Math.min(currentZoom, 1.15);
          reactFlowInstance.setCenter(x + 80, y + 40, { zoom: targetZoom, duration: 400 });
        }
      }
    }
  }, [selectedEvent, reactFlowInstance, nodes]);

  // Selection highlighting is now handled inside buildTraceGraph() via the
  // reactive useEffect([events, activeScenario, selectedEvent]) above.
  // The separate style-patch effect has been removed — it is no longer needed.

  const hasError = events.some(e => 
    e.event === 'error' || 
    e.category === 'PARITY_STATE_DIVERGENCE' || 
    e.message?.toLowerCase().includes('error') || 
    e.message?.toLowerCase().includes('fail')
  );

  return (
    <div className="flex h-[calc(100vh-56px)] bg-navy-base text-slate-100 overflow-hidden">
      {/* Sidebar - Timeline Logs & Scrubbing */}
      <div className="w-80 border-r border-slate-900 flex flex-col bg-slate-950/20 shrink-0">
        <div className="p-4 border-b border-slate-900 space-y-3">
          <div className="space-y-1">
            <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Inspect Trace Run:</label>
            <select
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            >
              {runsList.map(rid => (
                <option key={rid} value={rid}>{rid}</option>
              ))}
            </select>
          </div>

          {/* 4-level Telemetry switcher */}
          <div className="space-y-1">
            <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Telemetry Zoom:</label>
            <div className="grid grid-cols-4 bg-slate-950 border border-slate-900 rounded p-0.5 text-center text-[9px] font-bold">
              {(['PHASE', 'SUBTASK', 'ACTION', 'STEP'] as const).map(lvl => (
                <button
                  key={lvl}
                  onClick={() => setTelemetryLevel(lvl)}
                  className={`py-1 rounded uppercase tracking-wider ${
                    telemetryLevel === lvl ? 'bg-slate-900 text-indigo-400' : 'text-slate-500 hover:text-slate-400'
                  }`}
                >
                  {lvl}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Timeline event feed */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {filteredEvents.length === 0 ? (
            <p className="text-xs text-slate-500 italic p-2">Waiting for telemetry stream...</p>
          ) : (
            filteredEvents.map((evt, idx) => {
              const isSelected = selectedEvent === evt;
              const isError = evt.event === 'error' || evt.category === 'PARITY_STATE_DIVERGENCE';
              const eventIndexInMain = events.indexOf(evt);
              const isRootCauseIndex = analysisData && eventIndexInMain === analysisData.index;
              return (
                <button
                  key={idx}
                  onClick={() => setSelectedEvent(evt)}
                  className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all flex items-start gap-2.5 ${
                    isSelected 
                      ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300 ring-2 ring-indigo-500/50' 
                      : isRootCauseIndex
                        ? 'bg-rose-950/40 border-rose-500/50 text-rose-200 ring-1 ring-rose-500/30'
                        : isError 
                          ? 'bg-red-500/5 border-red-500/20 text-red-400'
                          : 'bg-slate-950/60 border-slate-900 text-slate-350 hover:bg-slate-900/40'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                    isRootCauseIndex ? 'bg-rose-500' : isError ? 'bg-red-500' : 'bg-indigo-500'
                  }`} />
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono">
                      <span className="uppercase font-bold tracking-wider text-indigo-400">
                        {evt.event} (Seq #{evt._seq}{evt.turn !== undefined ? `, Turn ${evt.turn}` : ''})
                      </span>
                      <div className="flex items-center gap-1.5">
                        {/* [P0-11] RCA confidence labeling: authoritative runtime
                            designation vs heuristic inference are never collapsed. */}
                        {evt.is_root_cause === true && (
                          <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 text-[8px] font-bold tracking-wider uppercase shrink-0">
                            🔴 Root Cause (Confirmed)
                          </span>
                        )}
                        {!evt.is_root_cause && isRootCauseIndex && (
                          <span
                            title="Inferred by the analysis heuristic — not an authoritative runtime designation."
                            className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[8px] font-bold tracking-wider uppercase shrink-0"
                          >
                            ⚠ Root Cause (Suspected)
                          </span>
                        )}
                        <span>{evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ''}</span>
                      </div>
                    </div>
                    <p className="font-mono text-[10px] truncate leading-tight">
                      {evt.message || evt.task || evt.step || 'Event trigger'}
                    </p>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Center - Visual Canvas */}
      <div className="flex-1 flex flex-col bg-navy-base relative min-w-0">
        {/* Header toolbar */}
        <div className="h-14 border-b border-slate-900 bg-slate-950/20 px-6 flex items-center justify-between shrink-0 text-xs">
          <div className="flex items-center gap-3">
            {/* [B1] Topology provenance authority chip */}
            <div
              title={
                topologyProvenance.source === 'CANONICAL'
                  ? `Topology reconstructed from canonical sources only: ${topologyProvenance.scenarioNodeCount} scenario node(s), ${topologyProvenance.runtimeNodeCount} runtime-discovered node(s) (execution_graph_node events).`
                  : 'No canonical workflow definition and no execution_graph_node events were found for this trace. Generic telemetry cannot fabricate topology.'
              }
              className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border font-mono text-[10px] font-bold uppercase tracking-wider cursor-help ${
                topologyProvenance.source === 'CANONICAL'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-300 animate-pulse'
              }`}
            >
              {topologyProvenance.source === 'CANONICAL' ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : (
                <AlertTriangle className="w-3.5 h-3.5" />
              )}
              Topology: {topologyProvenance.source === 'CANONICAL' ? 'CANONICAL' : 'TOPOLOGY_UNAVAILABLE'}
            </div>
            {/* [P0-9][B2] Prominent compositional trace-integrity state */}
            <div
              title={traceIntegrity.issues.join('\n') || 'Trace integrity verified.'}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border font-mono text-[10px] font-bold uppercase tracking-wider cursor-help ${
                integrityTone === 'clean'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : integrityTone === 'recovered'
                    ? 'border-violet-500/30 bg-violet-500/10 text-violet-300'
                    : integrityTone === 'unknown'
                      ? 'border-slate-700 bg-slate-900 text-slate-400'
                      : 'border-amber-500/30 bg-amber-500/10 text-amber-300'
              }`}
            >
              {integrityTone === 'clean' || integrityTone === 'recovered' ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : (
                <AlertTriangle className="w-3.5 h-3.5" />
              )}
              Trace: {integrityLabel}
            </div>
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Runner Status:</span>
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
              <span className={`w-2.5 h-2.5 rounded-full ${
                status === 'RUNNING' ? 'bg-amber-500 animate-pulse' :
                status === 'COMPLETED' ? 'bg-emerald-500' : 'bg-red-500'
              }`} />
              <span className={status === 'RUNNING' ? 'text-amber-400' : status === 'COMPLETED' ? 'text-emerald-400' : 'text-red-400'}>
                {status}
              </span>
            </div>

            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider ml-4">Stream:</span>
            <div className="flex items-center gap-1.5">
              <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${
                connectionStatus === 'CONNECTED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                connectionStatus === 'CONNECTING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse' :
                connectionStatus === 'RECONNECTING' ? 'bg-red-500/10 text-red-400 border-red-500/20 animate-pulse' :
                connectionStatus === 'FINISHED' ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' :
                'bg-slate-500/10 text-slate-400 border-slate-500/20'
              }`}>
                {connectionStatus === 'RECONNECTING' ? `RECONNECTING (${reconnectCount}/5)` : connectionStatus}
              </span>
              {connectionStatus !== 'CONNECTED' && connectionStatus !== 'FINISHED' && (
                <button
                  onClick={() => connectStream(runId)}
                  className="px-2 py-0.5 bg-indigo-600/20 hover:bg-indigo-600/40 border border-indigo-500/30 rounded text-[9px] font-mono text-indigo-300 font-bold uppercase tracking-wider transition-colors cursor-pointer"
                >
                  Reconnect
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {hasError && (
              <button
                onClick={handleIsolateRootCause}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-950/40 border border-rose-900 hover:border-rose-700 rounded text-rose-350 hover:text-rose-200 transition-colors font-bold uppercase tracking-wider cursor-pointer"
              >
                <AlertTriangle className="w-3.5 h-3.5 text-rose-500 animate-pulse" />
                <span>Isolate Root Cause</span>
              </button>
            )}
            <button
              onClick={handleExplain}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-950 border border-slate-900 rounded text-slate-400 hover:text-slate-200 transition-colors font-bold uppercase tracking-wider"
            >
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>AI Explain Diagnostics</span>
            </button>
          </div>
        </div>

        {sourcedFromMaster && (
          <div className="bg-indigo-500/5 border-b border-slate-900 px-6 py-2.5 flex items-center gap-2 text-[10px] text-indigo-400 font-medium leading-relaxed italic shrink-0">
            <span className="w-1.5 h-1.5 bg-indigo-500 rounded-full shrink-0 animate-pulse" />
            <span>Notice: Individual vaults/files are not available for this run. Data is retrieved from the master log repository (runs/run.jsonl).</span>
          </div>
        )}

        {/* ReactFlow Canvas container */}
        <div className="flex-1 h-full bg-slate-950/20 relative">
          {/* [B1] Explicit TOPOLOGY_UNAVAILABLE state — no synthetic graph is fabricated. */}
          {topologyProvenance.source === 'TOPOLOGY_UNAVAILABLE' && (
            <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
              <div className="max-w-md p-6 border border-amber-500/30 bg-slate-950/95 rounded-xl text-center space-y-2 shadow-2xl">
                <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto" />
                <h3 className="font-bold uppercase tracking-wider text-amber-300 text-sm">
                  TOPOLOGY_UNAVAILABLE
                </h3>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  No canonical topology could be reconstructed for this trace.
                  A graph requires the scenario workflow definition or at least
                  one authoritative <span className="font-mono text-slate-300">execution_graph_node</span> event.
                  Generic telemetry cannot fabricate topology (Runtime-Authoritative Truth Model).
                </p>
              </div>
            </div>
          )}
          <style>{`
            .react-flow__handle {
              opacity: 0 !important;
              pointer-events: none !important;
            }
            .react-flow__controls-button {
              background: #0f172a !important;
              border-bottom: 1px solid #1e293b !important;
              color: #f1f5f9 !important;
              fill: #f1f5f9 !important;
            }
            .react-flow__controls-button:hover {
              background: #1e293b !important;
            }
            .react-flow__controls-button svg {
              fill: #f1f5f9 !important;
              stroke: #f1f5f9 !important;
            }
          `}</style>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeDragStop={handleNodeDragStop}
            onInit={setReactFlowInstance}
            fitView
          >

            <Background color="#334155" gap={16} />
            <Controls />
          </ReactFlow>
        </div>
      </div>

      {/* Right Side - Diagnostics + State Parity Inspector */}
      <div className="w-96 border-l border-slate-900 bg-slate-950/30 overflow-y-auto p-5 space-y-4 shrink-0 text-xs flex flex-col justify-between h-full">
        <div className="space-y-4 overflow-y-auto">
          <h3 className="font-bold text-slate-400 uppercase tracking-wider text-[10px]">State Parity Inspector</h3>

          {/* [B3] Non-authoritative telemetry diagnostics — heuristic findings
              are quarantined here and never drive the execution graph. */}
          {diagnostics.length > 0 && (
            <div className="space-y-2 border border-sky-500/20 bg-sky-500/5 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <h4 className="font-bold uppercase tracking-wider text-[10px] text-sky-300">
                  Telemetry Diagnostics
                </h4>
                <span className="px-1.5 py-0.5 rounded bg-sky-500/15 text-sky-300 border border-sky-500/30 text-[8px] font-bold tracking-wider uppercase">
                  TELEMETRY-INFERRED · NON-AUTHORITATIVE
                </span>
              </div>
              <p className="text-[9px] text-slate-500 leading-relaxed">
                Heuristic signals from generic telemetry. These NEVER alter graph
                node states — canonical execution_graph_node events remain the sole
                status authority.
              </p>
              {diagnostics.map(d => (
                <button
                  key={d.nodeId}
                  onClick={() => {
                    const target = events.find(e => e._seq === d.firstMatchingSeq);
                    if (target) setSelectedEvent(target);
                  }}
                  title={d.signals.join('; ')}
                  className="w-full text-left p-2 rounded bg-slate-950/70 border border-slate-900 hover:border-sky-500/40 transition-colors space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-[10px] text-slate-200">{d.nodeId}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider ${
                        d.suspectedStatus === 'failed'
                          ? 'bg-red-500/15 text-red-300 border border-red-500/30'
                          : d.suspectedStatus === 'completed'
                            ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                            : 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                      }`}
                    >
                      suspected: {d.suspectedStatus}
                    </span>
                  </div>
                  <p className="text-[9px] text-slate-500 truncate">{d.signals.join('; ')}</p>
                </button>
              ))}
            </div>
          )}
          
          {selectedEvent ? (
            <div className="space-y-3">
              <div className="p-3 bg-slate-950/60 border border-slate-850 rounded-lg space-y-1">
                <span className="text-[10px] text-slate-500 font-bold uppercase font-mono">Event Type</span>
                <p className="text-white font-mono font-bold text-xs uppercase">{selectedEvent.event}</p>
              </div>

              {selectedEvent.category === 'PARITY_STATE_DIVERGENCE' || (selectedEvent as any).expected_state || (selectedEvent as any).divergence ? (
                <div className="space-y-2">
                  <div className="p-2.5 bg-red-500/5 border border-red-500/10 rounded-lg flex gap-2 text-red-400">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <h4 className="text-xs font-bold uppercase tracking-wider">State Divergence Detected</h4>
                      <p className="text-[10px] leading-relaxed">The returned runtime state does not match the expectations defined in the execution manifest.</p>
                    </div>
                  </div>

                  {/* Side-by-side Diff rendering authentic telemetry evidence */}
                  <div className="border border-slate-850 rounded-lg overflow-hidden bg-slate-950 text-[10px]">
                    <ReactDiffViewer
                      oldValue={JSON.stringify(
                        (selectedEvent as any).expected_state ??
                        (selectedEvent as any).expected ??
                        (selectedEvent as any).previous_state ??
                        (selectedEvent as any).divergence?.expected ??
                        { expected: selectedEvent.message || "Expected Outcome" },
                        null,
                        2
                      )}
                      newValue={JSON.stringify(
                        (selectedEvent as any).actual_state ??
                        (selectedEvent as any).actual ??
                        (selectedEvent as any).current_state ??
                        (selectedEvent as any).divergence?.actual ??
                        (selectedEvent as any).result ??
                        selectedEvent,
                        null,
                        2
                      )}
                      splitView={false}
                      useDarkTheme={true}
                      styles={{
                        variables: {
                          dark: {
                            diffViewerBackground: '#020617',
                            diffViewerColor: '#cbd5e1',
                            addedBackground: '#064e3b',
                            removedBackground: '#7f1d1d'
                          }
                        }
                      }}
                    />
                  </div>
                </div>

              ) : (
                <div className="space-y-2">
                  <span className="text-slate-400 font-semibold">Event Parameters JSON:</span>
                  <pre className="bg-slate-950 p-4 rounded-lg border border-slate-850 text-[10px] text-slate-300 font-mono leading-relaxed overflow-x-auto select-all max-h-[220px]">
                    {JSON.stringify(selectedEvent, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <p className="text-slate-500 italic py-4">Select an event from the timeline feed to inspect detailed environment state parity.</p>
          )}
        </div>
      </div>

      {/* AI diagnostics explain drawer overlay */}
      {showExplain && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex justify-end">
          <div className="bg-slate-900 border-l border-slate-800 w-full max-w-xl h-full p-6 flex flex-col justify-between text-slate-100 shadow-2xl animate-slide-in">
            <div className="space-y-4 overflow-y-auto flex-1 pr-2">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-indigo-400" />
                <h3 className="text-base font-bold text-white uppercase tracking-wider">AI Diagnostics Trace Explainer</h3>
              </div>
              <p className="text-slate-400 text-xs leading-relaxed">
                Analyzing cryptographic trace anchors and execution milestones to locate potential loops, logic hangs, and state overrides.
              </p>
              
              <div className="p-4 bg-slate-950/60 border border-slate-850 rounded-lg text-xs leading-relaxed font-mono whitespace-pre-wrap leading-relaxed text-slate-350">
                {explainResult}
              </div>
            </div>

            <div className="flex justify-between items-center pt-4 border-t border-slate-800/60 shrink-0">
              {((analysisData?.index !== undefined && analysisData.index >= 0) || hasError) ? (
                <button
                  onClick={() => {
                    let targetIdx = analysisData?.index;
                    if (targetIdx === undefined || targetIdx < 0) {
                      targetIdx = events.findIndex(e => 
                        e.event === 'error' || 
                        e.category === 'PARITY_STATE_DIVERGENCE' || 
                        e.message?.toLowerCase().includes('error') || 
                        e.message?.toLowerCase().includes('fail')
                      );
                    }
                    if (targetIdx >= 0 && targetIdx < events.length) {
                      setSelectedEvent(events[targetIdx]);
                      setShowExplain(false);
                    }
                  }}
                  className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-xs text-white font-bold uppercase tracking-wider rounded-lg flex items-center gap-1.5 transition-colors cursor-pointer"
                >
                  <AlertTriangle className="w-3.5 h-3.5 animate-pulse" />
                  <span>Go to Root Cause Turn</span>
                </button>
              ) : null}
              <button
                onClick={() => setShowExplain(false)}
                className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 text-xs text-slate-350 font-bold uppercase tracking-wider ml-auto"
              >
                Close Analysis
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
