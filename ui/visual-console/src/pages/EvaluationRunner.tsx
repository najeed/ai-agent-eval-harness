import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { 
  Play, ShieldCheck, Server, 
  AlertTriangle, RefreshCw 
} from 'lucide-react';
import { useRBAC } from '../context/RBACContext';

interface ScenarioItem {
  id: string;
  title: string;
  industry: string;
  path: string;
}

export const EvaluationRunner: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { canRunEval } = useRBAC();
  const scenariosQuery = searchParams.get('scenarios');

  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<string>('');
  
  // Config state
  const [protocol, setProtocol] = useState('HTTP');
  const [maxTurns, setMaxTurns] = useState('10');
  const [agentUrl, setAgentUrl] = useState('http://localhost:8000/api/agent');
  const [sessionNotes, setSessionNotes] = useState('Standard regression run');

  // Preflight health state
  const [preflightStatus, setPreflightStatus] = useState<'idle' | 'checking' | 'passed' | 'failed'>('idle');
  const [readinessData, setReadinessData] = useState<any>(null);
  
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const fetchData = async () => {
    try {
      const res = await fetch('/api/scenarios');
      const data = await res.json();
      const list = data.scenarios || [];
      setScenarios(list);
      
      // Auto-select first scenario or scenariosQuery if passed
      if (scenariosQuery) {
        setSelectedScenario(scenariosQuery.split(',')[0]);
      } else if (list.length > 0) {
        setSelectedScenario(list[0].id);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const triggerPreflight = async () => {
    setPreflightStatus('checking');
    try {
      const res = await fetch('/api/scenarios/readiness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedScenario,
          agent_config: {
            agent_name: 'runner_agent',
            protocol: protocol.toLowerCase(),
            endpoint: agentUrl,
          },
          runtime_config: {
            max_turns: parseInt(maxTurns) || 10,
          },
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setReadinessData(data);
        if (data.ready) {
          setPreflightStatus('passed');
        } else {
          setPreflightStatus('failed');
        }
      } else {
        setPreflightStatus('failed');
      }
    } catch (e) {
      setPreflightStatus('failed');
    }
  };

  const handleLaunch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedScenario) return;

    setSubmitting(true);
    setErrorMsg('');

    // Locate full path of scenario from list
    const found = scenarios.find(s => s.id === selectedScenario);
    const scenPath = found ? found.path : `scenarios/${selectedScenario}.json`;

    try {
      // POST evaluate scenario with explicit agent_config and runtime_config
      const res = await fetch('/api/v1/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: scenPath,
          max_turns: parseInt(maxTurns) || 10,
          protocol: protocol.toLowerCase(),
          endpoint: agentUrl,
          agent_config: {
            agent_name: 'runner_agent',
            protocol: protocol.toLowerCase(),
            endpoint: agentUrl,
            model: 'gpt-4o',
          },
          runtime_config: {
            max_turns: parseInt(maxTurns) || 10,
          },
          metadata: {
            protocol: protocol.toLowerCase(),
            agent_url: agentUrl,
            endpoint: agentUrl,
            notes: sessionNotes,
            agent_platform: 'AgentV-v2.0',
          },
        }),
      });

      const data = await res.json();

      if (res.ok && data.run_id) {
        // Successfully launched. Navigate directly into live debugger!
        navigate(`/debugger?run_id=${data.run_id}`);
      } else {
        setErrorMsg(data.error || 'Failed to initialize evaluation.');
      }
    } catch (err: any) {
      setErrorMsg(`Evaluation failure: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };


  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Evaluation Runner Control</h1>
        <p className="text-slate-400 text-sm">Configure environment protocols and dispatch agent evaluation jobs.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Left Form: Configuration */}
        <form onSubmit={handleLaunch} className="space-y-4 lg:col-span-2 border border-slate-900 bg-slate-950/20 rounded-xl p-6">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Launch Configuration</h2>
          
          {loading ? (
            <p className="text-xs text-slate-500 italic">Reading scenarios...</p>
          ) : (
            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Target Scenario:</label>
              <select
                value={selectedScenario}
                onChange={(e) => setSelectedScenario(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
              >
                {scenarios.map(s => (
                  <option key={s.id} value={s.id}>
                    [{s.industry.toUpperCase()}] {s.title} ({s.id})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Execution Protocol:</label>
              <select
                value={protocol}
                onChange={(e) => setProtocol(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
              >
                <option value="HTTP">HTTP Server</option>
                <option value="LOCAL">Local Executable</option>
                <option value="SOCKET">TCP Socket</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Max Execution Turns:</label>
              <input
                type="number"
                min="1"
                max="100"
                value={maxTurns}
                onChange={(e) => setMaxTurns(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Target AGENT_API_URL:</label>
              <input
                type="text"
                required
                value={agentUrl}
                onChange={(e) => setAgentUrl(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Evaluation Metadata Tags:</label>
            <input
              type="text"
              value={sessionNotes}
              onChange={(e) => setSessionNotes(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>

          {errorMsg && (
            <div className="p-3 bg-red-500/5 border border-red-500/20 text-red-400 rounded-lg text-xs flex gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          <div className="pt-2">
            <button
              type="submit"
              disabled={submitting || preflightStatus !== 'passed' || !canRunEval}
              className={`w-full py-2.5 rounded-lg text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2 transition-all ${
                preflightStatus === 'passed' && canRunEval
                  ? 'bg-indigo-600 hover:bg-indigo-500 text-white cursor-pointer'
                  : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-850'
              }`}
            >
              <Play className="w-4 h-4" />
              <span>{submitting ? 'Initializing Job...' : 'Execute Evaluation Suite'}</span>
            </button>
            {!canRunEval ? (
              <p className="text-[10px] text-amber-500 font-semibold text-center mt-2 italic">
                * View-Only Access: Scenario Designer or MultiAgentOps Eng privileges required to trigger evaluation runs.
              </p>
            ) : preflightStatus !== 'passed' && (
              <p className="text-[10px] text-slate-500 text-center mt-2 italic">
                * Complete the preflight health audit in the right panel to unlock execution.
              </p>
            )}
          </div>
        </form>

        {/* Right Panel: Preflight Audit */}
        <div className="border border-slate-900 bg-slate-950/20 rounded-xl p-6 space-y-4">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Execution Readiness Preflight</h2>
          
          <p className="text-slate-500 text-[11px] leading-relaxed">
            Validates scenario specification, agent protocol endpoint, required tools, simulator bindings, and cryptographic signing before dispatching.
          </p>

          <div className="space-y-3 pt-2">
            {preflightStatus === 'idle' && (
              <button
                onClick={triggerPreflight}
                className="w-full py-2 bg-slate-850 hover:bg-slate-800 border border-slate-800 rounded-lg text-slate-300 font-semibold text-xs transition-colors flex items-center justify-center gap-1.5"
              >
                <Server className="w-4 h-4 text-indigo-400" />
                <span>Verify Execution Readiness</span>
              </button>
            )}

            {preflightStatus === 'checking' && (
              <div className="flex justify-center items-center py-4 gap-2 text-xs text-slate-400">
                <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />
                <span>Validating execution readiness probes...</span>
              </div>
            )}

            {preflightStatus === 'passed' && readinessData && (
              <div className="space-y-3">
                <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-lg flex items-start gap-2.5">
                  <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider">Ready to Evaluate</h4>
                    <p className="text-slate-400 text-[10px] leading-relaxed">All execution readiness gates passed.</p>
                  </div>
                </div>
                
                <div className="space-y-1.5 text-xs">
                  {(readinessData.checks || []).map((chk: any, idx: number) => (
                    <div key={idx} className="flex justify-between border-b border-slate-900/60 pb-1.5">
                      <span className="text-slate-400 font-medium">{chk.name}</span>
                      <span className={`font-mono text-[10px] font-bold ${
                        chk.status === 'PASSED' ? 'text-emerald-400' : 'text-amber-400'
                      }`}>
                        {chk.status}
                      </span>
                    </div>
                  ))}
                </div>

                <button
                  onClick={triggerPreflight}
                  className="w-full py-1.5 bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-300 rounded text-xs transition-colors"
                >
                  Re-Validate Readiness
                </button>
              </div>
            )}

            {preflightStatus === 'failed' && (
              <div className="space-y-3">
                <div className="p-3 bg-red-500/5 border border-red-500/20 rounded-lg flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <h4 className="text-xs font-bold text-red-400 uppercase tracking-wider">Readiness Check Failed</h4>
                    <p className="text-slate-400 text-[10px] leading-relaxed">
                      {readinessData?.checks?.find((c: any) => c.status === 'FAILED')?.message || 'One or more execution readiness probes failed.'}
                    </p>
                  </div>
                </div>
                <button
                  onClick={triggerPreflight}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-xs font-bold transition-colors"
                >
                  Retry Readiness Probes
                </button>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
