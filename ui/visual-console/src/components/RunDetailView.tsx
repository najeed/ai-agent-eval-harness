import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  ShieldCheck,
  AlertTriangle,
  FileText,
  Activity,
  CheckCircle2,
  XCircle,
  Download,
  Terminal,
  Database,
  Lock,
  Layers,
  HelpCircle,
  Loader2,
} from 'lucide-react';
import { ProvisionalBadge } from './ProvisionalBadge';

export interface RunDetailData {
  run_id: string;
  scenario: string;
  status: string; // Process status: RUNNING, EXECUTION_COMPLETED, EXECUTION_FAILED, STALLED
  verdict?: 'VERIFIED' | 'VERIFIED_PROVISIONAL' | 'NOT_VERIFIED' | 'POLICY_BREACH' | 'UNVERIFIED';
  provisional?: boolean;
  execution_mode?: string | null;
  score?: number;
  duration?: number;
  timestamp?: string;
  model?: string;
  target?: string;
  content_hash?: string;
  assertions?: Array<{
    name: string;
    passed: boolean;
    expected?: string;
    actual?: string;
    description?: string;
  }>;
  state_diff?: {
    initial: Record<string, any>;
    final: Record<string, any>;
    mutations: string[];
  };
  tool_calls?: Array<{
    turn: number;
    tool: string;
    parameters: Record<string, any>;
    result: any;
    duration_ms?: number;
  }>;
  policy_violations?: Array<{
    rule: string;
    severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    message: string;
  }>;
  signature?: {
    key_id: string;
    algorithm: string;
    digest: string;
    provenance_chain: string[];
  };
  events?: any[];
}

interface RunDetailViewProps {
  run: RunDetailData;
  onClose?: () => void;
}

