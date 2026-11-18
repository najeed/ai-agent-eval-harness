/** Policy observations are diagnostics until the package and its authority verify. */
type Row = Record<string, any>;
export type PolicyOutcome = 'PASS' | 'FAIL' | 'INVALID' | 'NOT_EVALUATED' | 'UNKNOWN';
export interface PolicyObservation {
  id: string;
  node: string;
  execution: string;
  outcome: PolicyOutcome;
  required: boolean;
  certified: boolean;
  reason: string;
}
const record = (value: any): Row => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const rows = (value: any): Row[] => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];

/** Collect every execution carrier; a later notification node cannot erase review evidence. */
export function collectAssertionObservations(events: unknown[]): Row[] {
  const result: Row[] = [];
  function collect(value: Row, context: Row, depth = 0) {
    if (depth > 5) return;
    const scoped = {
      scenario_node_id: value.scenario_node_id ?? value.node_id ?? context.scenario_node_id,
      execution_instance_id: value.execution_instance_id ?? context.execution_instance_id,
      attempt: value.attempt ?? context.attempt,
    };
    for (const key of ['assertions', 'oracle_results', 'executed_oracle_results']) {
      for (const item of rows(value[key])) result.push({ ...scoped, ...item });
    }
    for (const key of ['data', 'result', 'verdict', 'finalization']) {
      if (Object.keys(record(value[key])).length) collect(value[key], scoped, depth + 1);
    }
  }
  for (const event of events) {
    const ev = record(event);
    collect(ev, {});
    const d = { ...ev, ...record(ev.data) };
    const type = ev.event ?? ev.type;
    if (type === 'oracle_result' || type === 'assertion_result') result.push(d);
    if (type === 'policy_check' || type === 'policy_violation') {
      result.push({ ...d, kind: 'policy', policy_id: d.policy_id ?? d.rule ?? 'guardrail',
        outcome: type === 'policy_violation' ? 'FAIL' : d.outcome ?? d.decision });
    }
  }
  return result;
}

function outcome(row: Row): PolicyOutcome {
  const typed = String(row.outcome ?? row.status ?? row.verdict ?? row.decision ?? '').toUpperCase();
  if (['INVALID', 'ERROR', 'EVALUATION_INVALID'].includes(typed)) return 'INVALID';
  if (['NOT_EVALUATED', 'NOT_APPLICABLE', 'SKIPPED', 'PENDING'].includes(typed)) return 'NOT_EVALUATED';
  if (['FAIL', 'FAILED', 'DENIED', 'BLOCKED'].includes(typed)) return 'FAIL';
  if (['PASS', 'PASSED', 'ALLOWED'].includes(typed)) return 'PASS';
  if (typed) return 'UNKNOWN';
  return row.passed === true ? 'PASS' : row.passed === false ? 'FAIL' : 'UNKNOWN';
}

