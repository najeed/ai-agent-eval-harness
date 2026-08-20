import React, { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { 
  ReactFlow, Controls, Background, useNodesState, useEdgesState 
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { 
  Sparkles, AlertTriangle 
} from 'lucide-react';
import ReactDiffViewer from 'react-diff-viewer-continued';

interface LogEvent {
  event: string;
  timestamp: string;
  run_id?: string;
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
}

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
    let targetIdx = -1;
    if (analysisData && analysisData.index !== undefined && analysisData.index >= 0) {
      targetIdx = analysisData.index;
    } else {
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

  // Auto-expand Explain Panel if query param is set
  useEffect(() => {
    if (runId && searchParams.get('explain') === 'true') {
      handleExplain();
    }
  }, [runId, searchParams]);

  // Close stream helper
  const closeStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

  // Connect to SSE stream with auto-reconnect backoff (NFR 8.1)
  const connectStream = (rid: string, attempt = 0) => {
    closeStream();
    if (attempt === 0) {
      setEvents([]);
      setSelectedEvent(null);
      setNodes([]);
      setEdges([]);
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

    // Server-Sent Events stream initialization (only if run is active)
    const streamUrl = `/api/v1/runs/${rid}/stream`;
    const source = new EventSource(streamUrl);
    eventSourceRef.current = source;

    source.onopen = () => {
      console.log(`SSE connection to ${rid} opened.`);
      setConnectionStatus('CONNECTED');
      setReconnectCount(0);
    };

    source.onmessage = (event) => {
      try {
        const data: LogEvent = JSON.parse(event.data);
        // Control-plane events: update connection/run state but do not
        // append to the trace log. Graph derivation is reactive — the
        // useEffect([events, activeScenario, selectedEvent]) below will
        // re-run automatically whenever any of its inputs change.
        if (data.event === 'timeout') {
          setStatus('STALLED');
          return;
        }
        if (data.event === 'not_found') {
          // Backend now emits structured JSON for the no-trace-yet path.
          // Surface a waiting state rather than silently discarding.
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

        // Pure append — graph derivation happens in the reactive effect.
        setEvents(prev => [...prev, data]);
      } catch (e) {
        console.error('Failed to parse SSE event data:', e);
      }
    };

    source.onerror = () => {
      console.warn('SSE stream encountered error or finished. Reconnecting/Closing.');
      closeStream();

      // Reconnect decision: only collapse to FINISHED on a confirmed terminal
      // status. Previously only 'RUNNING' triggered a retry, which meant
      // STALLED/UNKNOWN/404 silently set FINISHED with no manual affordance.
      // Terminal statuses are those the runtime sets when a run will never
      // produce more events.
      const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'ERROR']);

      fetch(`/api/v1/runs/${rid}`)
        .then(res => {
          if (!res.ok) {
            // 404 / server error — the run entry may not exist yet on a
            // freshly-started run. Treat as non-terminal and backoff-retry.
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
            // RUNNING, STALLED, UNKNOWN — all warrant a reconnect attempt.
            if (attempt < 5) {
              const backoffTime = Math.pow(2, attempt) * 1000;
              setReconnectCount(attempt + 1);
              setTimeout(() => {
                connectStream(rid, attempt + 1);
              }, backoffTime);
            } else {
              // Exhausted retries — surface DISCONNECTED with manual reconnect affordance.
              setConnectionStatus('DISCONNECTED');
            }
          }
        })
        .catch(() => {
          // Network error or non-OK status check: backoff and retry rather
          // than silently going to DISCONNECTED immediately.
          if (attempt < 5) {
            const backoffTime = Math.pow(2, attempt) * 1000;
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

  // Pure graph builder — no side effects, no React state reads.
  // Receives all inputs explicitly so it can be called from a reactive
  // useEffect without any closure dependencies on component state.
  const buildTraceGraph = (
    allEvents: LogEvent[],
    scen: any,
    selection: LogEvent | null
  ): { flowNodes: any[]; flowEdges: any[] } => {
    const workflowNodes = scen?.workflow?.nodes || scen?.workflow?.tasks || [];
    const workflowEdges = scen?.workflow?.edges || [];

    let flowNodes = [];
    const nodesPerRow = 4;

    if (workflowNodes.length > 0) {
      flowNodes = workflowNodes.map((n: any, index: number) => {
        const id = n.id;
        const isError = allEvents.some(e => (e.node_id === id || e.task_id === id) && (e.event === 'error' || e.category === 'PARITY_STATE_DIVERGENCE' || e.message?.toLowerCase().includes('error') || e.message?.toLowerCase().includes('fail')));
        const isFinished = allEvents.some(e => (e.node_id === id || e.task_id === id) && (e.event === 'maneuver_end' || e.event === 'node_end' || e.result === 'success'));
        const isStarted = allEvents.some(e => (e.node_id === id || e.task_id === id));
        const isHighlighted = selection && (id === selection.node_id || id === selection.task_id);

        let border = isHighlighted ? '2px solid #818cf8' : '1px solid #334155';
        let background = '#0f172a';
        let statusLabel = 'Pending';
        if (isError) {
          border = isHighlighted ? '2px solid #f87171' : '1px solid #ef4444';
          background = 'rgba(127,29,29,0.4)';
          statusLabel = 'Diverged';
        } else if (isFinished) {
          border = isHighlighted ? '2px solid #34d399' : '1px solid #10b981';
          background = 'rgba(6,78,59,0.4)';
          statusLabel = 'Completed';
        } else if (isStarted) {
          border = isHighlighted ? '2px solid #fbbf24' : '1px solid #f59e0b';
          background = 'rgba(120,53,15,0.4)';
          statusLabel = 'Running';
        }

        const row = Math.floor(index / nodesPerRow);
        const col = index % nodesPerRow;

        return {
          id,
          type: 'default',
          position: { x: 80 + col * 250, y: 50 + row * 160 },
          data: {
            label: (
              <div className="space-y-1">
                <div className="font-mono font-bold text-[10px] text-slate-200">{id}</div>
                <div className="text-[9px] text-slate-400 truncate max-w-[120px]" title={n.task_description || n.description}>{statusLabel}</div>
              </div>
            )
          },
          style: {
            background,
            color: '#fff',
            border,
            borderRadius: '8px',
            padding: '6px',
            width: 160,
            boxShadow: isHighlighted ? '0 0 15px rgba(99, 102, 241, 0.7), inset 0 0 0 1px rgba(129, 140, 248, 0.5)' : 'none',
            transition: 'box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease'
          }
        };
      });
    } else {
      // Fallback: Group events by node ID to map execution stages dynamically
      const nodeEvents = allEvents.filter(e => e.node_id || e.task_id);
      const nodeIds = Array.from(new Set(nodeEvents.map(e => e.node_id || e.task_id || '')));
      
      flowNodes = nodeIds.filter(Boolean).map((id, index) => {
        const isError = allEvents.some(e => (e.node_id === id || e.task_id === id) && (e.event === 'error' || e.category === 'PARITY_STATE_DIVERGENCE'));
        const isFinished = allEvents.some(e => (e.node_id === id || e.task_id === id) && e.event === 'maneuver_end');
        const isHighlighted = selection && (id === selection.node_id || id === selection.task_id);

        let border = isHighlighted ? '2px solid #818cf8' : '1px solid #334155';
        let background = '#0f172a';
        let statusLabel = 'Pending';
        if (isError) {
          border = isHighlighted ? '2px solid #f87171' : '1px solid #ef4444';
          background = 'rgba(127,29,29,0.4)';
          statusLabel = 'Diverged';
        } else if (isFinished) {
          border = isHighlighted ? '2px solid #34d399' : '1px solid #10b981';
          background = 'rgba(6,78,59,0.4)';
          statusLabel = 'Completed';
        } else {
          border = isHighlighted ? '2px solid #fbbf24' : '1px solid #f59e0b';
          background = 'rgba(120,53,15,0.4)';
          statusLabel = 'Running';
        }

        const row = Math.floor(index / nodesPerRow);
        const col = index % nodesPerRow;

        return {
          id,
          type: 'default',
          position: { x: 80 + col * 250, y: 50 + row * 160 },
          data: {
            label: (
              <div className="space-y-1">
                <div className="font-mono font-bold text-[10px] text-slate-200">{id}</div>
                <div className="text-[9px] text-slate-400 truncate max-w-[120px]">{statusLabel}</div>
              </div>
            )
          },
          style: {
            background,
            color: '#fff',
            border,
            borderRadius: '8px',
            padding: '6px',
            width: 140,
            boxShadow: isHighlighted ? '0 0 15px rgba(99, 102, 241, 0.7), inset 0 0 0 1px rgba(129, 140, 248, 0.5)' : 'none',
            transition: 'box-shadow 0.2s ease, border-color 0.2s ease, background-color 0.2s ease'
          }
        };
      });
    }

    let flowEdges: any[] = [];
    if (workflowEdges.length > 0) {
      // Scenario-defined topology — enforce that both source and target endpoints
      // exist in the flowNodes array being rendered to prevent dangling edge curves.
      const nodeIdSet = new Set(flowNodes.map((n: any) => n.id));
      flowEdges = workflowEdges
        .map((e: any, idx: number) => ({
          id: `e-${idx}`,
          source: e.from || e.source,
          target: e.to || e.target,
          animated: true
        }))
        .filter((e: any) => {
          const valid = nodeIdSet.has(e.source) && nodeIdSet.has(e.target);
          if (!valid) {
            console.warn('[LiveDebugger] Dropping edge with unresolved endpoint:', e);
          }
          return valid;
        });
    }
    // If no scenario edges are available (dynamic discovery fallback), we
    // intentionally do NOT fabricate sequential edges from event order.
    // Synthetic linear topology silently misrepresents non-linear DAGs.
    // Nodes will render without edges until a scenario-defined topology
    // is available.

    return { flowNodes, flowEdges };
  };

  // Single reactive graph derivation effect — the sole owner of setNodes/setEdges.
  // Runs whenever events accumulate, the scenario loads, or the selection changes.
  // This replaces: imperative updateFlowCanvas() calls inside onmessage, inside
  // checkStatus, and the separate style-patch useEffect for selection highlighting.
  useEffect(() => {
    const { flowNodes, flowEdges } = buildTraceGraph(events, activeScenario, selectedEvent);
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [events, activeScenario, selectedEvent]);

  // Filter events by selected telemetry level
  useEffect(() => {
    const filtered = events.filter(e => {
      if (telemetryLevel === 'PHASE') return e.event.includes('phase');
      if (telemetryLevel === 'SUBTASK') return e.event.includes('subtask') || e.event.includes('maneuver');
      if (telemetryLevel === 'ACTION') return e.event.includes('tool') || e.event.includes('adapter');
      return true; // STEP / All events
    });
    setFilteredEvents(filtered);
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
      const nodeId = selectedEvent.node_id || selectedEvent.task_id;
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
                        {isRootCauseIndex && (
                          <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30 text-[8px] font-bold tracking-wider uppercase animate-pulse shrink-0">
                            Root Cause Node
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
            onInit={setReactFlowInstance}
            fitView
          >
            <Background color="#334155" gap={16} />
            <Controls />
          </ReactFlow>
        </div>
      </div>

      {/* Right Side - State Parity Inspector (Diff Viewer) */}
      <div className="w-96 border-l border-slate-900 bg-slate-950/30 overflow-y-auto p-5 space-y-4 shrink-0 text-xs flex flex-col justify-between h-full">
        <div className="space-y-4 overflow-y-auto">
          <h3 className="font-bold text-slate-400 uppercase tracking-wider text-[10px]">State Parity Inspector</h3>
          
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
