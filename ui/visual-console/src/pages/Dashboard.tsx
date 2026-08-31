import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldCheck,
  Play,
  Sparkles,
  ArrowRight,
  CheckCircle2,
  Layers,
  FileText,
  Download,
  PlusCircle,
  Eye,
  Activity,
} from 'lucide-react';

import { AgentTargetSelector, DEFAULT_PROFILES, type AgentTargetProfile } from '../components/AgentTargetSelector';
import { ResolvedManifestModal } from '../components/ResolvedManifestModal';
import { ProvisionalBadge } from '../components/ProvisionalBadge';
import { useRBAC } from '../context/RBACContext';

interface RunItem {
  run_id: string;
  scenario: string;
  timestamp: string;
  status: string;
  verdict?: string;
  provisional?: boolean;
  execution_mode?: string | null;
  has_certificate?: boolean;
  agent?: string;
  duration?: number;
  resultStatus?: 'PASS' | 'FAIL';
}

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { tenantId, workspaceId } = useRBAC();

  const [runs, setRuns] = useState<RunItem[]>([]);
  const [scenarios, setScenarios] = useState<any[]>([]);

  // Verification Workflow Wizard State
  const [showWizard, setShowWizard] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState<AgentTargetProfile>(DEFAULT_PROFILES[0]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('');
  const [showManifestModal, setShowManifestModal] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);

  const fetchData = async () => {
    try {
      // Fetch runs list
      const runsRes = await fetch('/api/runs');
      const runsData = await runsRes.json();
      const loadedRuns: any[] = runsData.runs || [];

      // Fetch scenarios
      const scenRes = await fetch('/api/scenarios');
      const scenData = await scenRes.json();
      const loadedScens = scenData.scenarios || [];
      setScenarios(loadedScens);
      if (loadedScens.length > 0 && !selectedScenarioId) {
        setSelectedScenarioId(loadedScens[0].id || loadedScens[0].metadata?.id);
      }

      setRuns(
        loadedRuns.slice(0, 10).map((r) => {
          const isProv = r.provisional || r.verification_status === 'VERIFIED_PROVISIONAL';
          return {
            run_id: r.run_id,
            scenario: r.scenario || r.run_id,
            agent: r.identifier || undefined,
            duration: r.duration_seconds ?? undefined,
            resultStatus: r.result_status || undefined,
            timestamp: r.timestamp || 'N/A',
            status: r.execution_status || r.status || 'UNKNOWN',
            // Server verdict is authoritative; no client-side inference.
            verdict:
              r.verification_status === 'VERIFIED' || r.verification_status === 'VERIFIED_PROVISIONAL' || r.verification_status === 'FAILED_VERIFICATION'
                ? r.verification_status
                : 'UNKNOWN',
            provisional: isProv,
            execution_mode: r.execution_mode || null,
            has_certificate: !!r.has_certificate,
          };
        })
      );
    } catch (e) {
      console.error('Error fetching dashboard metrics:', e);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleLaunchVerification = async () => {
    setIsLaunching(true);
    try {
      // 1. Mandatory Preflight Readiness Gate (P0 #4)
      const preflightRes = await fetch('/api/scenarios/readiness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedScenarioId,
          agent_config: {
            protocol: selectedProfile.provider,
            endpoint: selectedProfile.endpoint,
            model: selectedProfile.model,
          },
          runtime_config: { max_turns: 10 },
        }),
      });
      const preflightData = await preflightRes.json();
      const preflightFingerprint = preflightData?.preflight_fingerprint;

      // 2. Governed Launch with preflight_fingerprint
      const res = await fetch('/api/v1/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: selectedScenarioId,
          agent: selectedProfile.endpoint,
          model: selectedProfile.model,
          protocol: selectedProfile.provider,
          tenant_id: tenantId,
          workspace_id: workspaceId,
          seed: 42,
          preflight_fingerprint: preflightFingerprint,
          metadata: {
            preflight_fingerprint: preflightFingerprint,
          },
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setShowManifestModal(false);
        navigate(`/debugger?run_id=${data.run_id || 'latest'}`);
      } else {
        alert(`Evaluation launch failed: ${data.error || 'Unknown error'}`);
      }
    } catch (err: any) {
      alert(`Error dispatching evaluation: ${err.message}`);
    } finally {
      setIsLaunching(false);
    }
  };

  const selectedScenarioObj =
    scenarios.find(
      (s) => s.id === selectedScenarioId || s.metadata?.id === selectedScenarioId
    ) || { id: selectedScenarioId || 'demo_scenario', title: 'Target Scenario' };

  return (
    <div className="p-8 space-y-8 max-w-7xl mx-auto">
      {/* Primary Workflow Hero CTA */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 via-indigo-950/40 to-slate-950 border border-slate-800 p-8 shadow-2xl">
        <div className="relative z-10 max-w-3xl space-y-4">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" />
            Enterprise Verification OS • NIST 2026 Audit Ready
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight leading-tight">
            Verify AI Agent Workflows with Cryptographic Proofs
          </h1>
          <p className="text-slate-400 text-sm leading-relaxed">
            Execute deterministic assurance contracts against any model or runtime. Produce immutable,
            evidence-linked Verification Packages and mathematical state transition verdicts.
          </p>

          <div className="flex flex-wrap items-center gap-4 pt-2">
            <button
              onClick={() => setShowWizard(true)}
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-bold text-sm shadow-xl shadow-indigo-500/25 flex items-center gap-2.5 transition transform active:scale-95"
            >
              <Play className="w-4 h-4 fill-current" />
              New Verification
            </button>

            <button
              onClick={() => navigate('/scenarios/compose')}
              className="px-5 py-3 rounded-xl bg-slate-900/80 hover:bg-slate-800 text-slate-300 hover:text-white font-semibold text-sm border border-slate-750 flex items-center gap-2 transition"
            >
              <PlusCircle className="w-4 h-4 text-slate-400" />
              Compose Assurance Contract
            </button>
          </div>
        </div>

        {/* Decorative Background Glow */}
        <div className="absolute right-0 top-0 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
      </div>

      {/* 6-Stage New Verification Workflow Wizard */}
      {showWizard && (
        <div className="p-6 rounded-2xl bg-slate-900 border border-indigo-500/30 shadow-2xl space-y-6 animate-fade-in">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="space-y-1">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-indigo-400" />
                New Verification Workflow
              </h2>
              <p className="text-xs text-slate-400">
                1. Select Target → 2. Select Scenario → 3. Review Resolved Config → 4. Execute → 5. Verify → 6. Export Evidence
              </p>
            </div>
            <button
              onClick={() => setShowWizard(false)}
              className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 font-medium"
            >
              Cancel
            </button>
          </div>

          <div className="space-y-6">
            {/* Step 1: Agent Target */}
            <div>
              <span className="text-[11px] font-mono text-indigo-400 uppercase tracking-wider font-bold block mb-2">
                Step 1 • Target Connection Profile
              </span>
              <AgentTargetSelector
                selectedProfile={selectedProfile}
                onChange={setSelectedProfile}
              />
            </div>

            {/* Step 2: Scenario Selection */}
            <div>
              <span className="text-[11px] font-mono text-indigo-400 uppercase tracking-wider font-bold block mb-2">
                Step 2 • Scenario / Assurance Suite Target
              </span>
              <div className="bg-slate-950/60 p-4 rounded-xl border border-slate-800 space-y-3">
                <label className="text-xs font-semibold text-slate-300 block">
                  Select Scenario from Catalog:
                </label>
                <select
                  value={selectedScenarioId}
                  onChange={(e) => setSelectedScenarioId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-750 text-white rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500 font-mono"
                >
                  {scenarios.map((s) => {
                    const sid = s.id || s.metadata?.id || 'scen';
                    const stitle = s.title || s.metadata?.name || sid;
                    return (
                      <option key={sid} value={sid}>
                        {stitle} ({sid})
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>

            {/* Step 3 & Launch CTA */}
            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-slate-400">
                Preflight checks will validate target connectivity and scenario integrity.
              </span>

              <button
                onClick={() => setShowManifestModal(true)}
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 flex items-center gap-2 transition"
              >
                <ShieldCheck className="w-4 h-4" />
                Review Resolved Config & Execute
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Preflight Manifest Review Modal */}
      <ResolvedManifestModal
        isOpen={showManifestModal}
        onClose={() => setShowManifestModal(false)}
        onConfirmLaunch={handleLaunchVerification}
        scenario={{
          id: selectedScenarioObj.id || selectedScenarioId,
          title: selectedScenarioObj.title || selectedScenarioObj.metadata?.name,
          version: selectedScenarioObj.version || selectedScenarioObj.metadata?.version,
          hash: selectedScenarioObj.metadata?.provisioning_hash,
        }}
        targetProfile={selectedProfile}
        tenantId={tenantId}
        workspaceId={workspaceId}
        seed={selectedScenarioObj.metadata?.seed ?? null}
        runtimeBoundary={
          selectedScenarioObj.metadata?.execution_mode
            ? `Declared: ${selectedScenarioObj.metadata.execution_mode}`
            : 'Standard Sandbox'
        }
        evaluators={
          Array.from(
            new Set([
              ...(selectedScenarioObj.evaluation?.metrics?.map((m: any) => m.metric || m) || []),
              ...(selectedScenarioObj.workflow?.nodes?.flatMap(
                (n: any) => n.success_criteria?.map((sc: any) => sc.metric) || []
              ) || []),
            ])
          ).filter(Boolean) as string[]
        }
        signingBackend={null}
        isLaunching={isLaunching}
      />


      {/* [Zero-state] Fastest path to first verified value */}
      {runs.length === 0 && (
        <div
          onClick={() => navigate('/spec-import')}
          className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-teal-950/60 via-slate-900 to-slate-900 border border-teal-500/30 p-6 flex flex-col sm:flex-row sm:items-center gap-4 cursor-pointer group hover:border-teal-400/50 transition"
        >
          <div className="w-11 h-11 rounded-xl bg-teal-500/15 border border-teal-500/30 flex items-center justify-center text-teal-300 group-hover:scale-110 transition shrink-0">
            <Sparkles className="w-5 h-5" />
          </div>
          <div className="flex-1 space-y-1">
            <h3 className="text-sm font-bold text-white">Get your first verified run in minutes</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Paste a requirement spec — the importer scaffolds a runnable scenario, then the
              verification workflow walks you through Connect → Preflight → Run → Evidence.
            </p>
          </div>
          <span className="text-xs font-semibold text-teal-300 flex items-center gap-1 shrink-0">
            Start with a spec <ArrowRight className="w-3.5 h-3.5" />
          </span>
        </div>
      )}
      {/* 3 Core Pillars Quick Navigation */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div
          onClick={() => navigate('/scenarios')}
          className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-indigo-500/50 hover:bg-slate-900 transition cursor-pointer group space-y-3"
        >
          <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 group-hover:scale-110 transition">
            <Layers className="w-5 h-5" />
          </div>
          <h3 className="text-base font-bold text-white group-hover:text-indigo-400 transition">
            Scenarios & Suites
          </h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Browse scenario catalog, author full assurance contracts visually, and inspect readiness probes.
          </p>
          <span className="text-xs font-semibold text-indigo-400 flex items-center gap-1">
            Open Scenarios <ArrowRight className="w-3.5 h-3.5" />
          </span>
        </div>

        <div
          onClick={() => navigate('/reports')}
          className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-indigo-500/50 hover:bg-slate-900 transition cursor-pointer group space-y-3"
        >
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 group-hover:scale-110 transition">
            <Activity className="w-5 h-5" />
          </div>
          <h3 className="text-base font-bold text-white group-hover:text-emerald-400 transition">
            Runs & Verification
          </h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Live telemetry, 7-tab canonical run inspection, multi-run comparison, and root-cause analysis.
          </p>
          <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
            Inspect Runs <ArrowRight className="w-3.5 h-3.5" />
          </span>
        </div>

        <div
          onClick={() => navigate('/reports')}
          className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-indigo-500/50 hover:bg-slate-900 transition cursor-pointer group space-y-3"
        >
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 group-hover:scale-110 transition">
            <FileText className="w-5 h-5" />
          </div>
          <h3 className="text-base font-bold text-white group-hover:text-amber-400 transition">
            Evidence Packages
          </h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            Single-file immutable Verification Packages (.agentv-package.json) and post-quantum certificates.
          </p>
          <span className="text-xs font-semibold text-amber-400 flex items-center gap-1">
            Audit Evidence <ArrowRight className="w-3.5 h-3.5" />
          </span>
        </div>
      </div>

      {/* Recent Verification Records Table */}
      <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-white">Recent Verification Records</h3>
            <p className="text-xs text-slate-400">
              Immutable audit history of executed scenarios and cryptographic verification packages.
            </p>
          </div>
          <button
            onClick={() => navigate('/reports')}
            className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold flex items-center gap-1"
          >
            View All Runs <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300 font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider">
                <th className="pb-3 font-semibold">Run ID</th>
                <th className="pb-3 font-semibold">Scenario Target</th>
                <th className="pb-3 font-semibold">Status / Verdict</th>
                <th className="pb-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {runs.map((r) => {
                const isProv = r.provisional || r.verdict === 'VERIFIED_PROVISIONAL';
                const isVer = r.verdict === 'VERIFIED' || isProv;
                const isFailed = r.verdict === 'FAILED_VERIFICATION';

                return (
                  <tr key={r.run_id} className="hover:bg-slate-850/50 transition">
                    <td className="py-3 font-sans font-semibold text-white max-w-[220px]">
                      <div className="flex items-center gap-2 truncate" title={r.scenario}>
                        <span className="truncate">{r.scenario}</span>
                        <ProvisionalBadge
                          provisional={isProv}
                          executionMode={r.execution_mode}
                          size="sm"
                        />
                      </div>
                      <button
                        onClick={() => navigator.clipboard?.writeText(r.run_id)}
                        title="Copy run ID"
                        className="mt-1 px-1 py-0.5 rounded bg-slate-800 border border-slate-700 text-[8px] font-mono text-slate-400 hover:text-indigo-300 align-middle"
                      >
                        {r.run_id.length > 14 ? r.run_id.slice(0, 14) + '…' : r.run_id} ⧉
                      </button>
                    </td>
                    <td className="py-3 font-sans text-slate-400">{r.agent || '—'}</td>
                    <td className="py-3">
                      <span
                        title={
                          isProv
                            ? 'Certificate is valid, but the run was marked provisional.'
                            : isVer
                              ? 'Certificate trace-hash matches the current trace (server-verified).'
                              : isFailed
                                ? 'Certificate trace-hash does NOT match the current trace.'
                                : 'No authoritative verification available for this run.'
                        }
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 w-fit ${isProv
                          ? 'bg-amber-500/10 border border-amber-500/30 text-amber-300'
                          : isVer
                            ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                            : isFailed
                              ? 'bg-red-500/10 border border-red-500/20 text-red-400'
                              : 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-400'
                          }`}
                      >
                        {isVer ? <ShieldCheck className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                        {isProv ? 'VERIFIED (PROVISIONAL)' : r.verdict === 'UNKNOWN' ? r.status : r.verdict}
                      </span>
                    </td>
                  <td className="py-3 text-right">
                    <div className="flex items-center justify-end gap-2 font-sans">
                      <button
                        onClick={() => navigate(`/reports?run_id=${r.run_id}`)}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-medium transition flex items-center gap-1"
                      >
                        <Eye className="w-3 h-3" /> View result
                      </button>
                      <button
                        onClick={() => navigate(`/debugger?run_id=${r.run_id}`)}
                        title="Open this run in the Live Debugger for root-cause inspection."
                        className={`px-2.5 py-1 rounded text-[11px] font-semibold transition flex items-center gap-1 border ${r.verdict === 'FAILED_VERIFICATION' || r.resultStatus === 'FAIL'
                            ? 'bg-red-500/10 hover:bg-red-500/20 border-red-500/30 text-red-300'
                            : 'bg-slate-800 hover:bg-slate-700 border-transparent text-slate-200'
                          }`}
                      >
                        <Activity className={`w-3 h-3 ${r.verdict === 'FAILED_VERIFICATION' || r.resultStatus === 'FAIL' ? 'text-red-400' : ''}`} />
                        Inspect failure
                      </button>
                      <a
                        href={`/api/v1/evidence/packages/${r.run_id}?download=true`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1 rounded bg-indigo-950/60 hover:bg-indigo-900 border border-indigo-500/30 text-indigo-300 text-[11px] font-semibold transition flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" /> Evidence
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
  );
};
