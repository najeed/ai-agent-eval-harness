import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { UserCheck, Clock, PlayCircle, RefreshCw } from 'lucide-react';

interface HITLItem {
  run_id: string;
  task_id: string;
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
  timestamp: string;
  prompt: string;
  agent_identity: string;
}

export const HITLQueue: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<HITLItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchHITLItems = async () => {
    setLoading(true);
    setError('');
    try {
      // Simulate reading trace events to locate runs suspended or requesting input
      // Pre-populate with typical scenarios to show high-fidelity active items
      const mockItems: HITLItem[] = [
        {
          run_id: 'test_run_sse',
          task_id: 'loan_app_task_01',
          status: 'PENDING_REVIEW',
          timestamp: new Date().toISOString(),
          prompt: 'Authorize loan approval override for applicant credit score below 600.',
          agent_identity: 'Financial-Auditor-v1',
        },
        {
          run_id: 'r1',
          task_id: 'pqc_manifest_gate_02',
          status: 'PENDING_REVIEW',
          timestamp: new Date(Date.now() - 3600000).toISOString(),
          prompt: 'Confirm quantum-safe key algorithm ML-DSA-65 validation bypass.',
          agent_identity: 'Trust-Center-Sealer',
        }
      ];
      setItems(mockItems);
    } catch (err: any) {
      setError(err.message || 'Failed to poll HITL queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHITLItems();
  }, []);

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
            Audit trace events for runs suspended requesting external human validation. Interactive approve/reject triggers are executed via the CLI.
          </p>
        </div>
        <button
          onClick={fetchHITLItems}
          className="p-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
          title="Refresh Queue"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64 text-xs text-slate-500">
          Loading HITL events...
        </div>
      ) : items.length === 0 ? (
        <div className="bg-slate-950 border border-slate-900 border-dashed rounded-xl p-16 text-center text-slate-550 max-w-xl mx-auto">
          <UserCheck className="w-10 h-10 text-slate-800 mx-auto mb-3" />
          <h3 className="text-xs font-bold text-slate-400">HITL Queue Clear</h3>
          <p className="text-[10px] text-slate-600 mt-1">
            No agent evaluations are currently suspended or requesting human-in-the-loop review overrides.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {items.map((item) => (
            <div
              key={item.run_id}
              className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 hover:border-slate-850 transition-all flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="flex justify-between items-start gap-2">
                  <div className="space-y-0.5">
                    <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono">Agent Identity</span>
                    <h3 className="text-xs font-bold text-white">{item.agent_identity}</h3>
                  </div>
                  <span className="px-2 py-0.5 bg-amber-500/10 border border-amber-500/20 text-amber-400 rounded text-[9px] font-bold uppercase tracking-wider animate-pulse">
                    {item.status.replace('_', ' ')}
                  </span>
                </div>

                <div className="p-3 bg-slate-950/80 border border-slate-850 rounded-lg space-y-2">
                  <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono block">Pending Request Prompt</span>
                  <p className="text-xs text-slate-350 leading-relaxed font-sans italic">"{item.prompt}"</p>
                </div>
              </div>

              <div className="border-t border-slate-900/60 pt-4 mt-2 space-y-3">
                <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    {new Date(item.timestamp).toLocaleTimeString()}
                  </span>
                  <span>Run ID: {item.run_id}</span>
                </div>

                {/* Read-Only action banner */}
                <div className="p-2.5 bg-indigo-500/5 border border-indigo-500/10 rounded text-[10px] text-indigo-400 font-medium leading-relaxed italic text-center">
                  * Interactive override inputs are locked on the visual console. Provide approval tokens directly in the background CLI thread.
                </div>

                <div className="flex gap-2">
                  <button
                    disabled
                    className="flex-1 py-1.5 bg-slate-900/50 text-slate-600 rounded text-[10px] font-bold border border-slate-900"
                  >
                    Approve Request
                  </button>
                  <button
                    onClick={() => navigate(`/debugger?run_id=${item.run_id}`)}
                    className="flex-1 py-1.5 bg-indigo-600/15 hover:bg-indigo-600/30 text-indigo-300 rounded text-[10px] font-bold border border-indigo-500/20 flex items-center justify-center gap-1.5 transition-all"
                  >
                    <PlayCircle className="w-3.5 h-3.5" />
                    <span>View Suspended Trace</span>
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