export const RunDetailView: React.FC<RunDetailViewProps> = ({ run }) => {
  const [activeTab, setActiveTab] = useState<
    'summary' | 'verification' | 'evidence' | 'trace' | 'state' | 'policy' | 'artifacts'
  >('summary');

  const [auditResult, setAuditResult] = useState<any>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  // Authoritative evidence package: the primary source for "why".
  const [evidencePackage, setEvidencePackage] = useState<any>(null);
  const [streamEvents, setStreamEvents] = useState<any[]>([]);
  const [streamLoading, setStreamLoading] = useState(true);

  useEffect(() => {
    if (!run?.run_id) return;
    setAuditLoading(true);
    setStreamLoading(true);

    fetch(`/api/v1/runs/${run.run_id}/verify`)
      .then(res => res.json())
      .then(data => setAuditResult(data))
      .catch(e => console.error('Authoritative verification fetch failed:', e))
      .finally(() => setAuditLoading(false));

    fetch(`/api/v1/evidence/packages/${run.run_id}`)
      .then(res => (res.ok ? res.json() : null))
      .then(data => setEvidencePackage(data))
      .catch(() => setEvidencePackage(null));

    // Authoritative trace hydration via SSE endpoint
    const accumulatedEvents: any[] = [];
    let es: EventSource | null = null;
    try {
      es = new EventSource(`/api/v1/runs/${run.run_id}/stream`);
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          accumulatedEvents.push(ev);
          if (ev.event === 'run_end' || ev.event === 'trace_sealed' || ev.event === 'verification_certificate_issued') {
            setStreamEvents([...accumulatedEvents]);
            setStreamLoading(false);
          }
        } catch {}
      };
      es.onerror = () => {
        setStreamEvents([...accumulatedEvents]);
        setStreamLoading(false);
        if (es) es.close();
      };
    } catch {
      setStreamLoading(false);
    }

    return () => {
      if (es) es.close();
    };
  }, [run?.run_id]);

  // Hydrated Assertions: from evidencePackage (verdict/graph) or trace events
  const assertions = React.useMemo(() => {
    if (evidencePackage?.verdict?.assertions && Array.isArray(evidencePackage.verdict.assertions) && evidencePackage.verdict.assertions.length > 0) {
      return evidencePackage.verdict.assertions;
    }
    if (evidencePackage?.assertions && Array.isArray(evidencePackage.assertions) && evidencePackage.assertions.length > 0) {
      return evidencePackage.assertions;
    }
    if (evidencePackage?.evidence_graph?.nodes && Array.isArray(evidencePackage.evidence_graph.nodes) && evidencePackage.evidence_graph.nodes.length > 0) {
      return evidencePackage.evidence_graph.nodes.map((n: any) => ({
        name: n.label || n.oracle_id || n.metric || n.node || 'assertion',
        passed: n.passed === true,
        expected: n.expected != null ? String(n.expected) : undefined,
        actual: n.actual != null ? String(n.actual) : undefined,
        description: n.description || `Node: ${n.node || n.node_id || 'unknown'} (${n.kind || 'metric'})`,
        node: n.node || n.node_id,
        metric: n.label || n.oracle_id,
      }));
    }
    for (let i = streamEvents.length - 1; i >= 0; i--) {
      const evData = streamEvents[i]?.data;
      if (evData && Array.isArray(evData.assertions) && evData.assertions.length > 0) {
        return evData.assertions.map((a: any) => ({
          name: a.metric || a.assertion || a.name || a.oracle_id || 'assertion',
          passed: a.passed === true,
          expected: a.expected != null ? String(a.expected) : undefined,
          actual: a.actual != null ? String(a.actual) : undefined,
          description: a.description,
          node: a.node || a.node_id,
          metric: a.metric || a.assertion,
        }));
      }
    }
    return run.assertions || [];
  }, [evidencePackage, streamEvents, run.assertions]);

  // Hydrated Tool Calls
  const toolCalls = React.useMemo(() => {
    const tools: Array<{
      turn: number;
      tool: string;
      parameters: Record<string, any>;
      result: any;
      duration_ms?: number;
    }> = [];
    streamEvents.forEach((ev, idx) => {
      const evType = ev.event || ev.type;
      if (evType === 'tool_call' || evType === 'agent_tool_call') {
        const d = ev.data || ev;
        tools.push({
          turn: d.turn || d.step || idx + 1,
          tool: d.tool || d.name || d.tool_name || 'unknown_tool',
          parameters: d.parameters || d.params || d.arguments || d.input || {},
          result: d.result || d.output || {},
          duration_ms: d.duration_ms || d.latency_ms,
        });
      }
    });
    return tools.length > 0 ? tools : (run.tool_calls || []);
  }, [streamEvents, run.tool_calls]);

  // Hydrated State Diff
  const stateDiff = React.useMemo(() => {
    if (run.state_diff) return run.state_diff;
    if (evidencePackage?.state_diff) return evidencePackage.state_diff;
    const mutations: string[] = [];
    let initial: Record<string, any> = {};
    let final: Record<string, any> = {};
    streamEvents.forEach(ev => {
      const evType = ev.event || ev.type;
      const d = ev.data || {};
      if (evType === 'state_delta' || evType === 'state_mutation') {
        if (d.path || d.mutation) mutations.push(d.path || d.mutation || JSON.stringify(d));
      }
      if (evType === 'run_start' && d.initial_state) initial = d.initial_state;
      if (evType === 'run_end' && d.final_state) final = d.final_state;
    });
    if (mutations.length > 0 || Object.keys(initial).length > 0 || Object.keys(final).length > 0) {
      return { initial, final, mutations };
    }
    return null;
  }, [run.state_diff, evidencePackage, streamEvents]);

  // Hydrated Policy Evidence: 3 STRICT STATES
  const policyEvidence = React.useMemo(() => {
    const violations: Array<{
      rule: string;
      severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
      message: string;
    }> = [];
    const evaluations: Array<{
      policy_id: string;
      decision: string;
      reason?: string;
    }> = [];

    if (run.policy_violations && run.policy_violations.length > 0) {
      violations.push(...run.policy_violations);
    }

    streamEvents.forEach(ev => {
      const evType = ev.event || ev.type;
      const d = ev.data || {};
      if (evType === 'policy_violation' || d.status === 'policy_violation' || ev.status === 'policy_violation') {
        violations.push({
          rule: d.rule || d.policy_id || ev.rule || 'Guardrail Policy',
          severity: (d.severity || ev.severity || 'HIGH').toUpperCase() as any,
          message: d.message || d.violation || ev.message || 'Policy violation detected',
        });
      }
      if (evType === 'policy_check' || d.decision === 'allowed' || (d.policy_id && d.decision)) {
        evaluations.push({
          policy_id: d.policy_id || 'guardrail',
          decision: d.decision || 'allowed',
          reason: d.reason,
        });
      }
    });

    assertions.forEach((a: any) => {
      const isPolicy = a.kind === 'policy' || (typeof a.name === 'string' && a.name.toLowerCase().includes('policy')) || (typeof a.metric === 'string' && a.metric.toLowerCase().includes('policy'));
      if (isPolicy) {
        if (!a.passed) {
          violations.push({
            rule: a.name || a.metric || 'Policy Assertion',
            severity: 'HIGH',
            message: `Policy assertion failed: expected ${a.expected ?? 'pass'}, actual ${a.actual ?? 'fail'}`,
          });
        } else {
          evaluations.push({
            policy_id: a.name || a.metric || 'Policy Assertion',
            decision: 'allowed',
            reason: 'Assertion passed',
          });
        }
      }
    });

    let state: 'FAIL' | 'PASS' | 'NOT_VERIFIED' = 'NOT_VERIFIED';
    if (violations.length > 0) {
      state = 'FAIL';
    } else if (evaluations.length > 0) {
      state = 'PASS';
    } else {
      state = 'NOT_VERIFIED';
    }

    return { state, violations, evaluations };
  }, [run.policy_violations, streamEvents, assertions]);

  const allEvents = streamEvents.length > 0 ? streamEvents : (run.events || []);

  // Strict Authoritative Verdict Resolution: Never Fabricate or Infer from Field Existence
  const verdict = auditLoading
    ? 'VERIFYING'
    : (auditResult?.verification_status || 'UNVERIFIED');
  const isProvisional = auditResult?.provisional || verdict === 'VERIFIED_PROVISIONAL' || false;
  const isVerified = verdict === 'VERIFIED' || verdict === 'VERIFIED_PROVISIONAL';
  const isBreach = verdict === 'POLICY_BREACH' || policyEvidence.state === 'FAIL';
  const isNotVerified = verdict === 'FAILED_VERIFICATION' || verdict === 'NOT_VERIFIED';

  // [P0-2, P0-4] Authoritative failed assertions for "What failed" / RCA
  const crypto = evidencePackage?.cryptographic_verification;
  const failedAssertions: any[] = (
    evidencePackage?.verdict?.assertions ??
    evidencePackage?.assertions ??
    assertions
  ).filter((a: any) => a && a.passed === false);

  const whyLine: string = isVerified
    ? `PASS; ${crypto?.verified ? 'signature verified and evidence chain intact' : 'runtime verification decision: PASS'}.`
    : isBreach
      ? 'FAIL; authoritative policy_violation event in the certified trace.'
      : failedAssertions.length > 0
        ? `FAIL; ${failedAssertions.length} assertion(s) failed. First failure: ${failedAssertions[0].metric ?? failedAssertions[0].assertion ?? failedAssertions[0].name ?? 'unnamed'
        } on node '${failedAssertions[0].node ?? failedAssertions[0].node_id ?? '?'}'.`
        : crypto && crypto.errors?.length > 0
          ? `NOT VERIFIED; ${crypto.errors[0]}`
          : isNotVerified
            ? 'NOT VERIFIED; runtime verification decision: FAIL.'
            : 'INCONCLUSIVE; no authoritative verification result available for this run.';
  const attestationGrade: string =
    evidencePackage?.evidence_chain_valid === true ? 'Cryptographically Attested' : 'Unattested';

  const downloadPackageUrl = `/api/v1/evidence/packages/${run.run_id}?download=true`;

  const signerStatus = auditResult
    ? auditResult.is_valid
      ? `${auditResult.algorithm || 'Ed25519'} Verified (Merkle Root Sealed)`
      : auditResult.has_certificate
        ? `Verification Failed: ${auditResult.failure_reason || 'Tampered'}`
        : 'UNSIGNED (No Cryptographic Proof)'
    : run.signature?.algorithm
      ? `${run.signature.algorithm} (${run.signature.key_id?.slice(0, 10) || 'Active'})`
      : 'UNSIGNED (No Cryptographic Proof)';


  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col h-full min-h-[650px]">
      {/* Top Banner Verdict Header */}
      <div className="p-6 border-b border-slate-800 bg-slate-950/60">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-slate-500">
                Immutable Run ID:
              </span>
              <span className="text-xs font-mono font-bold text-slate-300 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                {run.run_id}
              </span>
              <ProvisionalBadge
                provisional={isProvisional}
                executionMode={auditResult?.execution_mode || run.execution_mode}
              />
            </div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              {run.scenario}
            </h1>
            <p className="text-xs text-slate-400">
              Verified against target: <span className="font-mono text-slate-300">{run.target || run.model || 'Unknown Target'}</span>
            </p>
          </div>

          {/* Primary Verified Outcome Badge */}
          <div className="flex items-center gap-3">
            <div
              className={`px-4 py-2.5 rounded-xl border flex items-center gap-2.5 shadow-lg ${isVerified && !isProvisional
                ? 'bg-emerald-950/50 border-emerald-500/40 text-emerald-300 shadow-emerald-500/10'
                : isProvisional
                  ? 'bg-amber-950/50 border-amber-500/40 text-amber-300 shadow-amber-500/10'
                  : isBreach
                    ? 'bg-rose-950/50 border-rose-500/40 text-rose-300 shadow-rose-500/10'
                    : isNotVerified
                      ? 'bg-rose-950/40 border-rose-500/30 text-rose-300'
                      : 'bg-amber-950/50 border-amber-500/40 text-amber-300 shadow-amber-500/10'
                }`}
            >
              {auditLoading ? (
                <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
              ) : isVerified && !isProvisional ? (
                <ShieldCheck className="w-6 h-6 text-emerald-400" />
              ) : isBreach || isNotVerified ? (
                <AlertTriangle className="w-6 h-6 text-rose-400" />
              ) : (
                <HelpCircle className="w-6 h-6 text-amber-400" />
              )}
              <div>
                <div className="text-[10px] uppercase font-mono tracking-wider text-slate-400">
                  Verification Verdict
                </div>
                <div className="text-sm font-black tracking-wide">
                  {auditLoading ? 'Verifying...' : isProvisional ? 'VERIFIED (PROVISIONAL)' : verdict}
                </div>
              </div>
            </div>


            <a
              href={downloadPackageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold shadow-lg shadow-indigo-500/20 flex items-center gap-2 transition"
            >
              <Download className="w-4 h-4" />
              Export Verification Package
            </a>
          </div>
        </div>

        {/* 7 Product Tabs */}
        <div className="flex items-center gap-1 mt-6 border-b border-slate-800 -mb-6 overflow-x-auto">
          {[
            { id: 'summary', label: 'Summary', icon: <Activity className="w-3.5 h-3.5" /> },
            { id: 'verification', label: 'Verification & Proofs', icon: <ShieldCheck className="w-3.5 h-3.5" /> },
            { id: 'evidence', label: 'State & Tool Evidence', icon: <Database className="w-3.5 h-3.5" /> },
            { id: 'trace', label: 'Telemetry Trace', icon: <Layers className="w-3.5 h-3.5" /> },
            { id: 'state', label: 'VFS Sandbox', icon: <Terminal className="w-3.5 h-3.5" /> },
            { id: 'policy', label: 'Policy & Guardrails', icon: <Lock className="w-3.5 h-3.5" /> },
            { id: 'artifacts', label: 'Artifacts & Package', icon: <FileText className="w-3.5 h-3.5" /> },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition -mb-px whitespace-nowrap ${activeTab === tab.id
                ? 'border-indigo-500 text-white bg-slate-900/50'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content Viewport */}
      <div className="p-6 flex-1 overflow-y-auto space-y-6 text-slate-300 text-xs">
        {/* 1. SUMMARY TAB */}
        {activeTab === 'summary' && (
          <div className="space-y-6">
            {/* Primary Question Callout */}
            <div className="p-5 rounded-2xl bg-slate-950/60 border border-slate-800 space-y-2">
              <span className="text-[11px] uppercase font-mono tracking-wider text-slate-500 block">
                Primary Assurance Objective
              </span>
              <div className="text-sm font-semibold text-slate-100">
                Did this agent safely achieve the intended state transition without policy violations?
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                {/* verdict-first "why", sourced only from the
                    authoritative evidence package. */}
                {whyLine}
              </p>
              {failedAssertions.length > 0 && (
                <div className="mt-3 space-y-1" data-testid="rca-failure-summary">
                  <span className="text-[10px] uppercase font-mono tracking-wider text-rose-400 font-bold">
                    What failed ({failedAssertions.length})
                  </span>
                  <ul className="space-y-1">
                    {failedAssertions.slice(0, 5).map((a: any, i: number) => (
                      <li
                        key={i}
                        className="text-[11px] font-mono text-rose-300 bg-rose-950/20 border border-rose-500/20 rounded px-2 py-1"
                        data-testid="failed-assertion-item"
                      >
                        ✖ {a.metric ?? a.assertion ?? a.name ?? a.label ?? a.oracle_id ?? 'assertion'} on node '
                        {a.node ?? a.node_id ?? '?'}'
                        {a.expected !== undefined && (
                          <span className="text-slate-500">
                            {' '}
                            ; expected {JSON.stringify(a.expected)}, actual{' '}
                            {JSON.stringify(a.actual ?? a.actual_after)}
                          </span>
                        )}
                      </li>
                    ))}
                    {failedAssertions.length > 5 && (
                      <li className="text-[10px] text-slate-500">
                        +{failedAssertions.length - 5} more in the evidence package
                      </li>
                    )}
                  </ul>
                  <Link
                    to={`/debugger?run_id=${encodeURIComponent(run.run_id)}`}
                    className="inline-flex items-center gap-1 text-[11px] text-indigo-400 hover:text-indigo-300 mt-1"
                  >
                    → Inspect first causal divergence in the Live Debugger
                  </Link>
                </div>
              )}
              <p className="text-[10px] font-mono text-slate-500 mt-2">
                Attestation grade: <span className="text-slate-300">{attestationGrade}</span>
              </p>
            </div>

            {/* Quick Metrics Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 font-mono">
              <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800">
                <span className="text-slate-500 text-[10px] block uppercase">Execution Status</span>
                <span className="text-sm font-bold text-white">{run.status || 'UNKNOWN'}</span>
              </div>
              <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800">
                <span className="text-slate-500 text-[10px] block uppercase">Duration</span>
                <span className="text-sm font-bold text-slate-200">
                  {run.duration != null ? `${run.duration.toFixed(1)}s` : 'NOT_RECORDED'}
                </span>
              </div>
              <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800">
                <span className="text-slate-500 text-[10px] block uppercase">Assurance Score</span>
                <span className="text-sm font-bold text-emerald-400">
                  {run.score != null ? `${(run.score * 100).toFixed(1)}%` : 'NOT_SCORED'}
                </span>
              </div>
              <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800">
                <span className="text-slate-500 text-[10px] block uppercase">Cryptographic Proof</span>
                <span className={`text-xs font-bold ${run.signature ? 'text-indigo-400' : 'text-amber-400'}`}>
                  {signerStatus}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 2. VERIFICATION TAB */}
        {activeTab === 'verification' && (
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-bold text-white mb-1">State Invariant & Outcome Assertions</h3>
              <p className="text-xs text-slate-400">
                Deterministic mathematical checks verified independently of model output.
              </p>
            </div>

            {assertions && assertions.length > 0 ? (
              <div className="space-y-2.5">
                {assertions.map((a: any, idx: number) => (
                  <div
                    key={idx}
                    className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 flex items-start justify-between gap-4 font-mono"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-200 font-bold">{a.name}</span>
                      </div>
                      {a.description && <p className="text-xs text-slate-400 font-sans">{a.description}</p>}
                      {a.expected && (
                        <div className="text-[10px] text-slate-500 mt-1">
                          Expected: <span className="text-slate-400">{a.expected}</span> | Actual: <span className="text-slate-300">{a.actual}</span>
                        </div>
                      )}
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase flex items-center gap-1 ${a.passed
                        ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                        : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'
                        }`}
                    >
                      {a.passed ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      {a.passed ? 'PASSED' : 'FAILED'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 rounded-xl bg-slate-950/40 border border-slate-800/80 text-center font-mono text-slate-500">
                {streamLoading ? 'HYDRATING TRACE AND ASSERTIONS...' : 'NO ASSERTION EVIDENCE RECORDED FOR THIS RUN'}
              </div>
            )}
          </div>
        )}

        {/* 3. EVIDENCE TAB */}
        {activeTab === 'evidence' && (
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-bold text-white mb-1">Ground-Truth Evidence & Tool Invocations</h3>
              <p className="text-xs text-slate-400">
                Auditable records of all physical actions taken by the agent during evaluation.
              </p>
            </div>

            {toolCalls && toolCalls.length > 0 ? (
              <div className="space-y-3">
                {toolCalls.map((t, idx) => (
                  <div key={idx} className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2 font-mono">
                    <div className="flex items-center justify-between text-slate-400">
                      <span className="text-indigo-400 font-bold">Turn {t.turn}: {t.tool}()</span>
                      <span className="text-[10px] text-slate-500">{t.duration_ms != null ? `${t.duration_ms}ms` : ''}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-[11px]">
                      <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                        <span className="text-slate-500 block mb-1">Parameters:</span>
                        <pre className="text-slate-300 whitespace-pre-wrap">{JSON.stringify(t.parameters, null, 2)}</pre>
                      </div>
                      <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                        <span className="text-slate-500 block mb-1">Result:</span>
                        <pre className="text-emerald-300 whitespace-pre-wrap">{JSON.stringify(t.result, null, 2)}</pre>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 rounded-xl bg-slate-950/40 border border-slate-800/80 text-center font-mono text-slate-500">
                {streamLoading ? 'HYDRATING TOOL INVOCATIONS...' : 'NO TOOL INVOCATIONS RECORDED FOR THIS RUN'}
              </div>
            )}
          </div>
        )}

        {/* 4. TRACE TAB */}
        {activeTab === 'trace' && (
          <div className="space-y-4">
            <h3 className="text-sm font-bold text-white">Full Telemetry Execution Flow</h3>
            <p className="text-xs text-slate-400">Chronological OpenTelemetry-aligned event stream.</p>
            {allEvents && allEvents.length > 0 ? (
              <div className="p-4 rounded-xl bg-slate-950 font-mono text-[11px] text-slate-300 border border-slate-800 max-h-96 overflow-y-auto space-y-1">
                {allEvents.map((ev, i) => (
                  <div key={i} className="flex items-start gap-3 py-1 border-b border-slate-900">
                    <span className="text-slate-500 shrink-0">{ev.timestamp?.slice(11, 19) || '00:00:00'}</span>
                    <span className="text-indigo-400 font-semibold shrink-0">{ev.event || ev.type}</span>
                    <span className="text-slate-400 truncate">{JSON.stringify(ev.data || ev)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 rounded-xl bg-slate-950/40 border border-slate-800/80 text-center font-mono text-slate-500">
                {streamLoading ? 'HYDRATING TELEMETRY STREAM...' : 'NO TELEMETRY TRACE RECORDED FOR THIS RUN'}
              </div>
            )}
          </div>
        )}

        {/* 5. STATE TAB */}
        {activeTab === 'state' && (
          <div className="space-y-4">
            <h3 className="text-sm font-bold text-white">VFS Sandbox State Delta</h3>
            <p className="text-xs text-slate-400">Virtual isolated environment mutations.</p>
            {stateDiff ? (
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2 font-mono text-xs">
                <div className="text-emerald-400 font-bold">State Mutations Recorded: {stateDiff.mutations?.length || 0}</div>
                <pre className="text-slate-400 whitespace-pre-wrap">{JSON.stringify(stateDiff, null, 2)}</pre>
              </div>
            ) : (
              <div className="p-8 rounded-xl bg-slate-950/40 border border-slate-800/80 text-center font-mono text-slate-500">
                {streamLoading ? 'HYDRATING STATE MUTATIONS...' : 'NO STATE MUTATIONS RECORDED FOR THIS RUN'}
              </div>
            )}
          </div>
        )}

        {/* 6. POLICY TAB */}
        {activeTab === 'policy' && (
          <div className="space-y-4">
            <h3 className="text-sm font-bold text-white">Policy & Compliance Audit</h3>
            <p className="text-xs text-slate-400">Safety boundaries and guardrail enforcement status.</p>
            {policyEvidence.state === 'FAIL' ? (
              <div className="space-y-3" data-testid="policy-state-fail">
                <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 space-y-1">
                  <span className="font-bold flex items-center gap-1.5 text-rose-400">
                    <XCircle className="w-4 h-4" /> POLICY BREACH DETECTED ({policyEvidence.violations.length} Violation{policyEvidence.violations.length === 1 ? '' : 's'})
                  </span>
                  <p className="text-xs text-rose-200">
                    Authoritative policy breach recorded in certified trace. Execution violated declared guardrails.
                  </p>
                </div>
                <div className="space-y-2">
                  {policyEvidence.violations.map((v, i) => (
                    <div key={i} className="p-3.5 rounded-xl bg-slate-950/60 border border-rose-500/20 text-rose-300 font-mono text-xs">
                      <span className="font-bold">[{v.severity}] {v.rule}:</span> {v.message}
                    </div>
                  ))}
                </div>
              </div>
            ) : policyEvidence.state === 'PASS' ? (
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3" data-testid="policy-state-pass">
                <span className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> PASS — Authoritative Policy Evidence Verified
                </span>
                <p className="text-xs text-slate-300">
                  {policyEvidence.evaluations.length} declared guardrail check{policyEvidence.evaluations.length === 1 ? '' : 's'} evaluated with 0 safety breaches.
                </p>
                <div className="space-y-1.5 pt-2">
                  {policyEvidence.evaluations.slice(0, 5).map((ev, i) => (
                    <div key={i} className="text-[11px] font-mono text-slate-400 bg-slate-900/60 border border-slate-800 rounded px-2.5 py-1 flex items-center justify-between">
                      <span>✓ {ev.policy_id}</span>
                      <span className="text-emerald-400 text-[10px] font-bold uppercase">{ev.decision}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="p-5 rounded-xl bg-slate-950/40 border border-amber-500/20 space-y-2" data-testid="policy-state-not-verified">
                <span className="text-amber-400 font-bold flex items-center gap-1.5">
                  <HelpCircle className="w-4 h-4" /> NOT VERIFIED / NO POLICY EVIDENCE
                </span>
                <p className="text-xs text-slate-400 leading-relaxed">
                  No guardrails, sandbox policy checks, or security invariant assertions were recorded for this scenario run. Absence of violation records cannot be derived as affirmative compliance evidence.
                </p>
              </div>
            )}
          </div>
        )}

        {/* 7. ARTIFACTS TAB */}
        {activeTab === 'artifacts' && (
          <div className="space-y-4">
            <h3 className="text-sm font-bold text-white">Verification Packages & Deliverables</h3>
            <p className="text-xs text-slate-400">Immutable, signed compliance packages for audit trails.</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <a
                href={downloadPackageUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-indigo-500 transition flex items-center justify-between group"
              >
                <div className="space-y-1">
                  <div className="font-bold text-white flex items-center gap-1.5">
                    <FileText className="w-4 h-4 text-indigo-400" /> Verification Package (.agentv-package.json)
                  </div>
                  <div className="text-slate-400 text-[11px]">Single-file self-contained cryptographic audit package.</div>
                </div>
                <Download className="w-4 h-4 text-slate-400 group-hover:text-white transition" />
              </a>

              <a
                href={`/api/v1/runs/${run.run_id}/report.pdf`}
                target="_blank"
                rel="noopener noreferrer"
                className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 hover:border-indigo-500 transition flex items-center justify-between group"
              >
                <div className="space-y-1">
                  <div className="font-bold text-white flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" /> Executive PDF Compliance Report
                  </div>
                  <div className="text-slate-400 text-[11px]">Executive summary for compliance & regulatory reviews.</div>
                </div>
                <Download className="w-4 h-4 text-slate-400 group-hover:text-white transition" />
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

