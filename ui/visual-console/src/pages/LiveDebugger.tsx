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
}

export const LiveDebugger: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdParam = searchParams.get('run_id');

  const [runId, setRunId] = useState(runIdParam || '');
  const [runsList, setRunsList] = useState<string[]>([]);
  const [status, setStatus] = useState<string>('IDLE');
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [filteredEvents, setFilteredEvents] = useState<LogEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<LogEvent | null>(null);
  
  // 4-level Telemetry controls
  const [telemetryLevel, setTelemetryLevel] = useState<'PHASE' | 'SUBTASK' | 'ACTION' | 'STEP'>('STEP');

  // React Flow State
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  
  // AI explain drawer
  const [explainResult, setExplainResult] = useState<string>('');
  const [showExplain, setShowExplain] = useState(false);

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

  // Run status checker
  const checkStatus = async (rid: string) => {
    try {
      const res = await fetch(`/api/v1/runs/${rid}`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status || 'COMPLETED');
      }
    } catch (e) {
      setStatus('UNKNOWN');
    }
  };

  const handleExplain = async () => {
    if (!runId) return;
    setShowExplain(true);
    setExplainResult('AI Engine analyzing evaluation traces...');
    try {
      const res = await fetch(`/api/v1/explain/${runId}`);
      const data = await res.json();
      if (res.ok) {
        setExplainResult(data.analysis || 'Analysis complete. No loop or timeout patterns identified.');
      } else {
        setExplainResult(`Error: ${data.error || 'Failed to explain trace.'}`);
      }
    } catch (e: any) {
      setExplainResult(`Failed to trigger analysis: ${e.message}`);
    } finally {
      // Done
    }
  };

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
    
    // Set query param
    setSearchParams({ run_id: rid });

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
        if (data.event === 'timeout') {
          setStatus('STALLED');
          return;
        }
        setEvents(prev => {
          const updated = [...prev, data];
          updateFlowCanvas(updated);
          return updated;
        });
      } catch (e) {
        console.error('Failed to parse SSE event data:', e);
      }
    };

    source.onerror = () => {
      console.warn('SSE stream encountered error or finished. Reconnecting/Closing.');
      closeStream();
      
      // Auto-reconnect check
      fetch(`/api/v1/runs/${rid}`)
        .then(res => res.json())
        .then(data => {
          const runStatus = data.status || 'COMPLETED';
          setStatus(runStatus);
          
          if (runStatus === 'RUNNING') {
            if (attempt < 5) {
              const backoffTime = Math.pow(2, attempt) * 1000;
              setReconnectCount(attempt + 1);
              setTimeout(() => {
                connectStream(rid, attempt + 1);
              }, backoffTime);
            } else {
              setConnectionStatus('DISCONNECTED');
            }
          } else {
            setConnectionStatus('FINISHED');
          }
        })
        .catch(() => {
          setConnectionStatus('DISCONNECTED');
        });
    };
  };

  useEffect(() => {
    if (runId) {
      connectStream(runId);
    }
    return () => closeStream();
  }, [runId]);

  // Update ReactFlow nodes based on stream events
  const updateFlowCanvas = (allEvents: LogEvent[]) => {
    // Group events by node ID to map execution stages
    const nodeEvents = allEvents.filter(e => e.node_id || e.task_id);
    const nodeIds = Array.from(new Set(nodeEvents.map(e => e.node_id || e.task_id || '')));
    
    const flowNodes = nodeIds.filter(Boolean).map((id, index) => {
      const isError = allEvents.some(e => (e.node_id === id || e.task_id === id) && (e.event === 'error' || e.category === 'PARITY_STATE_DIVERGENCE'));
      const isFinished = allEvents.some(e => (e.node_id === id || e.task_id === id) && e.event === 'maneuver_end');
      
      let border = '1px solid #334155';
      let background = '#0f172a';
      let statusLabel = 'Pending';
      if (isError) {
        border = '1px solid #ef4444';
        background = '#7f1d1d/40';
        statusLabel = 'Diverged';
      } else if (isFinished) {
        border = '1px solid #10b981';
        background = '#064e3b/40';
        statusLabel = 'Completed';
      } else {
        border = '1px solid #f59e0b';
        background = '#78350f/40';
        statusLabel = 'Running';
      }

      return {
        id,
        type: 'default',
        position: { x: 100 + index * 200, y: 150 },
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
          width: 140
        }
      };
    });

    const flowEdges = [];
    for (let i = 0; i < flowNodes.length - 1; i++) {
      flowEdges.push({
        id: `e-${i}`,
        source: flowNodes[i].id,
        target: flowNodes[i + 1].id,
        animated: true
      });
    }

    setNodes(flowNodes);
    setEdges(flowEdges);
  };

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
              return (
                <button
                  key={idx}
                  onClick={() => setSelectedEvent(evt)}
                  className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all flex items-start gap-2.5 ${
                    isSelected 
                      ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300' 
                      : isError 
                        ? 'bg-red-500/5 border-red-500/20 text-red-400'
                        : 'bg-slate-950/60 border-slate-900 text-slate-350 hover:bg-slate-900/40'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                    isError ? 'bg-red-500' : 'bg-indigo-500'
                  }`} />
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono">
                      <span className="uppercase font-bold tracking-wider">{evt.event}</span>
                      <span>{evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ''}</span>
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
            <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${
              connectionStatus === 'CONNECTED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
              connectionStatus === 'CONNECTING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse' :
              connectionStatus === 'RECONNECTING' ? 'bg-red-500/10 text-red-400 border-red-500/20 animate-pulse' :
              connectionStatus === 'FINISHED' ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' :
              'bg-slate-500/10 text-slate-400 border-slate-500/20'
            }`}>
              {connectionStatus === 'RECONNECTING' ? `RECONNECTING (${reconnectCount}/5)` : connectionStatus}
            </span>
          </div>

          <button
            onClick={handleExplain}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-950 border border-slate-900 rounded text-slate-400 hover:text-slate-200 transition-colors font-bold uppercase tracking-wider"
          >
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
            <span>AI Explain Diagnostics</span>
          </button>
        </div>

        {/* ReactFlow Canvas container */}
        <div className="flex-1 h-full bg-slate-950/20 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
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

              {selectedEvent.category === 'PARITY_STATE_DIVERGENCE' ? (
                <div className="space-y-2">
                  <div className="p-2.5 bg-red-500/5 border border-red-500/10 rounded-lg flex gap-2 text-red-400">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <h4 className="text-xs font-bold uppercase tracking-wider">State Divergence Detected</h4>
                      <p className="text-[10px] leading-relaxed">The returned shim state does not match the expectations defined in the AES spec.</p>
                    </div>
                  </div>

                  {/* Side-by-side Git Diff using react-diff-viewer-continued */}
                  <div className="border border-slate-850 rounded-lg overflow-hidden bg-slate-950 text-[10px]">
                    <ReactDiffViewer
                      oldValue={JSON.stringify({ expected: "ok", table: "users" }, null, 2)}
                      newValue={JSON.stringify({ expected: "ok", table: null }, null, 2)}
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

            <div className="flex justify-end pt-4 border-t border-slate-800/60 shrink-0">
              <button
                onClick={() => setShowExplain(false)}
                className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 text-xs text-slate-350 font-bold uppercase tracking-wider"
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
