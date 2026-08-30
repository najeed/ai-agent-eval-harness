import React, { useEffect, useState, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ReactFlow, Controls, Background, useNodesState, useEdgesState
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Sparkles, AlertTriangle, CheckCircle2, Layers, Crosshair, Maximize2
} from 'lucide-react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import dagre from 'dagre';
import { computeScenarioHash } from '../lib/aesDocument';

import {
  buildWaterfall,
  mergeSeqGap,
  computeTraceIntegrity,
  filterEventsByTelemetryLevel,
  computeTelemetryDiagnostics,
} from '../lib/debuggerLogic';
import type {
  LogEvent,
  WaterfallRow,
  SeqGap,
  TraceIntegrityFlags,
  NodeDiagnostic,
} from '../lib/debuggerLogic';



// ---------------------------------------------------------------------------
// Strict StateComparison contract. A divergence event carries a
// structured `state_comparison` object (expected / actual / comparison /
// assertions / source / timestamp) emitted by the runtime parity verifier.
// The debugger renders ONLY this object. Absence of the payload means NO
// structured comparison exists; message text is never reparsed into a diff.
// ---------------------------------------------------------------------------

export interface StateComparisonPayload {
  expected: unknown;
  actual: unknown;
  comparison?: Record<string, unknown>;
  assertions?: unknown[];
  source?: string;
  timestamp?: string;
}

export const parseStateComparison = (evt: unknown): StateComparisonPayload | null => {
  if (!evt || typeof evt !== 'object') return null;
  const sc = (evt as any).state_comparison;
  if (!sc || typeof sc !== 'object' || Array.isArray(sc)) return null;
  if (!('expected' in sc) || !('actual' in sc)) return null;
  return sc as StateComparisonPayload;
};



