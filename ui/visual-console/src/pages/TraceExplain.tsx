import React, { useState, useEffect } from 'react';
import { Cpu, PlayCircle, ShieldAlert, Sparkles, ArrowRight } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

interface RunOption {
  run_id: string;
  scenario: string;
  status: string;
  timestamp: string;
}

interface ExplanationResult {
  run_id: string;
  status: string;
  analysis: {
    summary?: string;
    root_cause?: string;
    failed_turn_index?: number;
    remediation?: string;
    confidence?: number;
    verification_signature?: string;
    suggestion?: string;
    index?: number;
  };
}

export const TraceExplain: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialRunId = searchParams.get('run_id') || '';

  const [runs, setRuns] = useState<RunOption[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(initialRunId);
  const [loadingRuns, setLoadingRuns] = useState(false);

  const [explaining, setExplaining] = useState(false);
  const [result, setResult] = useState<ExplanationResult | null>(null);
  const [error, setError] = useState('');

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

  useEffect(() => {
    if (initialRunId) {
      setSelectedRunId(initialRunId);
    }
  }, [initialRunId]);

  const handleExplain = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!selectedRunId) return;

    setExplaining(true);
    setError('');
    setResult(null);

    try {
      const res = await fetch(`/api/v1/explain/${selectedRunId}`);
      const data = await res.json();
      if (res.ok) {
        setResult(data);
      } else {
        setError(data.error || 'Failed to explain trace.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error running trace explainer.');
    } finally {
      setExplaining(false);
    }
  };

  // Run automatically if run_id is in search params
  useEffect(() => {
    if (initialRunId && runs.length > 0) {
      handleExplain();
    }
  }, [initialRunId, runs.length]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" />
            <span>Trace Explain (AI)</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Invoke the core forensic Root-Cause Analysis (RCA) engine to diagnose trace run failure sequences and generate policy remediations.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Select Run form */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Select Target Run</span>
            </h3>

            {loadingRuns ? (
              <div className="text-xs text-slate-500 italic py-4">Loading active traces...</div>
            ) : runs.length === 0 ? (
              <div className="text-xs text-rose-400 py-4">No trace runs available. Run scenario tests first.</div>
            ) : (
              <form onSubmit={handleExplain} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Target Run ID</label>
                  <select
                    value={selectedRunId}
                    onChange={(e) => setSelectedRunId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    {runs.map((r) => (
                      <option key={r.run_id} value={r.run_id}>
                        {(r.run_id || '').slice(0, 12)}... ({(r.scenario || '').slice(0, 15)}...)
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="submit"
                  disabled={explaining || !selectedRunId}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
                >
                  <PlayCircle className="w-4 h-4" />
                  <span>{explaining ? 'Analyzing Trace...' : 'Run Diagnostics'}</span>
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right Side: RCA Report */}
        <div className="lg:col-span-2 space-y-4">
          {error && (
            <div className="p-4 bg-rose-500/10 border border-rose-500/25 rounded-xl text-rose-400 text-xs">
              {error}
            </div>
          )}

          {explaining ? (
            <div className="h-96 flex flex-col justify-center items-center gap-3 bg-slate-950/10 border border-slate-900 rounded-xl">
              <div className="w-8 h-8 border-4 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Executing forensic logs classifier...</span>
            </div>
          ) : !result ? (
            <div className="h-96 flex flex-col justify-center items-center gap-4 bg-slate-950/15 border border-slate-900 border-dashed rounded-xl text-slate-500 p-8 text-center">
              <ShieldAlert className="w-10 h-10 text-slate-800" />
              <h3 className="text-xs font-bold text-slate-400">RCA Diagnostic Output Pending</h3>
              <p className="text-[10px] text-slate-600 max-w-sm mx-auto leading-relaxed">
                Select a run trace from the left panel and click Run Diagnostics to extract turn-by-turn explanations of failures.
              </p>
            </div>
          ) : (
            <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-6 space-y-5 animate-slide-in">
              <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider">Root-Cause Analysis Report</h3>
                <span className="px-2 py-0.5 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded text-[9px] font-bold uppercase tracking-wider font-mono">
                  Confidence: {((result.analysis.confidence || 0.85) * 100).toFixed(0)}%
                </span>
              </div>

              <div className="space-y-4">
                {/* Summary */}
                <div className="space-y-1">
                  <span className="text-[9px] text-slate-500 font-bold uppercase">Executive Summary</span>
                  <p className="text-xs text-slate-200 leading-relaxed font-sans">
                    {result.analysis.summary || result.analysis.root_cause || 'No summary provided.'}
                  </p>
                </div>

                {/* Root Cause Details */}
                {result.analysis.summary && result.analysis.root_cause && (
                  <div className="space-y-1">
                    <span className="text-[9px] text-slate-500 font-bold uppercase">Identified Root Cause</span>
                    <p className="text-xs text-slate-350 leading-relaxed font-sans">{result.analysis.root_cause}</p>
                  </div>
                )}

                {/* Remediation */}
                {(result.analysis.remediation || result.analysis.suggestion) && (
                  <div className="p-4 bg-indigo-500/5 border border-indigo-500/10 rounded-lg space-y-2">
                    <span className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4 text-indigo-400" />
                      <span>Suggested Remediation Plan</span>
                    </span>
                    <p className="text-xs text-slate-300 leading-relaxed leading-normal">
                      {result.analysis.remediation || result.analysis.suggestion}
                    </p>
                  </div>
                )}

                <div className="flex flex-col sm:flex-row justify-between gap-4 border-t border-slate-900/60 pt-4 text-[10px] text-slate-500 font-mono">
                  <span>Run ID: {result.run_id}</span>
                  {(result.analysis.failed_turn_index !== undefined || result.analysis.index !== undefined) && (
                    <button
                      onClick={() => {
                        const targetIndex = result.analysis.failed_turn_index !== undefined 
                          ? result.analysis.failed_turn_index 
                          : result.analysis.index;
                        navigate(`/debugger?run_id=${result.run_id}&turn=${targetIndex}`);
                      }}
                      className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-bold"
                    >
                      <span>
                        Jump to turn {result.analysis.failed_turn_index !== undefined 
                          ? result.analysis.failed_turn_index 
                          : result.analysis.index} in Debugger
                      </span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