export function buildPolicyAudit(input: {
  evidencePackage?: any;
  audit?: any;
  events?: unknown[];
  assertions?: unknown[];
  violations?: unknown[];
  loading?: boolean;
  unavailable?: boolean;
}) {
  const pkg = record(input.evidencePackage);
  const crypto = record(pkg.cryptographic_verification);
  const audit = record(input.audit);
  const policies = record(record(record(pkg.scenario).metadata).policies);
  const declaredIds = new Set<string>();
  const requiredIds = new Set<string>();
  for (const [id, value] of Object.entries(policies)) {
    const declaration = record(value);
    const oracleId = String(declaration.oracle_id ?? `policy:${id}`);
    declaredIds.add(oracleId);
    if (declaration.required === true) requiredIds.add(oracleId);
  }
  const workflow = pkg.scenario?.workflow;
  const nodes = Array.isArray(workflow) ? rows(workflow) : rows(workflow?.nodes);
  for (const node of nodes) {
    for (const assertion of rows(node.expected_outcome)) {
      const id = String(assertion.oracle_id ?? assertion.id ?? '');
      if (!id || !(String(assertion.target ?? '').startsWith('policy:')
        || assertion.kind === 'policy' || id.startsWith('policy:'))) continue;
      declaredIds.add(id);
      if (assertion.required !== false && !['OPTIONAL', 'INFORMATIONAL'].includes(assertion.requiredness)) requiredIds.add(id);
    }
  }
  const verified = pkg.evidence_chain_valid === true && crypto.verified === true
    && crypto.authority_valid === true && audit.is_valid === true
    && audit.certificate_authoritative === true && audit.provisional !== true;
  const certifiedRows = verified
    ? rows(pkg.verdict?.assertions ?? pkg.manifest?.verification_package?.executed_oracle_results)
    : [];
  const diagnosticRows = [
    ...rows(input.assertions), ...rows(pkg.observed_assertions),
    ...collectAssertionObservations(input.events ?? []),
    // Signed-package contents are useful observations even when their signature fails.
    ...rows(pkg.manifest?.verification_package?.executed_oracle_results),
    ...(!verified ? rows(pkg.verdict?.assertions) : []),
    ...rows(input.violations).map(row => ({ ...row, kind: 'policy', policy_id: row.rule, outcome: 'FAIL' })),
  ];
  function normalize(source: Row[], certified: boolean): PolicyObservation[] {
    const byKey = new Map<string, PolicyObservation>();
    for (const row of source) {
      const assertion = record(row.assertion);
      const definition = record(row.definition);
      const id = String(row.oracle_id ?? row.policy_id ?? row.name ?? row.metric ?? assertion.oracle_id ?? '');
      const target = String(row.target ?? assertion.target ?? definition.target ?? '');
      if (!(row.kind === 'policy' || row.policy_id || id.startsWith('policy:')
        || target.startsWith('policy:') || declaredIds.has(id))) continue;
      const item: PolicyObservation = {
        id: id || target || 'policy', node: String(row.scenario_node_id ?? row.node_id ?? row.node ?? ''),
        execution: String(row.execution_instance_id ?? row.attempt_id ?? row.attempt ?? ''),
        outcome: outcome(row), required: row.requiredness ? row.requiredness === 'REQUIRED' : row.required !== false,
        certified, reason: String(row.error ?? row.reason ?? row.description ?? row.message ?? ''),
      };
      const key = JSON.stringify([item.id, item.node]);
      const previous = byKey.get(key);
      // Conflicting duplicates cannot erase FAIL/INVALID or requiredness.
      const rank = { PASS: 0, UNKNOWN: 1, NOT_EVALUATED: 2, INVALID: 3, FAIL: 4 };
      if (previous) {
        if (rank[previous.outcome] > rank[item.outcome]) item.reason = previous.reason || item.reason;
        item.outcome = rank[previous.outcome] > rank[item.outcome] ? previous.outcome : item.outcome;
        item.required ||= previous.required;
        item.reason ||= previous.reason;
      }
      byKey.set(key, item);
    }
    return [...byKey.values()];
  }
  const certified = normalize(certifiedRows, true);
  const observed = normalize(diagnosticRows, false);
  const active = verified && certified.length ? certified : observed;
  const missingChecks = [...requiredIds].filter(id => !active.some(item => item.id === id));
  const decision: PolicyOutcome = active.some(item => item.required && item.outcome === 'FAIL') ? 'FAIL'
    : active.some(item => item.outcome === 'INVALID') ? 'INVALID'
    : missingChecks.length || active.some(item => item.outcome !== 'PASS') ? 'NOT_EVALUATED'
    : active.length ? 'PASS' : 'UNKNOWN';
  const errors = [...new Set([
    ...(Array.isArray(crypto.errors) ? crypto.errors : []),
    ...(Array.isArray(audit.failures) ? audit.failures : []),
    ...(audit.failure_reason ? [audit.failure_reason] : []),
    ...(['EVIDENCE_INVALID', 'AUTHORITY_REJECTED'].includes(pkg.verdict?.verified_outcome)
      ? [`Evidence package outcome: ${pkg.verdict.verified_outcome}`] : []),
  ].filter((item): item is string => typeof item === 'string' && Boolean(item)))];
  const rejected = errors.length > 0 || crypto.verified === false && crypto.has_certificate === true
    || crypto.authority_valid === false || audit.has_certificate === true
      && (audit.is_valid === false || audit.certificate_authoritative === false);
  const state = rejected ? 'VERIFICATION_FAILED' : input.loading ? 'PENDING'
    : input.unavailable ? 'UNAVAILABLE' : verified && certified.length ? 'CERTIFIED'
    : observed.length ? 'OBSERVED' : 'ABSENT';
  return { state, outcome: decision, certified, observed, missingChecks, errors,
    verified: verified && !rejected && certified.length > 0, observations: active };
}