export const LiveDebugger: React.FC = () => {
  const [searchParams] = useSearchParams();
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

  // [B1] Topology provenance authority; reported by buildTraceGraph.
  const [topologyProvenance, setTopologyProvenance] = useState<{
    source: 'CANONICAL' | 'TOPOLOGY_UNAVAILABLE';
    scenarioNodeCount: number;
    runtimeNodeCount: number;
    droppedEdgeCount: number;
  }>({ source: 'TOPOLOGY_UNAVAILABLE', scenarioNodeCount: 0, runtimeNodeCount: 0, droppedEdgeCount: 0 });

  // Explicit graph layers. The planned graph (scenario DAG), the
  // executed graph (execution_graph_edge evidence) and the divergence overlay
  // (skipped planned nodes / unplanned executions) are DISTINCT views; the
  // runtime never blends them into one implied truth.
  type GraphLayerMode = 'planned' | 'executed' | 'divergence';
  const [layerMode, setLayerMode] = useState<GraphLayerMode>('executed');

  // [B3] Non-authoritative heuristic findings; rendered ONLY in the
  // diagnostics panel; never applied to graph node states.
  const [diagnostics, setDiagnostics] = useState<NodeDiagnostic[]>([]);

  // React Flow State
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [activeScenario, setActiveScenario] = useState<any>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);

  // Deterministic RCA drawer
  const [explainResult, setExplainResult] = useState<string>('');
  const [showExplain, setShowExplain] = useState(false);
  const [analysisData, setAnalysisData] = useState<any>(null);

  // Single cancellable stream controller. Exactly one EventSource and
  // at most one pending retry timer exist per run_id; every async continuation
  // is stale-guarded against run switches; terminal runs never schedule
  // retries (explicit FINISHED state). Replay resumption (cursor > 0) is a
  // distinct REPLAYING state so operators can tell catch-up from live.
  const [connectionStatus, setConnectionStatus] = useState<'CONNECTED' | 'CONNECTING' | 'RECONNECTING' | 'REPLAYING' | 'DISCONNECTED' | 'FINISHED'>('DISCONNECTED');
  const [reconnectCount, setReconnectCount] = useState(0);
  const [streamGaps, setStreamGaps] = useState<SeqGap[]>([]);

  interface StreamCtl {
    es: EventSource | null;
    timer: ReturnType<typeof setTimeout> | null;
    scenarioTimer: ReturnType<typeof setTimeout> | null;
    run: string | null;
    attempt: number;
  }
  const streamCtlRef = useRef<StreamCtl>({ es: null, timer: null, scenarioTimer: null, run: null, attempt: 0 });
  // Server-generated monotonic event ids: dedupe set + replay cursor.
  const seenSeqsRef = useRef<Set<number>>(new Set());
  const cursorRef = useRef<number>(0);

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

  // Run status checker; only responsible for status/scenario state.
  // Graph derivation is handled exclusively by the reactive useEffect below.
  // Every async continuation is stale-guarded: a response for a run the
  // operator already left can never enter state.
  const checkStatus = async (rid: string) => {
    try {
      const res = await fetch(`/api/v1/runs/${rid}`);
      if (streamCtlRef.current.run !== rid) return;
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status || 'COMPLETED');
        setSourcedFromMaster(!!data.sourced_from_master);
        if (data.scenario) {
          setActiveScenario(data.scenario);
        }
      }
    } catch (e) {
      if (streamCtlRef.current.run !== rid) return;
      setStatus('UNKNOWN');
      setSourcedFromMaster(false);
    }
  };

  // Independent scenario topology fetcher with exponential backoff retry.
  // Decoupled from stream connect to close the race window against session
  // startup; stale-guarded against run switches and capped attempts.
  const fetchScenarioWithRetry = async (rid: string, attempt = 0) => {
    const staleAfterFetch = () => streamCtlRef.current.run !== rid;
    try {
      const res = await fetch(`/api/v1/runs/${rid}`);
      if (!staleAfterFetch() && res.ok) {
        const data = await res.json();
        if (data.scenario) {
          setActiveScenario(data.scenario);
          return;
        }
      }
    } catch (e) {
      // fall through to retry scheduling
    }
    if (!staleAfterFetch() && attempt < 5) {
      const ctl = streamCtlRef.current;
      if (ctl.scenarioTimer) clearTimeout(ctl.scenarioTimer);
      ctl.scenarioTimer = setTimeout(() => {
        if (streamCtlRef.current.run === rid) fetchScenarioWithRetry(rid, attempt + 1);
      }, 500 * (attempt + 1));
    }
  };

  const handleExplain = async () => {
    if (!runId) return;
    setShowExplain(true);
    setExplainResult('Deterministic triage engine analyzing evaluation traces (rule-based, replayable — no LLM).');
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
          resultText = 'NO_ANALYSIS_AVAILABLE — the deterministic triage engine returned no analysis for this trace. No negative finding is inferred.';
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
    // UI as Confirmed vs Suspected; never collapsed into one label.
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

  // Trace-integrity state derived from the authoritative event
  // stream. Compositional flags; no single state downgrade.
  const traceIntegrity: TraceIntegrityFlags = computeTraceIntegrity(events, sourcedFromMaster);

  const integrityLabel = (() => {
    // ONE authoritative integrity state: live SSE gaps
    // participate in the verdict. An unreconciled gap can never coexist with
    // a green COMPLETE label.
    if (!traceIntegrity.hasEvents) return 'UNKNOWN';
    const flags: string[] = [];
    if (traceIntegrity.recovered) flags.push('RECOVERED');
    if (traceIntegrity.reordered) flags.push('REORDERED');
    if (traceIntegrity.gaps || streamGaps.length > 0) flags.push('PARTIAL');
    if (traceIntegrity.missingEnd) flags.push('NO_END');
    return flags.length ? flags.join('+') : 'COMPLETE';
  })();

  const integrityTone: 'clean' | 'recovered' | 'warn' | 'unknown' = (() => {
    if (!traceIntegrity.hasEvents) return 'unknown';
    if (
      traceIntegrity.gaps ||
      traceIntegrity.reordered ||
      traceIntegrity.missingEnd ||
      streamGaps.length > 0
    ) {
      return 'warn';
    }
    if (traceIntegrity.recovered) return 'recovered';
    return 'clean';
  })();

  // Auto-expand Explain Panel if query param is set
  useEffect(() => {
    if (runId && searchParams.get('explain') === 'true') {
      handleExplain();
    }
  }, [runId, searchParams]);

  // Persistent Node Positions Cache to prevent coordinate jitter during
  // telemetry stream. [Sprint-2] Keys are composite:
  //   `${run_id}::${scenario_hash}::${node_id}`
  // so changed topology or a different run can never resurrect stale
  // coordinates for a same-named node.
  const nodePositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const scenarioHash = useMemo(
    () => computeScenarioHash((activeScenario as any) ?? null),
    [activeScenario]
  );
  const posKey = (nodeId: string) => `${runId}::${scenarioHash}::${nodeId}`;

  const teardownStream = () => {
    const ctl = streamCtlRef.current;
    if (ctl.timer) {
      clearTimeout(ctl.timer);
      ctl.timer = null;
    }
    if (ctl.scenarioTimer) {
      clearTimeout(ctl.scenarioTimer);
      ctl.scenarioTimer = null;
    }
    if (ctl.es) {
      ctl.es.close();
      ctl.es = null;
    }
  };

  const resetRunLocalState = () => {
    setActiveScenario(null);
    setEvents([]);
    setSelectedEvent(null);
    setNodes([]);
    setEdges([]);
    cursorRef.current = 0;
    seenSeqsRef.current.clear();
    setStreamGaps([]);
    setReconnectCount(0);
  };

  const scheduleRetry = (rid: string) => {
    const ctl = streamCtlRef.current;
    if (ctl.attempt >= 8) {
      setConnectionStatus('DISCONNECTED');
      return;
    }
    const delay = Math.min(10000, Math.pow(2, ctl.attempt) * 1000);
    ctl.attempt += 1;
    setReconnectCount(ctl.attempt);
    // Catch-up with an existing cursor is a REPLAY, not a fresh connect.
    setConnectionStatus(cursorRef.current > 0 ? 'REPLAYING' : 'RECONNECTING');
    // At most ONE pending retry timer; it re-validates run identity before
    // firing, so a stale timer can never reopen a dead run's stream.
    ctl.timer = setTimeout(() => {
      if (streamCtlRef.current.run !== rid) return;
      streamCtlRef.current.timer = null;
      connectStream(rid);
    }, delay);
  };

  const connectStream = (rid: string) => {
    if (!rid) return;
    const ctl = streamCtlRef.current;
    const isNewRun = ctl.run !== rid;

    // Tear down ANY previous connection/timer before touching state: there is
    // never more than one live EventSource for this component.
    teardownStream();
    ctl.es = null;
    ctl.timer = null;
    ctl.attempt = 0;

    if (isNewRun) {
      ctl.run = rid;
      resetRunLocalState();
      // [Sprint-2] Prune layout cache entries belonging to other runs.
      for (const key of Array.from(nodePositionsRef.current.keys())) {
        if (!key.startsWith(`${rid}::`)) nodePositionsRef.current.delete(key);
      }
    }
    setConnectionStatus('CONNECTING');

    checkStatus(rid);
    fetchScenarioWithRetry(rid, 0);

    // Resume from the monotonic cursor; no URL rewriting inside the stream
    // lifecycle; the address bar only changes when the operator picks a run.
    const lastId = cursorRef.current;
    const source = new EventSource(
      `/api/v1/runs/${rid}/stream${lastId > 0 ? `?last_event_id=${lastId}` : ''}`
    );
    ctl.es = source;

    source.onopen = () => {
      if (streamCtlRef.current.es !== source) return;
      setConnectionStatus('CONNECTED');
      setReconnectCount(0);
    };

    source.onmessage = (event) => {
      // Stale-frame guard: frames from a superseded connection are dropped.
      if (streamCtlRef.current.run !== rid || streamCtlRef.current.es !== source) return;
      let data: LogEvent;
      try {
        data = JSON.parse(event.data);
        if (event.lastEventId) {
          data._seq = parseInt(event.lastEventId, 10) || data._seq;
        }
      } catch (e) {
        console.error('Failed to parse SSE event data:', e);
        return;
      }
      if (data.event === 'timeout') {
        setStatus('STALLED');
        return;
      }
      if (data.event === 'not_found') {
        console.info('[LiveDebugger] Trace not ready yet:', data.message);
        setConnectionStatus('CONNECTING');
        return;
      }

      // Dedupe + gap detection & reconciliation BEFORE an event may enter state.
      const seq = typeof data._seq === 'number' ? data._seq : 0;
      if (seq > 0) {
        if (seenSeqsRef.current.has(seq)) return;
        seenSeqsRef.current.add(seq);
        const prev = cursorRef.current;
        if (prev > 0 && seq > prev + 1) {
          setStreamGaps(g => mergeSeqGap(g, { from: prev + 1, to: seq - 1 }));
        } else {
          // Reconcile gap: If this incoming seq fills an existing gap range, update/remove it
          setStreamGaps(gaps => {
            if (!gaps.length) return gaps;
            return gaps
              .map(gap => {
                if (seq >= gap.from && seq <= gap.to) {
                  if (gap.from === gap.to) return null; // exact single-seq gap filled
                  if (seq === gap.from) return { from: gap.from + 1, to: gap.to };
                  if (seq === gap.to) return { from: gap.from, to: gap.to - 1 };
                  return gap;
                }
                return gap;
              })
              .filter(Boolean) as { from: number; to: number }[];
          });
        }
        if (seq > cursorRef.current) cursorRef.current = seq;
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

      setEvents(prevEvents => {
        const next = [...prevEvents, data];
        // Bounded client-side memory: keep sliding window up to 10,000 events
        return next.length > 10000 ? next.slice(-10000) : next;
      });
    };

    source.onerror = () => {
      if (streamCtlRef.current.run !== rid || streamCtlRef.current.es !== source) return;
      source.close();
      streamCtlRef.current.es = null;

      const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'ERROR']);

      fetch(`/api/v1/runs/${rid}`)
        .then(res => {
          if (!res.ok) throw new Error(`Status check returned ${res.status}`);
          return res.json();
        })
        .then(data => {
          if (streamCtlRef.current.run !== rid) return;
          const runStatus = data.status || 'UNKNOWN';
          setStatus(runStatus);
          setSourcedFromMaster(!!data.sourced_from_master);

          if (TERMINAL_STATUSES.has(runStatus)) {
            // Explicit terminal state: the run is over; no retries are scheduled.
            setConnectionStatus('FINISHED');
          } else {
            scheduleRetry(rid);
          }
        })
        .catch(() => {
          if (streamCtlRef.current.run === rid) scheduleRetry(rid);
        });
    };
  };

  useEffect(() => {
    if (runId) {
      connectStream(runId);
    }
    return () => teardownStream();
  }, [runId]);

  // Canonical Graph Builder; provenance-gated (Runtime-Authoritative
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
    selection: LogEvent | null,
    mode: GraphLayerMode,
    isTerminalRun: boolean
  ): {
    flowNodes: any[];
    flowEdges: any[];
    provenance: 'CANONICAL' | 'TOPOLOGY_UNAVAILABLE';
    scenarioNodeCount: number;
    runtimeNodeCount: number;
    droppedEdgeCount: number;
  } => {
    const positions = nodePositionsRef.current;

    // 0. Canonical event normalization: every consumer below
    // (node status, attempt counts, edge decoration) derives from events
    // ordered by server-assigned _seq — NEVER array arrival order, which
    // replay/recovery reconnection can scramble. Events lacking _seq retain
    // stable arrival position after all sequenced events.
    const seqIndexed = allEvents.map((e, arrivalIdx) => ({
      ev: e,
      arrivalIdx,
      seq: typeof e._seq === 'number' && Number.isFinite(e._seq) ? e._seq : null
    }));
    seqIndexed.sort((a, b) => {
      if (a.seq !== null && b.seq !== null && a.seq !== b.seq) return a.seq - b.seq;
      if (a.seq !== null && b.seq === null) return -1;
      if (a.seq === null && b.seq !== null) return 1;
      return a.arrivalIdx - b.arrivalIdx;
    });
    const normalizedEvents = seqIndexed.map(x => x.ev);

    // 1. Canonical sources only.
    const scenarioNodesRaw = scen?.workflow?.nodes || scen?.workflow?.tasks || [];
    const workflowEdges = scen?.workflow?.edges || [];

    const graphNodeEventsAll = normalizedEvents.filter(e => e.event === 'execution_graph_node');
    // Nodes with authoritative executed coverage; drives the
    // divergence overlay (planned-but-never-executed detection).
    const executedNodeIds = new Set<string>(
      graphNodeEventsAll.map(e => e.scenario_node_id).filter((id): id is string => !!id)
    );
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
        droppedEdgeCount: 0
      };
    }

    // 2. Map authoritative state per canonical node using O(1) index; status comes SOLELY from
    // execution_graph_node events. No string heuristics.
    const eventsByNodeId = new Map<string, any[]>();
    for (const ev of graphNodeEventsAll) {
      if (ev.scenario_node_id) {
        const nid = String(ev.scenario_node_id);
        const list = eventsByNodeId.get(nid);
        if (list) list.push(ev);
        else eventsByNodeId.set(nid, [ev]);
      }
    }

    const flowNodes = workflowNodes.map((n: any) => {
      const id = String(n.id || n.scenario_node_id || n.task_id);
      const label = n.task_description || n.description || n.label || id;

      const graphNodeEvents = eventsByNodeId.get(id) || [];

      let status = 'pending';
      let hasCanonicalEvent = false;
      let failureClass: string | undefined;
      let failureReason: string | undefined;
      let durationMs: number | undefined;
      let maxAttempt = 1;
      let passCount = 0;
      let failCount = 0;

      if (graphNodeEvents.length > 0) {
        for (const ev of graphNodeEvents) {
          const st = ev.status ? ev.status.toLowerCase() : '';
          if (st === 'completed') passCount++;
          else if (st === 'failed' || st === 'error' || st === 'aborted') failCount++;
        }
        const latestEv = graphNodeEvents[graphNodeEvents.length - 1];
        if (latestEv.status) {
          status = latestEv.status.toLowerCase();
        }
        failureClass = latestEv.failure_class;
        failureReason = latestEv.failure_reason;
        durationMs = latestEv.duration_ms;
        const attempts = graphNodeEvents.map((e: any) => e.attempt || 1);
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
        statusLabel = failureClass || failureReason || (failCount > 1 ? `Failed (${failCount} attempts)` : 'Failed');
      } else if (status === 'completed') {
        border = isHighlighted ? '2px solid #34d399' : '1px solid #10b981';
        background = 'rgba(6,78,59,0.4)';
        statusLabel = failCount > 0 ? `Completed (${passCount}/${passCount + failCount} with retries)` : 'Completed';
      } else if (status === 'running') {
        border = isHighlighted ? '2px solid #fbbf24' : '1px solid #f59e0b';
        background = 'rgba(120,53,15,0.4)';
        statusLabel = maxAttempt > 1 ? `Running (att #${maxAttempt})` : 'Running';
      }

      // Divergence overlay: only in divergence layer, only from
      // canonical evidence. Pending ≠ skipped while the run is live; a
      // planned node is SKIPPED only once the run reached a terminal state.
      const isUnplanned = !!(n as any).__runtime_discovered;
      const isSkipped =
        mode === 'divergence' && !isUnplanned && isTerminalRun && !executedNodeIds.has(id);
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
          label: (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-1">
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
                  title="No execution_graph_node event recorded for this node yet; status is PENDING by definition, not inferred."
                  className="px-1 py-0.2 bg-slate-800/60 text-slate-500 text-[8px] rounded tracking-wider uppercase"
                >
                  NO GRAPH EVENT
                </div>
              )}
              {isSkipped && (
                <div
                  title="Planned in the scenario DAG but never executed when the run terminated (execution_graph_node evidence)."
                  className="px-1 py-0.2 bg-red-500/20 text-red-300 text-[8px] rounded font-bold tracking-wider uppercase"
                >
                  SKIPPED
                </div>
              )}
              {isUnplanned && mode === 'divergence' && (
                <div
                  title="Executed at runtime but absent from the planned scenario DAG."
                  className="px-1 py-0.2 bg-amber-500/20 text-amber-300 text-[8px] rounded font-bold tracking-wider uppercase"
                >
                  UNPLANNED
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

    // Initial edges from workflow definition: include stable edge ID or condition/ordinal to preserve parallel edges
    workflowEdges.forEach((e: any, idx: number) => {
      const source = e.from || e.source;
      const target = e.to || e.target;
      if (nodeIdSet.has(source) && nodeIdSet.has(target)) {
        const edgeId = e.id || `scen-edge-${source}-${target}-${e.condition || e.type || idx}`;
        flowEdgesMap.set(edgeId, {
          id: edgeId,
          source,
          target,
          label: e.condition || e.label || undefined,
          animated: true,
          style: { stroke: '#6366f1', strokeWidth: 2 }
        });
      }
    });

    // Decorate with runtime execution_graph_edge events
    const graphEdgeEvents = normalizedEvents.filter(e => e.event === 'execution_graph_edge');
    const instanceOwner = new Map<string, string>();
    for (const ev of graphNodeEventsAll) {
      if (ev.execution_instance_id && ev.scenario_node_id) {
        instanceOwner.set(String(ev.execution_instance_id), String(ev.scenario_node_id));
      }
    }
    const unplacedExecEdges = new Set<string>();
    graphEdgeEvents.forEach((e: any, idx: number) => {
      const rawSource = e.from_scenario_node_id || e.source_execution_id || e.source;
      const rawTarget = e.to_scenario_node_id || e.target_execution_id || e.target;
      const source = nodeIdSet.has(rawSource)
        ? rawSource
        : instanceOwner.get(String(rawSource));
      const target = nodeIdSet.has(rawTarget)
        ? rawTarget
        : instanceOwner.get(String(rawTarget));
      if (source && target && nodeIdSet.has(source) && nodeIdSet.has(target)) {
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
          animated: true,
          style: {
            stroke: e.edge_type === 'retry' ? '#f59e0b' : '#6366f1',
            strokeWidth: 2,
            strokeDasharray: e.edge_type === 'retry' ? '5,5' : undefined
          }
        });
      } else if (rawSource != null && rawTarget != null) {
        unplacedExecEdges.add(`${rawSource}->${rawTarget}`);
      }
    });

    const allEdges = Array.from(flowEdgesMap.values());

    // Parallel edge offset decoration
    const edgePairCounts = new Map<string, number>();
    const edgePairCurrent = new Map<string, number>();
    for (const e of allEdges) {
      const pair = `${e.source}->${e.target}`;
      edgePairCounts.set(pair, (edgePairCounts.get(pair) || 0) + 1);
    }

    const flowEdges = allEdges
      .filter(e => {
        const plannedEdge = e.id.startsWith('scen-edge-');
        if (mode === 'planned') return plannedEdge;
        if (mode === 'executed') return !plannedEdge;
        // divergence layer displays both
        return true;
      })
      .map(e => {
        const plannedEdge = e.id.startsWith('scen-edge-');
        const pair = `${e.source}->${e.target}`;
        const total = edgePairCounts.get(pair) || 1;
        const cur = edgePairCurrent.get(pair) || 0;
        edgePairCurrent.set(pair, cur + 1);

        if (!plannedEdge) {
          return {
            ...e,
            type: total > 1 ? 'smoothstep' : undefined,
            animated: mode !== 'planned',
            style: { stroke: '#10b981', strokeWidth: 2 },
          };
        }
        if (mode === 'planned') {
          return {
            ...e,
            type: total > 1 ? 'smoothstep' : undefined,
            animated: true,
            style: { stroke: '#6366f1', strokeWidth: 2 },
          };
        }
        return {
          ...e,
          type: total > 1 ? 'smoothstep' : undefined,
          animated: false,
          style: {
            stroke: mode === 'divergence' ? '#818cf8' : '#475569',
            strokeWidth: 1,
            strokeDasharray: '5,5',
            opacity: 0.7,
          },
        };
      });

    // 4. Graph Layout Engine (Dagre Integration)
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
      // Composite cache key: run_id :: scenario_hash :: node_id.
      const savedPos = positions.get(posKey(node.id));
      if (savedPos) {
        return { ...node, position: savedPos };
      }
      const nodeWithPosition = dagreGraph.node(node.id);
      const x = nodeWithPosition ? nodeWithPosition.x - nodeWidth / 2 + 80 : 80 + index * 220;
      const y = nodeWithPosition ? nodeWithPosition.y - nodeHeight / 2 + 50 : 50;
      const pos = { x, y };
      positions.set(posKey(node.id), pos);
      return { ...node, position: pos };
    });

    return {
      flowNodes: layoutedNodes,
      flowEdges,
      provenance: 'CANONICAL',
      scenarioNodeCount: scenarioNodesRaw.length,
      runtimeNodeCount: runtimeDiscoveredNodes.length,
      droppedEdgeCount: unplacedExecEdges.size
    };
  };

  // Node Drag Position Saver to ensure layout state persistence
  const handleNodeDragStop = (_: any, node: any) => {
    if (node && node.id && node.position) {
      nodePositionsRef.current.set(posKey(node.id), { x: node.position.x, y: node.position.y });
    }
  };

  const RUN_TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'ERROR']);
  const isTerminalRun = RUN_TERMINAL_STATUSES.has(status);

  useEffect(() => {
    const result = buildTraceGraph(events, activeScenario, selectedEvent, layerMode, isTerminalRun);
    setNodes(result.flowNodes);
    setEdges(result.flowEdges);
    setTopologyProvenance({
      source: result.provenance,
      scenarioNodeCount: result.scenarioNodeCount,
      runtimeNodeCount: result.runtimeNodeCount,
      droppedEdgeCount: result.droppedEdgeCount
    });
    // Heuristic findings are computed for the diagnostics panel only.
    setDiagnostics(computeTelemetryDiagnostics(events));
  }, [events, activeScenario, selectedEvent, layerMode, isTerminalRun, runId, scenarioHash]);

  // Filter events by selected telemetry level via typed taxonomy
  useEffect(() => {
    setFilteredEvents(filterEventsByTelemetryLevel(events, telemetryLevel));
  }, [events, telemetryLevel]);

  // Auto-fit fires ONCE per run+scenario (initial load only).
  // During active investigation the viewport is never moved automatically;
  // an explicit "Fit graph" button exists in the toolbar.
  const autoFitKeyRef = useRef<string>('');
  useEffect(() => {
    if (!reactFlowInstance || nodes.length === 0) return;
    const key = `${runId}::${scenarioHash}`;
    if (autoFitKeyRef.current === key) return;
    autoFitKeyRef.current = key;
    const timer = setTimeout(() => {
      reactFlowInstance.fitView({ padding: 0.2, duration: 400 });
    }, 60);
    return () => clearTimeout(timer);
  }, [nodes.length, reactFlowInstance, runId, scenarioHash]);

  // Selection NEVER moves the camera. Recentering happens only on
  // this explicit operator action.
  const focusSelectedNode = () => {
    if (!selectedEvent || !reactFlowInstance) return;
    const nodeId =
      selectedEvent.scenario_node_id || selectedEvent.node_id || selectedEvent.task_id;
    if (!nodeId) return;
    const targetNode = nodes.find(n => n.id === nodeId);
    if (!targetNode) return;
    const { x, y } = targetNode.position;
    const currentZoom = reactFlowInstance.getZoom ? reactFlowInstance.getZoom() : 1.0;
    reactFlowInstance.setCenter(x + 80, y + 40, { zoom: Math.min(currentZoom, 1.15), duration: 400 });
  };

  // Selection highlighting is now handled inside buildTraceGraph() via the
  // reactive useEffect([events, activeScenario, selectedEvent]) above.
  // The separate style-patch effect has been removed; it is no longer needed.

  const hasError = events.some(e =>
    e.event === 'error' ||
    e.category === 'PARITY_STATE_DIVERGENCE' ||
    e.message?.toLowerCase().includes('error') ||
    e.message?.toLowerCase().includes('fail')
  );

  // Forensic waterfall derived from authoritative graph-node events.
  const waterfall = useMemo(() => buildWaterfall(events), [events]);
  const focusWaterfallRow = (row: WaterfallRow) => {
    const target = [...events]
      .reverse()
      .find(
        e =>
          e.event === 'execution_graph_node' &&
          (e.execution_instance_id === row.execId ||
            ((e.scenario_node_id || e.node_id) === row.nodeId &&
              (e.iteration ?? 1) === row.iteration))
      );
    if (target) setSelectedEvent(target);
  };

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
                  className={`py-1 rounded uppercase tracking-wider ${telemetryLevel === lvl ? 'bg-slate-900 text-indigo-400' : 'text-slate-500 hover:text-slate-400'
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
              const isRootCauseIndex =
                evt.is_root_cause === true ||
                (analysisData &&
                  (analysisData.seq !== undefined
                    ? evt._seq === analysisData.seq
                    : analysisData.event_id
                      ? evt.event_id === analysisData.event_id
                      : events.indexOf(evt) === analysisData.index));
              return (
                <button
                  key={idx}
                  onClick={() => setSelectedEvent(evt)}
                  className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all flex items-start gap-2.5 ${isSelected
                    ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300 ring-2 ring-indigo-500/50'
                    : isRootCauseIndex
                      ? 'bg-rose-950/40 border-rose-500/50 text-rose-200 ring-1 ring-rose-500/30'
                      : isError
                        ? 'bg-red-500/5 border-red-500/20 text-red-400'
                        : 'bg-slate-950/60 border-slate-900 text-slate-350 hover:bg-slate-900/40'
                    }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${isRootCauseIndex ? 'bg-rose-500' : isError ? 'bg-red-500' : 'bg-indigo-500'
                    }`} />
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono">
                      <span className="uppercase font-bold tracking-wider text-indigo-400">
                        {evt.event} (Seq #{evt._seq}{evt.turn !== undefined ? `, Turn ${evt.turn}` : ''})
                      </span>
                      <div className="flex items-center gap-1.5">
                        {/* RCA confidence labeling: authoritative runtime
                            designation vs heuristic inference are never collapsed. */}
                        {evt.is_root_cause === true && (
                          <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 text-[8px] font-bold tracking-wider uppercase shrink-0">
                            🔴 Root Cause (Confirmed)
                          </span>
                        )}
                        {!evt.is_root_cause && isRootCauseIndex && (
                          <span
                            title="Inferred by the analysis heuristic; not an authoritative runtime designation."
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

          {/* Execution waterfall; synchronized forensic timeline
              built ONLY from authoritative execution_graph_node evidence:
              parent/child depth, retries/iterations, observed durations and
              failure boundaries. Nodes without timestamps are listed, never
              synthesized into the time axis. */}
          {waterfall.rows.length > 0 && (
            <details className="border border-slate-900 rounded-lg bg-slate-950/40">
              <summary className="px-2.5 py-2 text-[9px] font-bold uppercase tracking-wider text-slate-500 cursor-pointer hover:text-slate-400">
                Execution Waterfall ({waterfall.rows.length})
                {waterfall.tMin !== null && waterfall.tMax !== null && (
                  <span className="ml-1 font-mono normal-case text-slate-600">
                    {((waterfall.tMax - waterfall.tMin) / 1000).toFixed(2)}s span
                  </span>
                )}
              </summary>
              <div className="px-2.5 pb-2.5 space-y-1 max-h-64 overflow-y-auto">
                {waterfall.tMin !== null && waterfall.tMax !== null && waterfall.tMax > waterfall.tMin ? (
                  (() => {
                    const span = waterfall.tMax - waterfall.tMin;
                    return waterfall.rows.map(row => {
                      const start = row.startTs ?? row.endTs!;
                      const end = row.endTs ?? row.startTs!;
                      const left = Math.min(((start - waterfall.tMin!) / span) * 100, 97);
                      const width = Math.max(((end - start) / span) * 100, 1);
                      const barCls =
                        row.status === 'completed'
                          ? 'bg-emerald-500/70'
                          : row.status === 'failed'
                            ? 'bg-red-500/80'
                            : row.status === 'running'
                              ? 'bg-amber-500/80 animate-pulse'
                              : 'bg-slate-600';
                      return (
                        <button
                          key={row.execId}
                          onClick={() => focusWaterfallRow(row)}
                          title={`${row.nodeId} · ${row.status}${row.durationMs ? ` · ${row.durationMs}ms` : ''}`}
                          className="w-full flex items-center gap-2 group"
                        >
                          <span
                            className="font-mono text-[8px] text-slate-500 truncate w-24 text-left"
                            style={{ paddingLeft: `${Math.min(row.depth * 8, 32)}px` }}
                          >
                            {row.depth > 0 ? '↳ ' : ''}{row.nodeId}
                            {row.iteration > 1 || (row.execId.match(/#(\d+)$/)?.[1] ?? '1') !== '1' ? ` ·it${row.iteration}` : ''}
                          </span>
                          <span className="relative flex-1 h-3 bg-slate-900/80 rounded overflow-hidden">
                            <span
                              className={`absolute h-full rounded ${barCls}`}
                              style={{ left: `${left}%`, width: `${width}%` }}
                            />
                            {/* [Sprint-6] Tool/assertion/failure markers */}
                            {row.markers.map((m, mi) => {
                              const span = waterfall.tMax! - waterfall.tMin!;
                              const mLeft = Math.min(((m.t - waterfall.tMin!) / span) * 100, 98);
                              const color =
                                m.kind === 'error'
                                  ? 'bg-red-400'
                                  : m.kind === 'evaluation'
                                    ? 'bg-teal-300'
                                    : m.kind === 'tool_result'
                                      ? 'bg-cyan-300'
                                      : 'bg-indigo-300';
                              return (
                                <span
                                  key={mi}
                                  title={`${m.kind} @ ${new Date(m.t).toLocaleTimeString()}`}
                                  className={`absolute top-0 bottom-0 w-[2px] ${color}`}
                                  style={{ left: `${mLeft}%` }}
                                />
                              );
                            })}
                            {row.status === 'failed' && (
                              <span
                                className="absolute top-0 bottom-0 w-0.5 bg-red-300"
                                style={{ left: `${Math.min(left + width, 99)}%` }}
                                title="Failure boundary"
                              />
                            )}
                          </span>
                          <span className="font-mono text-[8px] text-slate-500 w-10 text-right">
                            {row.durationMs != null ? `${(row.durationMs / 1000).toFixed(2)}s` : '—'}
                          </span>
                        </button>
                      );
                    });
                  })()
                ) : (
                  waterfall.rows.map(row => (
                    <button
                      key={row.execId}
                      onClick={() => focusWaterfallRow(row)}
                      className="w-full text-left font-mono text-[8px] text-slate-500 hover:text-slate-300 truncate"
                    >
                      {row.depth > 0 ? '↳ ' : ''}{row.nodeId} · {row.status} · no timestamps in trace
                    </button>
                  ))
                )}
              </div>
            </details>
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
              className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border font-mono text-[10px] font-bold uppercase tracking-wider cursor-help ${topologyProvenance.source === 'CANONICAL'
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
              className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border font-mono text-[10px] font-bold uppercase tracking-wider cursor-help ${integrityTone === 'clean'
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
            {/* [P1.4] Executed transitions that could not be placed on the
                graph are surfaced — never a silently false-complete graph. */}
            {topologyProvenance.droppedEdgeCount > 0 && (
              <div
                title={`${topologyProvenance.droppedEdgeCount} executed transition event(s) reference endpoints that could not be resolved to scenario nodes. The rendered graph is INCOMPLETE: absence of an edge here is NOT evidence it did not fire.`}
                className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-300 font-mono text-[10px] font-bold uppercase tracking-wider cursor-help animate-pulse"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                DROPPED EDGES ({topologyProvenance.droppedEdgeCount})
              </div>
            )}
            {/* [P0-10] Live SSE gap banner; missing server event ids are
                reported visibly, never silently tolerated. */}
            {streamGaps.length > 0 && (
              <div
                title={`Server stream gaps detected before dedupe/reorder: ${streamGaps
                  .map(g => `${g.from}–${g.to}`)
                  .join(', ')}. The trace-integrity panel reflects the authoritative post-replay state.`}
                className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 font-mono text-[10px] font-bold uppercase tracking-wider cursor-help animate-pulse"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                SSE GAP ({streamGaps.length})
              </div>
            )}
            {/* [GUI-P0-8] Explicit graph layer selector */}
            <div
              title={
                layerMode === 'planned'
                  ? 'Planned layer: the scenario DAG as defined; the design-time control-flow contract.'
                  : layerMode === 'executed'
                    ? 'Executed layer: authoritative execution_graph_edge transitions over a dimmed plan skeleton.'
                    : 'Divergence overlay: planned-vs-executed differences (SKIPPED planned nodes, UNPLANNED executions).'
              }
              className="flex bg-slate-950 border border-slate-800 rounded-lg p-0.5 font-mono text-[9px] font-bold uppercase tracking-wider cursor-help"
            >
              <Layers className="w-3.5 h-3.5 text-slate-500 self-center ml-1.5 mr-1" />
              {(['planned', 'executed', 'divergence'] as const).map(l => (
                <button
                  key={l}
                  onClick={() => setLayerMode(l)}
                  className={`px-2 py-1 rounded-md transition-colors ${layerMode === l ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                    }`}
                >
                  {l}
                </button>
              ))}
            </div>
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Runner Status:</span>
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
              <span className={`w-2.5 h-2.5 rounded-full ${status === 'RUNNING' ? 'bg-amber-500 animate-pulse' :
                status === 'COMPLETED' ? 'bg-emerald-500' : 'bg-red-500'
                }`} />
              <span className={status === 'RUNNING' ? 'text-amber-400' : status === 'COMPLETED' ? 'text-emerald-400' : 'text-red-400'}>
                {status}
              </span>
            </div>

            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider ml-4">Stream:</span>
            <div className="flex items-center gap-1.5">
              <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${connectionStatus === 'CONNECTED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                connectionStatus === 'REPLAYING' ? 'bg-violet-500/10 text-violet-300 border-violet-500/20 animate-pulse' :
                  connectionStatus === 'CONNECTING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse' :
                    connectionStatus === 'RECONNECTING' ? 'bg-red-500/10 text-red-400 border-red-500/20 animate-pulse' :
                      connectionStatus === 'FINISHED' ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' :
                        'bg-slate-500/10 text-slate-400 border-slate-500/20'
                }`}>
                {connectionStatus === 'RECONNECTING' ? `RECONNECTING (${reconnectCount}/8)` : connectionStatus}
              </span>
              {(connectionStatus === 'DISCONNECTED' || connectionStatus === 'RECONNECTING') && (
                <button
                  onClick={() => connectStream(runId)}
                  className="px-2 py-0.5 bg-indigo-600/20 hover:bg-indigo-600/40 border border-indigo-500/30 rounded text-[9px] font-mono text-indigo-300 font-bold uppercase tracking-wider transition-colors cursor-pointer"
                >
                  Reconnect
                </button>
              )}
              {/* [Sprint-3] Explicit fit; auto-fit only ever happens on
                  initial load of a run+scenario. */}
              <button
                title="Fit graph to viewport (explicit)"
                onClick={() => reactFlowInstance?.fitView?.({ padding: 0.2, duration: 300 })}
                className="px-2 py-0.5 bg-slate-800/60 hover:bg-slate-800 border border-slate-700 rounded text-[9px] font-mono text-slate-300 font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1"
              >
                <Maximize2 className="w-3 h-3" /> Fit
              </button>
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
              <span>Root Cause Analysis</span>
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
          {/* Explicit TOPOLOGY_UNAVAILABLE state. */}
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
            nodesConnectable={false}
            edgesReconnectable={false}
            proOptions={{ hideAttribution: true }}
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

          {/* [B3] Non-authoritative telemetry diagnostics; heuristic findings
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
                node states; canonical execution_graph_node events remain the sole
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
                      className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider ${d.suspectedStatus === 'failed'
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

              {/* [Sprint-4] Explicit focus; selection never moves the camera. */}
              {(selectedEvent.scenario_node_id || selectedEvent.node_id || selectedEvent.task_id) && (
                <button
                  onClick={focusSelectedNode}
                  title="Center the graph on this event's node (explicit action only)"
                  className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-indigo-500/40 text-slate-300 hover:text-indigo-300 text-[10px] font-bold uppercase tracking-wider transition-colors"
                >
                  <Crosshair className="w-3.5 h-3.5" /> Focus node
                </button>
              )}

              {(() => {
                // [P0-12] Strict StateComparison rendering. The diff renders
                // ONLY from the runtime's structured payload; never guessed
                // out of message text or arbitrary fallback fields.
                const sc = parseStateComparison(selectedEvent);
                const legacyParity =
                  selectedEvent.category === 'PARITY_STATE_DIVERGENCE' && !sc;

                if (!sc && !legacyParity) return null;

                return (
                  <div className="space-y-2">
                    <div className="p-2.5 bg-red-500/5 border border-red-500/10 rounded-lg flex gap-2 text-red-400">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                      <div className="space-y-0.5">
                        <h4 className="text-xs font-bold uppercase tracking-wider">State Divergence Detected</h4>
                        <p className="text-[10px] leading-relaxed">The returned runtime state does not match the expectations defined in the execution manifest.</p>
                      </div>
                    </div>

                    {sc ? (
                      <>
                        <div className="border border-slate-850 rounded-lg overflow-hidden bg-slate-950 text-[10px]">
                          <ReactDiffViewer
                            oldValue={JSON.stringify(sc.expected, null, 2)}
                            newValue={JSON.stringify(sc.actual, null, 2)}
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
                        <div className="p-2.5 bg-slate-950/70 border border-slate-900 rounded-lg space-y-1 font-mono text-[9px] text-slate-400">
                          {sc.comparison?.['kind'] !== undefined && (
                            <p><span className="text-slate-500 uppercase tracking-wider">comparison:</span> {String(sc.comparison['kind'])}</p>
                          )}
                          {typeof sc.comparison?.['failed_assertion'] === 'string' && (
                            <p className="break-all"><span className="text-slate-500 uppercase tracking-wider">first failure:</span> <span className="text-red-300">{sc.comparison['failed_assertion'] as string}</span></p>
                          )}
                          {Array.isArray(sc.assertions) && (
                            <p><span className="text-slate-500 uppercase tracking-wider">assertions:</span> {sc.assertions.length}</p>
                          )}
                          {sc.source && (
                            <p><span className="text-slate-500 uppercase tracking-wider">source:</span> {sc.source}</p>
                          )}
                          {sc.timestamp && (
                            <p><span className="text-slate-500 uppercase tracking-wider">timestamp:</span> {sc.timestamp}</p>
                          )}
                        </div>
                      </>
                    ) : (
                      <div className="p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg text-[10px] text-amber-300 leading-relaxed">
                        Structured StateComparison payload is unavailable for this
                        legacy divergence event; no expected-vs-actual diff is
                        inferred from message text. Raw event shown below.
                      </div>
                    )}
                  </div>
                );
              })()}

              <div className="space-y-2">
                <span className="text-slate-400 font-semibold">Event Parameters JSON:</span>
                <pre className="bg-slate-950 p-4 rounded-lg border border-slate-850 text-[10px] text-slate-300 font-mono leading-relaxed overflow-x-auto select-all max-h-[220px]">
                  {JSON.stringify(selectedEvent, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <p className="text-slate-500 italic py-4">Select an event from the timeline feed to inspect detailed environment state parity.</p>
          )}
        </div>
      </div>

      {/* Deterministic diagnostics drawer overlay */}
      {showExplain && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex justify-end">
          <div className="bg-slate-900 border-l border-slate-800 w-full max-w-xl h-full p-6 flex flex-col justify-between text-slate-100 shadow-2xl animate-slide-in">
            <div className="space-y-4 overflow-y-auto flex-1 pr-2">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-indigo-400" />
                <h3 className="text-base font-bold text-white uppercase tracking-wider">Root Cause Analysis — Deterministic Diagnostics Engine</h3>
              </div>
              <p className="text-slate-400 text-xs leading-relaxed">
                Analyzing cryptographic trace anchors and execution milestones to locate potential loops, logic hangs, and state overrides.
              </p>

              <div className="p-4 bg-slate-950/60 border border-slate-850 rounded-lg text-xs leading-relaxed font-mono whitespace-pre-wrap leading-relaxed text-slate-350">
                {/* [Release-blocker 4] The whole explanation is heuristic
                    output: it is labeled SUSPECTED with its source and
                    confidence — never presented as an authoritative verdict. */}
                <div className="flex items-center gap-2 mb-2">
                  {analysisData ? (
                    <>
                      <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[8px] font-bold tracking-wider uppercase">
                        ⚠ SUSPECTED (heuristic)
                      </span>
                      <span className="text-[8px] font-mono text-slate-500 uppercase">
                        source: deterministic triage rules (/api/v1/explain)
                        · confidence: {explainResult.match(/Confidence:\s*([^\n]+)/)?.[1] ?? 'N/A'}
                      </span>
                    </>
                  ) : (
                    <span className="px-1.5 py-0.5 rounded bg-slate-700/40 text-slate-400 border border-slate-600/40 text-[8px] font-bold tracking-wider uppercase">
                      NO ANALYSIS AVAILABLE
                    </span>
                  )}
                </div>
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




