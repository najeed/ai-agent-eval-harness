import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { UserCheck, Clock, PlayCircle, RefreshCw, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { useRBAC } from '../context/RBACContext';

interface HITLItem {
  id: string;
  run_id: string;
  task_id: string;
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'timeout' | null;
  timestamp: string;
  prompt: string;
  created_at: number;
  timeout_seconds: number;
  remaining_seconds: number;
}

export const HITLQueue: React.FC = () => {
  const navigate = useNavigate();
  const { canResolveHITL, role } = useRBAC();
  const [items, setItems] = useState<HITLItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  
  // Rejection modal state
  const [rejectingItem, setRejectingItem] = useState<HITLItem | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  // Custom approvals responses
  const [approvalResponses, setApprovalResponses] = useState<Record<string, string>>({});

  const fetchHITLItems = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/v1/hitl/queue');
      if (!res.ok) throw new Error(`Server returned status ${res.status}`);
      const data = await res.json();
      
      // Map properties to ensure consistency
      const mapped = (data.pending || []).map((item: any) => ({
        ...item,
        status: item.action ? item.action.toUpperCase() : 'PENDING_REVIEW'
      }));
      setItems(mapped);
    } catch (err: any) {
      setError(err.message || 'Failed to poll HITL queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHITLItems();

    // Setup EventSource for real-time updates
    const eventSource = new EventSource('/api/v1/hitl/stream');

    eventSource.addEventListener('create', (event: MessageEvent) => {
      try {
        const item = JSON.parse(event.data);
        setItems(prev => {
          // Check if already in list
          if (prev.some(i => i.id === item.id)) return prev;
          return [{ ...item, status: 'PENDING_REVIEW' }, ...prev];
        });
      } catch (err) {
        console.error('Error parsing SSE create event data:', err);
      }
    });

    eventSource.addEventListener('resolve', (event: MessageEvent) => {
      try {
        const resolvedItem = JSON.parse(event.data);
        // Remove item from pending list once resolved
        setItems(prev => prev.filter(i => i.id !== resolvedItem.id));
      } catch (err) {
        console.error('Error parsing SSE resolve event data:', err);
      }
    });

    eventSource.onerror = (err) => {
      console.warn('SSE connection closed or error encountered. Reconnecting...', err);
    };

    return () => {
      eventSource.close();
    };
  }, []);

  // SLA seconds countdown timer interval ticks
  useEffect(() => {
    const interval = setInterval(() => {
      setItems(prev =>
        prev.map(item => {
          const elapsed = Math.floor(Date.now() / 1000 - item.created_at);
          const remaining = Math.max(0, item.timeout_seconds - elapsed);
          return {
            ...item,
            remaining_seconds: remaining,
            status: remaining <= 0 ? 'timeout' : item.status
          };
        }).filter(item => item.remaining_seconds > 0) // Filter out fully timed out items from the visual queue
      );
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  const handleResolve = async (id: string, action: 'approve' | 'reject', customResponse?: string) => {
    if (resolvingId) return; // Prevent double-submit
    setResolvingId(id);
    setError('');

    try {
      const res = await fetch(`/api/v1/hitl/${id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          response: customResponse || (action === 'approve' ? 'Approved by human reviewer' : 'Rejected')
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || 'Failed to submit override decision.');
      }

      // Close reject modal if open
      setRejectingItem(null);
      setRejectReason('');
      
      // Re-fetch to synchronize state
      await fetchHITLItems();
      
      window.dispatchEvent(new CustomEvent('agentv-toast', {
        detail: { message: `Intervention request successfully ${action}d.`, type: 'success' }
      }));
    } catch (err: any) {
      setError(err.message || 'Failed to resolve HITL item.');
    } finally {
      setResolvingId(null);
    }
  };

  const formatSLA = (seconds: number) => {
    if (seconds <= 0) return 'EXPIRED';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <UserCheck className="w-5 h-5 text-indigo-400" />
            <span>Human-in-the-Loop Queue</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Real-time control center for auditing suspended execution steps requesting manual policy overrides.
          </p>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1 bg-slate-900/60 border border-slate-800 text-[10px] text-slate-400 rounded-lg flex items-center gap-1.5 font-mono">
            Role: <strong className="text-indigo-400">{role}</strong>
          </span>
          <button
            onClick={fetchHITLItems}
            className="p-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
            title="Refresh Queue"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!canResolveHITL && (
        <div className="p-3.5 bg-amber-500/10 border border-amber-500/25 rounded-xl text-amber-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Your active Persona context (<strong>{role}</strong>) does not have resolve privileges. Controls are in read-only audit mode.</span>
        </div>
      )}

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64 text-xs text-slate-500">
          Loading active reviews...
        </div>
      ) : items.length === 0 ? (
        <div className="bg-slate-950 border border-slate-900 border-dashed rounded-xl p-16 text-center text-slate-550 max-w-xl mx-auto">
          <CheckCircle className="w-10 h-10 text-emerald-500/30 mx-auto mb-3" />
          <h3 className="text-xs font-bold text-slate-400">HITL Queue Clear</h3>
          <p className="text-[10px] text-slate-600 mt-1">
            No agent evaluations are currently suspended or requesting manual interventions.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {items.map((item) => (
            <div
              key={item.id}
              className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 hover:border-slate-850 transition-all flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="flex justify-between items-start gap-2">
                  <div className="space-y-0.5">
                    <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono">Suspended Run ID</span>
                    <h3 className="text-xs font-bold text-white font-mono">{item.run_id}</h3>
                  </div>
                  <div className="flex gap-2 items-center">
                    <span className={`px-2 py-0.5 border text-[9px] font-bold uppercase tracking-wider rounded font-mono ${
                      item.remaining_seconds < 180 
                        ? 'bg-rose-500/10 border-rose-500/20 text-rose-400 animate-pulse'
                        : 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                    }`}>
                      SLA: {formatSLA(item.remaining_seconds)}
                    </span>
                    <span className="px-2 py-0.5 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded text-[9px] font-bold uppercase tracking-wider">
                      {item.status?.replace('_', ' ')}
                    </span>
                  </div>
                </div>

                <div className="p-3.5 bg-slate-950/80 border border-slate-850 rounded-lg space-y-2">
                  <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono block">Human Intervention Required</span>
                  <p className="text-xs text-slate-350 leading-relaxed font-sans italic">"{item.prompt}"</p>
                </div>
                
                {canResolveHITL && (
                  <div className="space-y-1.5">
                    <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono block">Custom Response Payload (Optional)</span>
                    <input
                      type="text"
                      value={approvalResponses[item.id] || ''}
                      onChange={(e) => setApprovalResponses(prev => ({ ...prev, [item.id]: e.target.value }))}
                      placeholder="e.g. Approved under safety override key PQC-99..."
                      className="w-full bg-slate-950 border border-slate-900 rounded px-2.5 py-1 text-xs text-slate-300 focus:outline-none focus:border-indigo-600 transition-colors placeholder:text-slate-700"
                    />
                  </div>
                )}
              </div>

              <div className="border-t border-slate-900/60 pt-4 mt-2 space-y-3">
                <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    {new Date(item.created_at * 1000).toLocaleTimeString()}
                  </span>
                  <span>Task ID: {item.task_id}</span>
                </div>

                <div className="flex gap-2">
                  <button
                    disabled={!canResolveHITL || resolvingId !== null}
                    onClick={() => handleResolve(item.id, 'approve', approvalResponses[item.id])}
                    className="flex-1 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-900/50 text-white disabled:text-slate-600 rounded text-[10px] font-bold border border-indigo-500/25 transition-all text-center"
                  >
                    {resolvingId === item.id ? 'Resolving...' : 'Approve'}
                  </button>
                  <button
                    disabled={!canResolveHITL || resolvingId !== null}
                    onClick={() => setRejectingItem(item)}
                    className="flex-1 py-1.5 bg-rose-600/10 hover:bg-rose-600/20 disabled:bg-transparent text-rose-400 disabled:text-slate-600 rounded text-[10px] font-bold border border-rose-500/25 disabled:border-slate-900 transition-all text-center"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => navigate(`/debugger?run_id=${item.run_id}`)}
                    className="py-1.5 px-3 bg-slate-900 hover:bg-slate-850 text-slate-300 rounded text-[10px] font-bold border border-slate-800 flex items-center justify-center gap-1 transition-all"
                  >
                    <PlayCircle className="w-3.5 h-3.5" />
                    <span>Debugger</span>
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Rejection Justification Modal */}
      {rejectingItem && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-950 border border-slate-900 rounded-2xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 border-b border-slate-900 pb-3">
              <XCircle className="w-5 h-5 text-rose-500" />
              <h3 className="text-sm font-bold text-white">Rejection Audit Log</h3>
            </div>
            
            <p className="text-xs text-slate-400 leading-relaxed">
              To reject intervention request for run <strong>{rejectingItem.run_id}</strong>, please supply an audit justification:
            </p>

            <textarea
              required
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Provide reasoning for rejection (required)..."
              rows={3}
              className="w-full bg-slate-950 border border-slate-900 rounded-xl p-3 text-xs text-slate-300 focus:outline-none focus:border-indigo-600 placeholder:text-slate-700"
            />

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setRejectingItem(null);
                  setRejectReason('');
                }}
                className="px-3.5 py-1.5 bg-slate-900 hover:bg-slate-850 border border-slate-800 text-slate-400 rounded-lg text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                disabled={!rejectReason.trim() || resolvingId !== null}
                onClick={() => handleResolve(rejectingItem.id, 'reject', rejectReason.trim())}
                className="px-4 py-1.5 bg-rose-600 hover:bg-rose-500 disabled:bg-rose-950 disabled:text-rose-700 text-white rounded-lg text-xs font-semibold"
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
