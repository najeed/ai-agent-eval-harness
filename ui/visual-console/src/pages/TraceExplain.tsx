import React, { useState, useEffect } from 'react';
import { Cpu, PlayCircle, Sparkles } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

interface RunOption {
  run_id: string;
  scenario: string;
  status: string;
  timestamp: string;
}

export const TraceExplain: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialRunId = searchParams.get('run_id') || '';

  const [runs, setRuns] = useState<RunOption[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(initialRunId);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // Auto-redirect if run_id is already present in url query parameters
  useEffect(() => {
    if (initialRunId) {
      navigate(`/debugger?run_id=${initialRunId}&explain=true`, { replace: true });
    }
  }, [initialRunId, navigate]);

  const fetchRuns = async () => {
    setLoadingRuns(true);
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      if (res.ok && data.runs) {
        setRuns(data.runs);
        if (data.runs.length > 0 && !selectedRunId) {
          setSelectedRunId(data.runs[0].run_id);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingRuns(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleTriggerRedirect = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedRunId) {
      navigate(`/debugger?run_id=${selectedRunId}&explain=true`);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" />
            <span>Trace Explain Diagnostics</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Redirecting to visual debugger inline diagnostics panels. Select a run below to initialize.
          </p>
        </div>
      </div>

      <div className="max-w-xl mx-auto">
        <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-6 space-y-4">
          <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles className="w-4 h-4 text-indigo-400" />
            <span>Select Target Run</span>
          </h3>

          {loadingRuns ? (
            <div className="text-xs text-slate-500 italic py-4 text-center">Loading run traces...</div>
          ) : runs.length === 0 ? (
            <div className="text-xs text-rose-400 py-4 text-center">No trace runs available. Execute evaluations first.</div>
          ) : (
            <form onSubmit={handleTriggerRedirect} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-[9px] text-slate-500 font-bold uppercase font-mono">Target Run ID</label>
                <select
                  value={selectedRunId}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer font-mono"
                >
                  {runs.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} ({r.status})
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={!selectedRunId}
                className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                <PlayCircle className="w-4 h-4" />
                <span>Open in Debugger with Explain Panel</span>
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
