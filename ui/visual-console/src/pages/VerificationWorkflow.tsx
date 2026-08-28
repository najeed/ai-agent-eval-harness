import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Plug, FileText, ShieldCheck, PlayCircle, Gavel, Bug, PackageCheck,
  CheckCircle2, XCircle, AlertTriangle, ArrowRight, RefreshCw,
  SlidersHorizontal, ChevronDown, ChevronRight,
} from 'lucide-react';
import { useRBAC } from '../context/RBACContext';

/**
 * VerificationWorkflow; the primary product spine (P1-12).
 *
 * Connect → Validate → Select/Compose → Preflight → Run → Diagnose → Evidence
 *
 * Every status shown here is derived from an authoritative runtime object
 * (RuntimeHealth / readiness checks / VerificationResult). The UI never
 * invents verification claims.
 */

interface RuntimeHealth {
  status: string;
  mode: string;
  version: string;
  last_heartbeat: string;
  dependencies: Record<string, string>;
  signing_backend: string;
  details: string[];
}

interface ReadinessCheck {
  name: string;
  status: string;
  tier?: string;
  message?: string;
  latency_ms?: number | null;
}

type StepState = 'pending' | 'active' | 'done' | 'blocked';

const STEPS = [
  { id: 1, label: 'Connect Agent', icon: <Plug className="w-4 h-4" /> },
  { id: 2, label: 'Choose Scenario', icon: <FileText className="w-4 h-4" /> },
  { id: 3, label: 'Preflight', icon: <ShieldCheck className="w-4 h-4" /> },
  { id: 4, label: 'Run', icon: <PlayCircle className="w-4 h-4" /> },
  { id: 5, label: 'Verdict', icon: <Gavel className="w-4 h-4" /> },
  { id: 6, label: 'Diagnose', icon: <Bug className="w-4 h-4" /> },
  { id: 7, label: 'Evidence', icon: <PackageCheck className="w-4 h-4" /> },
] as const;

const tierBadge = (tier?: string) => {
  switch (tier) {
    case 'VERIFIABLE':
      return 'bg-teal-500/15 text-teal-300 border-teal-500/30';
    case 'EXECUTABLE':
      return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
    case 'REACHABLE':
      return 'bg-blue-500/15 text-blue-300 border-blue-500/30';
    case 'CONFIGURED':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
    default:
      return 'bg-slate-500/15 text-slate-400 border-slate-500/30';
  }
};

