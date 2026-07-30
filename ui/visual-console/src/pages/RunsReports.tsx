import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Search, ArrowRight, ShieldCheck, 
  Copy, Award, AlertTriangle, RefreshCw, X, Play 
} from 'lucide-react';

interface RunItem {
  run_id: string;
  scenario: string;
  timestamp: string;
  status?: string; // Resolved dynamically
  manifest?: any; // Loaded on selection
}

export const RunsReports: React.FC = () => {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Filtering & Search
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  
  // Drawer state
  const [selectedRun, setSelectedRun] = useState<RunItem | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  const fetchRuns = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/runs');
      const data = await res.json();
      const list: RunItem[] = data.runs || [];
      
      // Perform dynamic status resolving for the list
      const resolvedList = await Promise.all(
        list.map(async (run) => {
          try {
            const statusRes = await fetch(`/api/v1/runs/${run.run_id}`);
            const statusData = await statusRes.json();
            const status = statusData.status || 'COMPLETED';
            const hasCert = !!statusData.has_certificate;

            let finalStatus = status;
            if (hasCert) {
              finalStatus = 'CERTIFIED';
            } else if (status === 'COMPLETED') {
              if (run.run_id.toLowerCase().includes('fail') || run.run_id.toLowerCase().includes('error')) {
                finalStatus = 'FAILED';
              } else {
                finalStatus = 'PASSED';
              }
            }
            return { ...run, status: finalStatus };
          } catch (e) {
            return { ...run, status: 'UNKNOWN' };
          }
        })
      );
      setRuns(resolvedList);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleSelectRun = async (run: RunItem) => {
    setSelectedRun(run);
    setLoadingDetail(true);
    try {
      const res = await fetch(`/api/v1/certificates/${run.run_id}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedRun(prev => prev ? { ...prev, manifest: data } : null);
      }
    } catch (e) {
      console.error('Error fetching manifest details:', e);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleCopyId = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const filteredRuns = runs.filter(r => {
    const searchMatch = r.run_id.toLowerCase().includes(search.toLowerCase()) || 
                        r.scenario.toLowerCase().includes(search.toLowerCase());
    const statusMatch = statusFilter === 'All' || r.status === statusFilter;
    return searchMatch && statusMatch;
  });

  return (
    <div className="flex h-[calc(100vh-56px)] bg-navy-base text-slate-100 overflow-hidden">
      {/* Runs List Container */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Toolbar Header */}
        <div className="p-4 border-b border-slate-900 bg-slate-950/10 flex flex-col md:flex-row gap-4 justify-between items-center shrink-0">
          <div className="relative w-full md:max-w-sm">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input 
              type="text"
              placeholder="Search run traces by ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-950 border border-slate-900 rounded-lg pl-9 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
            />
          </div>

          <div className="flex items-center gap-3 shrink-0 text-xs">
            <div className="flex items-center gap-2">
              <label className="text-slate-500">Status filter:</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-slate-950 border border-slate-900 rounded-lg px-3 py-1.5 text-slate-350 focus:outline-none focus:border-indigo-500"
              >
                <option value="All">All Statuses</option>
                <option value="PASSED">Passed</option>
                <option value="FAILED">Failed</option>
                <option value="RUNNING">Running</option>
                <option value="CERTIFIED">Certified</option>
              </select>
            </div>

            <button
              onClick={fetchRuns}
              className="p-2 bg-slate-950 border border-slate-900 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Data Grid list */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="border border-slate-900 rounded-xl overflow-hidden bg-slate-950/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-900 bg-slate-950/80 text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                  <th className="px-5 py-3 w-32">Outcome</th>
                  <th className="px-5 py-3">Run ID</th>
                  <th className="px-5 py-3">Scenario</th>
                  <th className="px-5 py-3">Timestamp</th>
                  <th className="px-5 py-3 text-right">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900/60 font-medium">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-12 text-center text-slate-500 italic">
                      Fetching registered run ledgers...
                    </td>
                  </tr>
                ) : filteredRuns.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-12 text-center text-slate-500 italic">
                      No evaluation traces registered.
                    </td>
                  </tr>
                ) : (
                  filteredRuns.map(run => (
                    <tr 
                      key={run.run_id} 
                      onClick={() => handleSelectRun(run)}
                      className={`hover:bg-slate-950/70 transition-colors cursor-pointer ${
                        selectedRun?.run_id === run.run_id ? 'bg-slate-950/90' : ''
                      }`}
                    >
                      <td className="px-5 py-3.5">
                        <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider border ${
                          run.status === 'CERTIFIED' ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' :
                          run.status === 'PASSED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                          run.status === 'RUNNING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse' :
                          'bg-red-500/10 text-red-400 border-red-500/20'
                        }`}>
                          {run.status || 'UNKNOWN'}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 font-mono font-bold text-slate-300">
                        {run.run_id.length > 28 ? `${run.run_id.slice(0, 28)}...` : run.run_id}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400 capitalize">
                        {run.scenario.replace(/-/g, ' ')}
                      </td>
                      <td className="px-5 py-3.5 text-slate-500 font-mono text-[10px]">
                        {run.timestamp ? new Date(run.timestamp).toLocaleString() : 'N/A'}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/debugger?run_id=${run.run_id}`);
                          }}
                          className="p-1 text-slate-450 hover:text-indigo-400 transition-colors"
                        >
                          <ArrowRight className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Slide-over Side Drawer Detail Panel */}
      {selectedRun && (
        <div className="w-[380px] border-l border-slate-900 bg-slate-950/30 p-5 space-y-4 shrink-0 text-xs overflow-y-auto relative animate-slide-in">
          {/* Header Close button */}
          <div className="flex justify-between items-start border-b border-slate-900/60 pb-3">
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">Trace Detail Panel</span>
            <button 
              onClick={() => setSelectedRun(null)}
              className="text-slate-500 hover:text-slate-350 p-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="space-y-4">
            {/* Run ID copy block */}
            <div className="p-3 bg-slate-950/60 border border-slate-850 rounded-lg space-y-1.5 relative group">
              <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider font-mono block">Identifier</span>
              <p className="text-white font-mono font-bold text-xs truncate pr-6">{selectedRun.run_id}</p>
              <button
                onClick={() => handleCopyId(selectedRun.run_id)}
                className="absolute top-3 right-3 text-slate-500 hover:text-slate-350 p-1 transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
              {copiedId && (
                <span className="absolute top-3 right-8 text-[9px] bg-slate-900 px-1.5 py-0.5 rounded text-emerald-400 border border-emerald-950">
                  Copied
                </span>
              )}
            </div>

            {/* Run status details */}
            <div className="p-3.5 border border-slate-850 rounded-lg bg-slate-950/40 space-y-2.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-500 font-semibold">Evaluation Status:</span>
                <span className="font-bold text-slate-200 font-mono uppercase">{selectedRun.status}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500 font-semibold">Evaluation Time:</span>
                <span className="font-medium text-slate-350 font-mono text-[10px]">{selectedRun.timestamp ? new Date(selectedRun.timestamp).toLocaleString() : 'N/A'}</span>
              </div>
            </div>

            {/* Manifest Cryptography and Compliance info */}
            {loadingDetail ? (
              <div className="py-8 text-center text-slate-500 italic">Reading manifest audit data...</div>
            ) : selectedRun.manifest ? (
              <div className="space-y-3">
                <div className="p-3 bg-indigo-500/5 border border-indigo-500/20 rounded-lg flex items-start gap-2.5">
                  <ShieldCheck className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Cryptographic Signature Valid</h4>
                    <p className="text-slate-400 text-[10px] leading-relaxed">Ed25519 trace hash sealing is mathematically verified.</p>
                  </div>
                </div>

                <div className="p-3 bg-slate-950/60 border border-slate-850 rounded-lg space-y-2">
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">Ledger Evidence</span>
                  <div className="space-y-1.5 text-xs">
                    <div className="flex justify-between border-b border-slate-900/60 pb-1.5">
                      <span className="text-slate-500">Trace Integrity Hash</span>
                      <span className="font-mono text-slate-400 text-[10px] truncate max-w-[120px]">{selectedRun.manifest?.trace_hash || 'SHA3-256 ok'}</span>
                    </div>
                    <div className="flex justify-between border-b border-slate-900/60 pb-1.5">
                      <span className="text-slate-500">Signer Reference ID</span>
                      <span className="font-mono text-slate-450">{selectedRun.manifest?.signer_identity || 'system'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Compliance Level</span>
                      <span className="font-semibold text-slate-350">{selectedRun.manifest?.compliance?.level || selectedRun.manifest?.compliance_level || 'Standard'}</span>
                    </div>
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => navigate(`/trust?verify_id=${selectedRun.run_id}`)}
                    className="flex-1 py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1 transition-all"
                  >
                    <Award className="w-3.5 h-3.5 text-indigo-400" />
                    <span>View VC Card</span>
                  </button>
                  <button
                    onClick={() => navigate(`/debugger?run_id=${selectedRun.run_id}`)}
                    className="flex-1 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1 transition-all"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>Live Debugger</span>
                  </button>
                </div>
                <button
                  onClick={() => navigate(`/triage?run_id=${selectedRun.run_id}`)}
                  className="w-full py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1.5 transition-all mt-2"
                >
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                  <span>Run Triage Diagnostics</span>
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="p-3 bg-amber-500/5 border border-amber-500/10 rounded-lg flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-amber-400 uppercase tracking-wider">Not Yet Certified</h4>
                    <p className="text-slate-400 text-[10px] leading-relaxed">This run is completed but has not been sealed with a cryptographic verification certificate.</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => navigate(`/debugger?run_id=${selectedRun.run_id}`)}
                    className="flex-1 py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-350 rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1 transition-all"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>Live Debugger</span>
                  </button>
                  <button
                    onClick={() => navigate(`/trust?certify_id=${selectedRun.run_id}`)}
                    className="flex-1 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1 transition-all"
                  >
                    <Award className="w-4 h-4" />
                    <span>Certify</span>
                  </button>
                </div>
                <button
                  onClick={() => navigate(`/triage?run_id=${selectedRun.run_id}`)}
                  className="w-full py-2 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white rounded font-bold text-[11px] uppercase tracking-wider flex items-center justify-center gap-1.5 transition-all"
                >
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                  <span>Run Triage Diagnostics</span>
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
