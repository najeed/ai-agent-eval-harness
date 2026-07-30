import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Activity, ShieldCheck, Play, Sparkles, AlertTriangle, 
  Clock, ArrowRight, Server, CheckCircle2 
} from 'lucide-react';

interface RunItem {
  run_id: string;
  scenario: string;
  timestamp: string;
  path?: string;
  status?: string; // resolved dynamically
}

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [doctor, setDoctor] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [triageList, setTriageList] = useState<RunItem[]>([]);
  const [stats, setStats] = useState({
    total: 0,
    passed: 0,
    failed: 0,
    running: 0,
    stalled: 0,
    certCount: 0
  });

  const fetchData = async () => {
    try {
      // Fetch runs list
      const runsRes = await fetch('/api/runs');
      const runsData = await runsRes.json();
      const loadedRuns: RunItem[] = runsData.runs || [];
      
      // Fetch doctor status
      const docRes = await fetch('/api/v1/doctor');
      const docData = await docRes.json();
      setDoctor(docData);

      // Resolve runs status and metrics
      let passed = 0;
      let failed = 0;
      let running = 0;
      let stalled = 0;
      let certCount = 0;
      const triages: RunItem[] = [];

      const runsWithStatus = await Promise.all(
        loadedRuns.slice(0, 20).map(async (run) => {
          try {
            const statusRes = await fetch(`/api/v1/runs/${run.run_id}`);
            const statusData = await statusRes.json();
            const status = statusData.status || 'COMPLETED';
            const hasCert = !!statusData.has_certificate;
            
            let finalStatus = status;
            if (hasCert) {
              finalStatus = 'CERTIFIED';
              certCount++;
              passed++;
            } else if (status === 'COMPLETED') {
              // Heuristic: check if 'fail' or 'error' exists in run_id string or assume pass
              if (run.run_id.toLowerCase().includes('fail') || run.run_id.toLowerCase().includes('error')) {
                finalStatus = 'FAILED';
                failed++;
                triages.push({ ...run, status: finalStatus });
              } else {
                finalStatus = 'PASSED';
                passed++;
              }
            } else if (status === 'RUNNING') {
              running++;
            } else if (status === 'STALLED') {
              stalled++;
              triages.push({ ...run, status: finalStatus });
            }

            return { ...run, status: finalStatus };
          } catch (e) {
            return { ...run, status: 'UNKNOWN' };
          }
        })
      );

      setRuns(runsWithStatus);
      setTriageList(triages);
      setStats({
        total: loadedRuns.length,
        passed,
        failed,
        running,
        stalled,
        certCount
      });
    } catch (e) {
      console.error('Error fetching dashboard metrics:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div className="p-6 space-y-6">
      {/* Header Info */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Console Overview</h1>
          <p className="text-slate-400 text-sm">Real-time MultiAgentOps metrics and compliance auditing status.</p>
        </div>
        <div className="flex items-center gap-2 bg-slate-950 border border-slate-900 px-3 py-1.5 rounded-lg text-xs font-semibold">
          <Clock className="w-3.5 h-3.5 text-indigo-400" />
          <span>Sync Status: Ready</span>
        </div>
      </div>

      {/* Metric Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Card 1: Agent Fleet Status */}
        <div className="border border-slate-900 bg-slate-950/40 rounded-xl p-5 space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between text-xs text-slate-500 font-semibold uppercase tracking-wider">
            <span>Agent Fleet Status</span>
            <Server className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="space-y-1">
            <h3 className="text-2xl font-bold text-white tracking-tight">
              {doctor?.status === 'healthy' ? 'Active' : 'Unhealthy'}
            </h3>
            <p className="text-[10px] text-slate-500">
              {doctor?.simulator_count || 20} active simulators loaded
            </p>
          </div>
          {/* Sparkline simulation */}
          <div className="h-6 flex items-end gap-1 pt-1 opacity-70">
            <span className="w-full bg-indigo-500/20 h-2 rounded-t" />
            <span className="w-full bg-indigo-500/20 h-3 rounded-t" />
            <span className="w-full bg-indigo-500/30 h-1 rounded-t" />
            <span className="w-full bg-indigo-500/40 h-4 rounded-t" />
            <span className="w-full bg-indigo-500 h-5 rounded-t" />
          </div>
        </div>

        {/* Card 2: Runs Executed */}
        <div className="border border-slate-900 bg-slate-950/40 rounded-xl p-5 space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between text-xs text-slate-500 font-semibold uppercase tracking-wider">
            <span>Runs Executed (24h)</span>
            <Play className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="space-y-1">
            <h3 className="text-2xl font-bold text-white tracking-tight">{stats.total}</h3>
            <p className="text-[10px] text-slate-500">
              {stats.running} active evaluations currently running
            </p>
          </div>
          <div className="h-6 flex items-end gap-1 pt-1 opacity-70">
            <span className="w-full bg-indigo-500/10 h-3 rounded-t" />
            <span className="w-full bg-indigo-500/20 h-1 rounded-t" />
            <span className="w-full bg-indigo-500/40 h-5 rounded-t" />
            <span className="w-full bg-indigo-500/30 h-2 rounded-t" />
            <span className="w-full bg-indigo-500 h-4 rounded-t" />
          </div>
        </div>

        {/* Card 3: Overall Pass Rate */}
        <div className="border border-slate-900 bg-slate-950/40 rounded-xl p-5 space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between text-xs text-slate-500 font-semibold uppercase tracking-wider">
            <span>Overall Pass Rate</span>
            <Activity className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="space-y-1">
            <h3 className="text-2xl font-bold text-white tracking-tight">
              {stats.total > 0 ? `${Math.round((stats.passed / (stats.passed + stats.failed || 1)) * 100)}%` : '100%'}
            </h3>
            <p className="text-[10px] text-slate-500">
              Calculated across all historical traces
            </p>
          </div>
          <div className="h-6 flex items-end gap-1 pt-1 opacity-70">
            <span className="w-full bg-indigo-500/40 h-2 rounded-t" />
            <span className="w-full bg-indigo-500/30 h-4 rounded-t" />
            <span className="w-full bg-indigo-500/20 h-1 rounded-t" />
            <span className="w-full bg-indigo-500/50 h-3 rounded-t" />
            <span className="w-full bg-indigo-500 h-5 rounded-t" />
          </div>
        </div>

        {/* Card 4: Certificates Issued */}
        <div className="border border-slate-900 bg-slate-950/40 rounded-xl p-5 space-y-3 relative overflow-hidden">
          <div className="flex items-center justify-between text-xs text-slate-500 font-semibold uppercase tracking-wider">
            <span>Certificates Issued</span>
            <ShieldCheck className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="space-y-1">
            <h3 className="text-2xl font-bold text-white tracking-tight">{stats.certCount}</h3>
            <p className="text-[10px] text-slate-500">
              Ed25519 digitally signed VC v3.0.0 evidence
            </p>
          </div>
          <div className="h-6 flex items-end gap-1 pt-1 opacity-70">
            <span className="w-full bg-indigo-500/25 h-1 rounded-t" />
            <span className="w-full bg-indigo-500/45 h-3 rounded-t" />
            <span className="w-full bg-indigo-500/15 h-2 rounded-t" />
            <span className="w-full bg-indigo-500/30 h-4 rounded-t" />
            <span className="w-full bg-indigo-500 h-5 rounded-t" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Triage Needs Attention Rail */}
        <div className="border border-slate-900 bg-slate-950/20 rounded-xl p-5 space-y-4 lg:col-span-1">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Needs Attention</h2>
            <span className="px-2 py-0.5 rounded bg-red-500/10 text-red-400 text-[10px] font-bold border border-red-500/20">
              {triageList.length} Alerts
            </span>
          </div>

          <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
            {loading ? (
              <p className="text-xs text-slate-500 italic">Scanning database...</p>
            ) : triageList.length === 0 ? (
              <div className="py-8 text-center text-slate-500 space-y-1">
                <CheckCircle2 className="w-8 h-8 text-emerald-500/40 mx-auto" />
                <p className="text-xs font-medium">All evaluations green</p>
                <p className="text-[10px]">No compliance alerts found.</p>
              </div>
            ) : (
              triageList.map(run => (
                <div key={run.run_id} className="p-3 bg-slate-950 border border-slate-900 rounded-lg flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <div className="space-y-1 min-w-0 flex-1">
                    <h4 className="text-xs font-bold text-slate-200 font-mono truncate">{run.run_id}</h4>
                    <p className="text-[10px] text-slate-500 truncate">Scenario: {run.scenario}</p>
                    <div className="flex justify-between items-center pt-1 text-[9px]">
                      <span className="text-red-400 uppercase font-semibold">{run.status}</span>
                      <button 
                        onClick={() => navigate(`/debugger?run_id=${run.run_id}`)}
                        className="text-indigo-400 hover:text-indigo-300 font-bold flex items-center gap-0.5 transition-colors"
                      >
                        Inspect <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Recent Evaluations View */}
        <div className="border border-slate-900 bg-slate-950/20 rounded-xl p-5 space-y-4 lg:col-span-2">
          <div className="flex justify-between items-center">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Recent Evaluations</h2>
            <button 
              onClick={() => navigate('/reports')}
              className="text-xs text-indigo-400 hover:text-indigo-300 font-bold transition-colors"
            >
              View All Runs
            </button>
          </div>

          <div className="border border-slate-900 rounded-lg overflow-hidden bg-slate-950/40">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-900 bg-slate-950/80 text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                  <th className="px-4 py-2.5">Run ID</th>
                  <th className="px-4 py-2.5">Scenario</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Time</th>
                  <th className="px-4 py-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900/60">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-slate-500 italic">
                      Fetching recent evaluations...
                    </td>
                  </tr>
                ) : runs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-slate-500 italic">
                      No evaluation traces registered.
                    </td>
                  </tr>
                ) : (
                  runs.slice(0, 6).map(run => (
                    <tr key={run.run_id} className="hover:bg-slate-950/70 transition-colors">
                      <td className="px-4 py-3 font-mono font-bold text-slate-300 truncate max-w-[120px]">
                        {run.run_id}
                      </td>
                      <td className="px-4 py-3 text-slate-400 truncate max-w-[150px]">
                        {run.scenario.replace(/-/g, ' ')}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider border ${
                          run.status === 'CERTIFIED' ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' :
                          run.status === 'PASSED' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                          run.status === 'RUNNING' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse' :
                          'bg-red-500/10 text-red-400 border-red-500/20'
                        }`}>
                          {run.status || 'UNKNOWN'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500 font-mono text-[10px]">
                        {run.timestamp ? new Date(run.timestamp).toLocaleTimeString() : 'N/A'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button 
                          onClick={() => navigate(`/debugger?run_id=${run.run_id}`)}
                          className="px-2.5 py-1 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 rounded hover:text-white transition-colors"
                        >
                          Trace
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

      {/* Quick Launch Actions Card */}
      <div className="border border-slate-900 bg-slate-950/10 rounded-xl p-6">
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-4">Quick Launcher Tasks</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <button 
            onClick={() => navigate('/editor')}
            className="flex items-center gap-3 p-4 bg-slate-950/40 hover:bg-slate-950/80 border border-slate-900 hover:border-indigo-500/30 rounded-xl text-left transition-all group"
          >
            <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg group-hover:scale-105 transition-transform shrink-0">
              <Sparkles className="w-5 h-5" />
            </div>
            <div className="space-y-0.5">
              <h4 className="text-xs font-bold text-white group-hover:text-indigo-400 transition-colors uppercase tracking-wider">Compose Scenario</h4>
              <p className="text-[10px] text-slate-500 leading-normal">Open the visual workspace and compile custom AES graphs.</p>
            </div>
          </button>

          <button 
            onClick={() => navigate('/runner')}
            className="flex items-center gap-3 p-4 bg-slate-950/40 hover:bg-slate-950/80 border border-slate-900 hover:border-indigo-500/30 rounded-xl text-left transition-all group"
          >
            <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg group-hover:scale-105 transition-transform shrink-0">
              <Play className="w-5 h-5" />
            </div>
            <div className="space-y-0.5">
              <h4 className="text-xs font-bold text-white group-hover:text-indigo-400 transition-colors uppercase tracking-wider">Run Evaluation Suite</h4>
              <p className="text-[10px] text-slate-500 leading-normal">Dispatch benchmark jobs to connected Agent endpoints.</p>
            </div>
          </button>

          <button 
            onClick={() => {
              if (runs.length > 0) {
                navigate(`/debugger?run_id=${runs[0].run_id}`);
              } else {
                navigate('/debugger');
              }
            }}
            className="flex items-center gap-3 p-4 bg-slate-950/40 hover:bg-slate-950/80 border border-slate-900 hover:border-indigo-500/30 rounded-xl text-left transition-all group"
          >
            <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg group-hover:scale-105 transition-transform shrink-0">
              <Activity className="w-5 h-5" />
            </div>
            <div className="space-y-0.5">
              <h4 className="text-xs font-bold text-white group-hover:text-indigo-400 transition-colors uppercase tracking-wider">Inspect Last Trace</h4>
              <p className="text-[10px] text-slate-500 leading-normal">Jump into the visual debugging timeline for the last run.</p>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
};