export const VerificationWorkflow: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { canRunEval } = useRBAC();
  const [protocol, setProtocol] = useState('http_rest');
  const [endpoint, setEndpoint] = useState('');
  const [scenarioId, setScenarioId] = useState('');
  const [preflightResult, setPreflightResult] = useState<{
    ready: boolean;
    checks: ReadinessCheck[];
    fingerprint?: string;
  } | null>(null);
  const [runId, setRunId] = useState('');

  // [G1] Advanced execution settings (folded in from the retired standalone
  // runner page): max turns and evaluation metadata notes.
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxTurns, setMaxTurns] = useState('10');
  const [sessionNotes, setSessionNotes] = useState('Standard regression run');
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [boundScenarioHash, setBoundScenarioHash] = useState('');
  const verdict: string | null = null;

  useEffect(() => {
    const sId = searchParams.get('scenario_id') || searchParams.get('scenarios');
    if (sId) {
      setScenarioId(sId.split(',')[0].trim());
    }
  }, [searchParams]);


  // Authoritative runtime health; never render READY without this.
  const healthQuery = useQuery<RuntimeHealth>({
    queryKey: ['runtime-health'],
    queryFn: async () => {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    retry: 1,
    refetchInterval: 30_000,
  });

  const scenariosQuery = useQuery<{ scenarios?: { id: string; name?: string; path?: string; title?: string; industry?: string }[] }>({
    queryKey: ['scenario-list'],
    queryFn: async () => {
      const res = await fetch('/api/scenarios');
      if (!res.ok) return {};
      return res.json();
    },
    staleTime: 60_000,
  });

  const scenarios: { id: string; name?: string; path?: string; title?: string; industry?: string }[] = useMemo(() => {
    const raw =
      (scenariosQuery.data as any)?.scenarios ??
      (scenariosQuery.data as any)?.data ??
      [];
    return Array.isArray(raw) ? raw : [];
  }, [scenariosQuery.data]);

  const healthStatus = healthQuery.isError
    ? 'UNREACHABLE'
    : ((healthQuery.data as any)?.status ?? 'UNREACHABLE');

  const stepStates: Record<number, StepState> = {
    1: endpoint.trim() ? 'done' : 'active',
    2: scenarioId.trim() ? 'done' : endpoint.trim() ? 'active' : 'pending',
    3: preflightResult ? (preflightResult.ready ? 'done' : 'blocked') : scenarioId ? 'active' : 'pending',
    4: runId ? 'done' : preflightResult?.ready ? 'active' : 'blocked',
    5: verdict ? 'done' : runId ? 'active' : 'blocked',
    6: verdict === 'NOT_VERIFIED' || verdict === 'POLICY_BREACH' ? 'active' : runId && verdict ? 'done' : 'blocked',
    7: runId && verdict ? 'active' : 'blocked',
  };

  // [Chain binding] Deep-link preselection: /?scenario_id=<id> pre-fills the
  // scenario so first-value flows can land directly in the spine.
  useEffect(() => {
    const sid = searchParams.get('scenario_id');
    if (sid) setScenarioId(sid);
  }, [searchParams]);

  const runPreflight = async () => {
    setPreflightResult(null);
    try {
      const res = await fetch('/api/scenarios/readiness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: scenarioId || undefined,
          agent_config: { protocol, endpoint },
          runtime_config: { max_turns: parseInt(maxTurns) || 10 },
        }),
      });
      const data = await res.json();
      setPreflightResult({
        ready: !!data.ready,
        checks: data.checks ?? [],
        fingerprint: data.preflight_fingerprint,
      });
    } catch {
      setPreflightResult({ ready: false, checks: [] });
    }
  };

  // Reset preflight when any execution parameter changes; a stale pass
  const onParamChange = (setter: (val: string) => void) => (val: string) => {
    setter(val);
    setPreflightResult(null);
  };

  const [availableProtocols, setAvailableProtocols] = useState<string[]>([

    'http',
    'http_rest',
    'sse',
    'socket',
    'ollama',
    'openai',
    'anthropic',
    'gemini',
  ]);

  useEffect(() => {
    // Dynamic protocol discovery from Runtime health
    fetch('/api/v1/doctor')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data && Array.isArray(data.available_protocols) && data.available_protocols.length > 0) {
          setAvailableProtocols(data.available_protocols);
        }
      })
      .catch(() => {});
  }, []);

  const launchEvaluation = async () => {
    if (!scenarioId || !endpoint.trim()) {
      setLaunchError('Please specify a valid Scenario ID and Agent Endpoint.');
      return;
    }
    if (!preflightResult || !preflightResult.ready) {
      setLaunchError('Cannot launch: a passing preflight check is required.');
      return;
    }
    setLaunching(true);
    setLaunchError('');
    const found = scenarios.find(s => s.id === scenarioId);
    const scenPath = found?.path || `scenarios/${scenarioId}.json`;
    try {
      const res = await fetch('/api/v1/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: scenPath,
          max_turns: parseInt(maxTurns) || 10,
          protocol,
          endpoint,
          agent_config: { protocol, endpoint },
          runtime_config: { max_turns: parseInt(maxTurns) || 10 },
          metadata: {
            notes: sessionNotes || undefined,
            preflight_fingerprint: preflightResult.fingerprint,
          },
        }),
      });
      const data = await res.json();
      if (res.ok && data.run_id) {
        if (data.scenario_hash) setBoundScenarioHash(data.scenario_hash);
        navigate(`/debugger?run_id=${data.run_id}`);
      } else {
        setLaunchError(data.error || 'Failed to initialize evaluation.');
      }
    } catch (err: any) {
      setLaunchError(`Evaluation failure: ${err.message}`);
    } finally {
      setLaunching(false);
    }
  };


  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">New Verification</h1>
        <p className="text-xs text-slate-400 mt-1">
          Connect → Validate → Select → Preflight → Run → Diagnose → Evidence. Steps unlock in
          order; nothing here claims verification the runtime has not produced.
        </p>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {STEPS.map((s, i) => (
          <React.Fragment key={s.id}>
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px] font-semibold shrink-0 ${stepStates[s.id] === 'done'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : stepStates[s.id] === 'active'
                    ? 'border-indigo-500/40 bg-indigo-500/10 text-indigo-300'
                    : stepStates[Number(s.id)] === 'blocked'
                      ? 'border-slate-800 bg-slate-900/40 text-slate-600'
                      : 'border-slate-700 bg-slate-900/40 text-slate-400'
                }`}
            >
              {stepStates[s.id] === 'done' ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : stepStates[s.id] === 'blocked' ? (
                <XCircle className="w-3.5 h-3.5" />
              ) : (
                s.icon
              )}
              {s.label}
            </div>
            {i < STEPS.length - 1 && <ArrowRight className="w-3 h-3 text-slate-700 shrink-0" />}
          </React.Fragment>
        ))}
      </div>

      {/* Runtime health strip */}
      <div
        className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-mono ${healthStatus === 'HEALTHY'
            ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-300'
            : healthStatus === 'DEGRADED'
              ? 'border-amber-500/20 bg-amber-500/5 text-amber-300'
              : 'border-red-500/20 bg-red-500/5 text-red-300'
          }`}
      >
        {healthStatus === 'HEALTHY' ? (
          <CheckCircle2 className="w-3.5 h-3.5" />
        ) : (
          <AlertTriangle className="w-3.5 h-3.5" />
        )}
        Runtime: {healthStatus}
        {(healthQuery.data as any)?.signing_backend === 'ephemeral' && (
          <span className="ml-auto text-[10px] text-amber-400">
            ephemeral signer; runs will be Executable/Verifiable, not Cryptographically Attested
          </span>
        )}
      </div>

      {/* Step 1: Connect Agent */}
      <section className="bg-slate-950/50 border border-slate-900 rounded-xl p-5 space-y-3">
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <Plug className="w-4 h-4 text-indigo-400" /> 1 · Connect Agent
        </h2>
        <div className="grid grid-cols-[180px_1fr] gap-3 items-center">
          <label className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">
            Protocol
            <select
              value={protocol}
              onChange={e => onParamChange(setProtocol)(e.target.value)}
              className="mt-1 w-full bg-slate-900 border border-slate-800 rounded px-2 py-1.5 text-xs text-slate-200"
            >
              {availableProtocols.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>

          <label className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">
            Endpoint
            <input
              value={endpoint}
              onChange={e => onParamChange(setEndpoint)(e.target.value)}
              placeholder="https://your-agent.example.com (no implicit default)"
              className="mt-1 w-full bg-slate-900 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 font-mono"
            />
          </label>
        </div>
        {!endpoint.trim() && (
          <p className="text-[11px] text-slate-500">
            An explicit target is required for non-demo use. There is no implicit localhost target.
          </p>
        )}
      </section>

      {/* Step 2: Choose Scenario */}
      <section className="bg-slate-950/50 border border-slate-900 rounded-xl p-5 space-y-3">
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <FileText className="w-4 h-4 text-indigo-400" /> 2 · Choose Scenario
        </h2>
        <select
          value={scenarioId}
          onChange={e => onParamChange(setScenarioId)(e.target.value)}
          className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-xs text-slate-200 font-mono"
        >
          <option value="">— select a scenario;</option>
          {scenarios.map(s => (
            <option key={s.id} value={s.id}>
              {s.name || s.id}
            </option>
          ))}
        </select>
        <div className="flex items-center justify-between">
          <Link to="/editor" className="text-[11px] text-indigo-400 hover:text-indigo-300">
            or compose a new scenario →
          </Link>
          {scenarioId && (
            <span className="text-[10px] font-mono text-slate-500">selected: {scenarioId}</span>
          )}
        </div>
      </section>

      {/* Step 3: Preflight */}
      <section className="bg-slate-950/50 border border-slate-900 rounded-xl p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-indigo-400" /> 3 · Preflight
          </h2>
          <button
            onClick={runPreflight}
            disabled={!scenarioId || !endpoint.trim()}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-semibold transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Run preflight
          </button>
        </div>
        {preflightResult && (
          <ul className="space-y-1.5">
            {preflightResult.checks.map(c => (
              <li
                key={c.name}
                className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-900/60 border border-slate-800 text-xs"
              >
                {c.status === 'PASSED' ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : c.status === 'FAILED' ? (
                  <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                ) : (
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                )}
                <span className="text-slate-300 font-semibold w-44 truncate">{c.name}</span>
                {c.tier && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${tierBadge(c.tier)}`}>
                    {c.tier}
                  </span>
                )}
                <span className="text-slate-500 truncate">{c.message}</span>
                {typeof c.latency_ms === 'number' && (
                  <span className="ml-auto text-[10px] font-mono text-slate-600">{c.latency_ms}ms</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Steps 4–7: launch + post-run */}
      <section className="bg-slate-950/50 border border-slate-900 rounded-xl p-5 space-y-4">
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <PlayCircle className="w-4 h-4 text-indigo-400" /> 4–7 · Run, Verdict, Diagnose, Evidence
        </h2>
        {!preflightResult?.ready ? (
          <p className="text-xs text-slate-500">
            Locked until all preflight checks pass. A run that cannot produce verification evidence
            is never equivalent to a verified run.
          </p>
        ) : (
          <>
            {/* [G1] Advanced execution settings drawer; folded in from the
                retired standalone runner page. */}
            <div className="border border-slate-800 rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setShowAdvanced(v => !v)}
                className="w-full flex items-center gap-2 px-3 py-2 bg-slate-900/60 hover:bg-slate-900 text-slate-300 text-xs font-semibold transition-colors"
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-indigo-400" />
                Advanced execution settings
                {showAdvanced ? (
                  <ChevronDown className="w-3.5 h-3.5 ml-auto text-slate-500" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 ml-auto text-slate-500" />
                )}
              </button>
              {showAdvanced && (
                <div className="p-3 space-y-3 bg-slate-950/40">
                  <label className="block text-[11px] uppercase tracking-wider text-slate-500 font-bold">
                    Max Execution Turns
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={maxTurns}
                      onChange={e => onParamChange(setMaxTurns)(e.target.value)}
                      className="mt-1 w-full bg-slate-900 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </label>
                  <label className="block text-[11px] uppercase tracking-wider text-slate-500 font-bold">
                    Evaluation Metadata Notes
                    <input
                      type="text"
                      value={sessionNotes}
                      onChange={e => setSessionNotes(e.target.value)}
                      className="mt-1 w-full bg-slate-900 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </label>
                  <p className="text-[10px] text-slate-500">
                    Changing these values invalidates the current preflight result; re-run preflight
                    before launching.
                  </p>
                </div>
              )}
            </div>

            {launchError && (
              <div className="p-3 bg-red-500/5 border border-red-500/20 text-red-400 rounded-lg text-xs flex gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{launchError}</span>
              </div>
            )}

            {!canRunEval && (
              <p className="text-[10px] text-amber-500 font-semibold italic">
                View-only access: MultiAgentOps Eng or Scenario Designer privileges are required to
                trigger evaluation runs.
              </p>
            )}

            <button
              onClick={launchEvaluation}
              disabled={launching || !canRunEval || !preflightResult?.ready}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-bold transition-colors"
            >
              <PlayCircle className="w-4 h-4" />
              {launching ? 'Initializing job…' : 'Launch evaluation'}
            </button>
            {!preflightResult?.ready && (
              <p className="text-[10px] text-amber-400 font-medium">
                Preflight validation required: complete and pass preflight check before launch.
              </p>
            )}
            {boundScenarioHash && (
              <p className="text-[10px] font-mono text-slate-500">
                bound revision:{' '}
                <span className="text-slate-400">{boundScenarioHash.slice(0, 19)}…</span>
              </p>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
              <input
                value={runId}
                onChange={e => setRunId(e.target.value)}
                placeholder="completed run_id"
                className="bg-slate-900 border border-slate-800 rounded px-3 py-2 text-xs text-slate-200 font-mono"
              />
              <Link
                to={`/reports?run_id=${encodeURIComponent(runId)}`}
                className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-xs font-semibold ${runId
                    ? 'border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/10'
                    : 'border-slate-800 text-slate-600 pointer-events-none'
                  }`}
              >
                <Gavel className="w-3.5 h-3.5" /> Verdict & report
              </Link>
              <Link
                to={`/debugger?run_id=${encodeURIComponent(runId)}`}
                className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-xs font-semibold ${runId
                    ? 'border-indigo-500/30 text-indigo-300 hover:bg-indigo-500/10'
                    : 'border-slate-800 text-slate-600 pointer-events-none'
                  }`}
              >
                <Bug className="w-3.5 h-3.5" /> Diagnose in debugger
              </Link>
            </div>
          </>
        )}
      </section>
    </div>
  );
};

export default VerificationWorkflow;


