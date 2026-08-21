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
  verdict?: 'VERIFIED' | 'NOT_VERIFIED' | 'POLICY_BREACH' | 'UNVERIFIED';
  score?: number;
  duration?: number;
  has_certificate?: boolean;
  manifest?: any;
}

export const RunsReports: React.FC = () => {
  const [searchParams] = useSearchParams();
  const runIdParam = searchParams.get('run_id');


  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Filtering & Search
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');

  // Active selected run for canonical inspection
  const [selectedRun, setSelectedRun] = useState<RunItem | null>(null);

  const fetchRuns = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      const loaded: any[] = data.runs || [];
      const parsedRuns: RunItem[] = loaded.map((r) => {
        const isCert = !!r.has_certificate;
        const verdict = r.verification_status || (isCert ? 'VERIFIED' : r.passed === false ? 'NOT_VERIFIED' : 'UNVERIFIED');
        return {
          run_id: r.run_id,
          scenario: r.scenario || r.run_id,
          timestamp: r.timestamp || 'N/A',
          status: r.execution_status || r.status || 'UNKNOWN',
          verdict: verdict,
          score: r.score ?? undefined,
          duration: r.duration_seconds ?? r.duration ?? undefined,
          has_certificate: isCert,
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
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-white tracking-tight">Runs & Verification Evidence</h1>
              <p className="text-xs text-slate-400">
                Authoritative execution history, state transition verdicts, and downloadable Verification Packages.
              </p>
            </div>

            <div className="flex items-center gap-3">
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

            <div className="flex items-center gap-2 w-full sm:w-auto">
              {['All', 'VERIFIED', 'NOT_VERIFIED', 'POLICY_BREACH', 'UNVERIFIED'].map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${statusFilter === st
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                    }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {/* Master Runs Table */}
          <div className="bg-slate-900/80 rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950/80 border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider font-mono">
                <tr>
                  <th className="px-6 py-3.5 font-semibold">Run ID</th>
                  <th className="px-6 py-3.5 font-semibold">Scenario Target</th>
                  <th className="px-6 py-3.5 font-semibold">Verification Verdict</th>
                  <th className="px-6 py-3.5 font-semibold">Duration</th>
                  <th className="px-6 py-3.5 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {filteredRuns.map((r) => {
                  const isVer = r.verdict === 'VERIFIED';
                  const isBreach = r.verdict === 'POLICY_BREACH';
                  return (
                    <tr key={r.run_id} className="hover:bg-slate-850/50 transition">
                      <td className="px-6 py-4 font-bold text-slate-200">{r.run_id}</td>
                      <td className="px-6 py-4 font-sans font-medium text-white">{r.scenario}</td>
                      <td className="px-6 py-4">
                        <span
                          className={`px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider inline-flex items-center gap-1.5 ${isVer
                              ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                              : isBreach
                                ? 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
                                : 'bg-amber-500/10 border border-amber-500/20 text-amber-400'
                            }`}
                        >
                          {isVer ? <ShieldCheck className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                          {r.verdict || 'UNVERIFIED'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-400">
                        {r.duration != null ? `${r.duration.toFixed(1)}s` : '-'}
                      </td>
                      <td className="px-6 py-4 text-right">

                        <div className="flex items-center justify-end gap-2 font-sans">
                          <button
                            onClick={() => setSelectedRun(r)}
                            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition"
                          >
                            <Eye className="w-3.5 h-3.5 text-indigo-400" />
                            Inspect 7-Tab Detail
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
      )}
    </div>
  );
};
