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
import { useRBAC } from '../context/RBACContext';

interface RunItem {
  run_id: string;
  scenario: string;
  timestamp: string;
  status: string;
  verdict?: string;
  has_certificate?: boolean;
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
        loadedRuns.slice(0, 10).map((r) => ({
          run_id: r.run_id,
          scenario: r.scenario || r.run_id,
          timestamp: r.timestamp || 'N/A',
          status: r.execution_status || r.status || 'UNKNOWN',
          verdict: r.verification_status || (r.has_certificate ? 'VERIFIED' : r.passed === false ? 'NOT_VERIFIED' : 'UNVERIFIED'),
          has_certificate: !!r.has_certificate,
        }))
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
        }}
        targetProfile={selectedProfile}
        tenantId={tenantId}
        workspaceId={workspaceId}
        seed={42}
        evaluators={['GroundTruthValidator', 'PolicyGuardrailsVerifier', 'StateHygieneChecker']}
        isLaunching={isLaunching}
      />

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
              {runs.map((r) => (
                <tr key={r.run_id} className="hover:bg-slate-850/50 transition">
                  <td className="py-3 font-bold text-slate-200">{r.run_id}</td>
                  <td className="py-3 font-sans text-slate-300 font-medium">{r.scenario}</td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 w-fit ${r.has_certificate
                        ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                        : 'bg-indigo-500/10 border border-indigo-500/20 text-indigo-400'
                        }`}
                    >
                      {r.has_certificate ? <ShieldCheck className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                      {r.has_certificate ? 'VERIFIED' : r.status}
                    </span>
                  </td>
                  <td className="py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => navigate(`/reports?run_id=${r.run_id}`)}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-sans font-medium transition flex items-center gap-1"
                      >
                        <Eye className="w-3 h-3" /> Inspect
                      </button>
                      <a
                        href={`/api/v1/evidence/packages/${r.run_id}?download=true`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1 rounded bg-indigo-950/60 hover:bg-indigo-900 border border-indigo-500/30 text-indigo-300 text-[11px] font-sans font-semibold transition flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" /> Package
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
