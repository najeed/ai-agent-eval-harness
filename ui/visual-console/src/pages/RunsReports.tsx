import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Search,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  Download,
  Eye,
} from 'lucide-react';
import { RunDetailView } from '../components/RunDetailView';

interface RunItem {
  run_id: string;
  scenario: string;
  timestamp: string;
  status?: string;
  verdict?: string;
  score?: number;
  duration?: number;
  agent?: string;
  resultStatus?: 'PASS' | 'FAIL';
  has_certificate?: boolean;
  manifest?: any;
}

const formatStarted = (ts: string | undefined): string => {
  if (!ts) return '—';
  const parsed = new Date(ts);
  if (isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

export const RunsReports: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdParam = searchParams.get('run_id');
  const activeView = searchParams.get('view') === 'packages' ? 'packages' : 'history';

  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Filtering & Search
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');

  // Active selected run for canonical inspection
  const [selectedRun, setSelectedRun] = useState<RunItem | null>(null);

  const setViewMode = (mode: 'history' | 'packages') => {
    const nextParams = new URLSearchParams(searchParams);
    if (mode === 'packages') {
      nextParams.set('view', 'packages');
    } else {
      nextParams.delete('view');
    }
    setSearchParams(nextParams);
  };


  const fetchRuns = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      const loaded: any[] = data.runs || [];
      // The server's verification_status is authoritative (cert trace-hash
      // vs current-trace compare). The client NEVER infers a verdict from
      // certificate presence or pass/fail status; absent verdicts are UNKNOWN.
      const parsedRuns: RunItem[] = loaded.map((r) => {
        // Server verdict is authoritative across the FULL literal set:
        // VERIFIED | FAILED_VERIFICATION | NOT_EXECUTED | ERROR | UNKNOWN.
        const verdict: string = r.verification_status || 'UNKNOWN';
        return {
          run_id: r.run_id,
          scenario: r.scenario || r.run_id,
          timestamp: r.timestamp || 'N/A',
          status: r.execution_status || r.status || 'UNKNOWN',
          verdict: verdict,
          score: r.score ?? undefined,
          duration: r.duration_seconds ?? r.duration ?? undefined,
          agent: r.identifier || undefined,
          resultStatus: r.result_status || undefined,
          traceIntegrity: r.trace_integrity || undefined,
          has_certificate: !!r.has_certificate,
        };
      });
      setRuns(parsedRuns);

      if (runIdParam) {
        const found = parsedRuns.find((r) => r.run_id === runIdParam);
        if (found) setSelectedRun(found);
      }
    } catch (e) {
      console.error('Error loading runs:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, [runIdParam]);

  const filteredRuns = runs.filter((r) => {
    const matchesSearch =
      r.run_id.toLowerCase().includes(search.toLowerCase()) ||
      r.scenario.toLowerCase().includes(search.toLowerCase());
    const matchesStatus =
      statusFilter === 'All' ||
      r.verdict === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      {/* If a run is selected for canonical inspection, show full RunDetailView */}
      {selectedRun ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              onClick={() => setSelectedRun(null)}
              className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 flex items-center gap-1.5 transition"
            >
              ← Back to All Runs & Evidence Packages
            </button>
          </div>
          <RunDetailView run={selectedRun as any} onClose={() => setSelectedRun(null)} />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Header & View Mode Switcher */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-white tracking-tight">
                  {activeView === 'packages' ? 'Evidence Packages & Verification' : 'Active & History Runs'}
                </h1>
                <span className="px-2.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider bg-indigo-500/10 border border-indigo-500/30 text-indigo-300">
                  {activeView === 'packages' ? 'Audit & Artifacts' : 'Execution Logs'}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                {activeView === 'packages'
                  ? 'Authoritative cryptographic audit bundles, ML-DSA-65 / Ed25519 sealed manifests, and offline verification packages.'
                  : 'Authoritative execution history, state transition verdicts, and continuous evaluation telemetry.'}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {/* Tab Selector */}
              <div className="flex bg-slate-950 border border-slate-800 rounded-lg p-1">
                <button
                  onClick={() => setViewMode('history')}
                  className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${activeView === 'history'
                    ? 'bg-slate-800 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                    }`}
                >
                  Active & History
                </button>
                <button
                  onClick={() => setViewMode('packages')}
                  className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${activeView === 'packages'
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                    }`}
                >
                  Evidence Packages
                </button>
              </div>

              <button
                onClick={fetchRuns}
                className="px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 text-xs font-semibold flex items-center gap-2 transition"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>


          {/* Search & Filter Bar */}
          <div className="flex flex-col sm:flex-row items-center gap-3 bg-slate-900/60 p-3 rounded-xl border border-slate-800">
            <div className="relative flex-1 w-full">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                placeholder="Search run ID or scenario..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-4 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
              {[
                { key: 'All', label: 'All' },
                { key: 'VERIFIED', label: 'Verified' },
                { key: 'FAILED_VERIFICATION', label: 'Failed Verification' },
                { key: 'NOT_EXECUTED', label: 'Not Executed' },
                { key: 'ERROR', label: 'Error' },
                { key: 'UNKNOWN', label: 'Unknown' },
              ].map((st) => (

                <button
                  key={st.key}
                  onClick={() => setStatusFilter(st.key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${statusFilter === st.key
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                    }`}
                >
                  {st.label}
                </button>
              ))}
            </div>
          </div>

          {/* Master Runs Table */}
          <div className="bg-slate-900/80 rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300 min-w-[800px]">
                <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider font-mono">
                  <tr>
                    <th className="px-6 py-3.5 font-semibold min-w-[220px]">Scenario</th>
                    <th className="px-6 py-3.5 font-semibold whitespace-nowrap">Agent</th>
                    <th className="px-6 py-3.5 font-semibold whitespace-nowrap">Verification Verdict</th>
                    <th className="px-6 py-3.5 font-semibold whitespace-nowrap">Started</th>
                    <th className="px-6 py-3.5 font-semibold whitespace-nowrap">Duration</th>
                    <th className="px-6 py-3.5 font-semibold text-right min-w-[260px] whitespace-nowrap">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {filteredRuns.map((r) => {
                    //Server-authoritative verdict only, no inference.
                    const isVer = r.verdict === 'VERIFIED';
                    const isFailed = r.verdict === 'FAILED_VERIFICATION';
                    const verdictLabel = isVer
                      ? 'Verified'
                      : isFailed
                        ? 'Failed Verification'
                        : 'Unknown';

                    return (
                      <tr key={r.run_id} className="hover:bg-slate-850/50 transition">
                        <td className="px-6 py-4 font-sans font-medium text-white max-w-[280px]">
                          <div className="truncate" title={r.scenario}>{r.scenario}</div>
                          <button
                            onClick={() => navigator.clipboard?.writeText(r.run_id)}
                            title="Copy run ID"
                            className="mt-1 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[9px] font-mono text-slate-400 hover:text-indigo-300 align-middle"
                          >
                            {r.run_id.length > 14 ? r.run_id.slice(0, 14) + '…' : r.run_id} ⧉
                          </button>
                        </td>
                        <td className="px-6 py-4 font-sans text-slate-400 max-w-[180px] truncate" title={r.agent || 'Unknown agent'}>
                          {r.agent || '—'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span
                            title={
                              isVer
                                ? 'Certificate trace-hash matches the current trace (server-verified).'
                                : isFailed
                                  ? 'Certificate trace-hash does NOT match the current trace.'
                                  : 'No certificate available, or the server could not verify this run.'
                            }
                            className={`px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider inline-flex items-center gap-1.5 ${isVer
                              ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                              : isFailed
                                ? 'bg-red-500/10 border border-red-500/20 text-red-400'
                                : 'bg-slate-500/10 border border-slate-500/20 text-slate-400'
                              }`}
                          >
                            {isVer ? <ShieldCheck className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                            {verdictLabel}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-slate-400 whitespace-nowrap" title={r.timestamp}>
                          {formatStarted(r.timestamp)}
                        </td>
                        <td className="px-6 py-4 text-slate-400 whitespace-nowrap">
                          {r.duration != null ? `${r.duration.toFixed(1)}s` : '-'}
                        </td>
                        <td className="px-6 py-4 text-right whitespace-nowrap min-w-[260px]">
                          <div className="flex items-center justify-end gap-2 font-sans">
                            <button
                              onClick={() => setSelectedRun(r)}
                              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition"
                            >
                              <Eye className="w-3.5 h-3.5 text-indigo-400" />
                              Inspect Detail
                            </button>
                            <a
                              href={`/api/v1/evidence/packages/${r.run_id}?download=true`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="px-3 py-1.5 rounded-lg bg-indigo-950/60 hover:bg-indigo-900 border border-indigo-500/30 text-indigo-300 text-xs font-semibold flex items-center gap-1.5 transition"
                            >
                              <Download className="w-3.5 h-3.5" />
                              Package
                            </a>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}
    </div>
  );
};

