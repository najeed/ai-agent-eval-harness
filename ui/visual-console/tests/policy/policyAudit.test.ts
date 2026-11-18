import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPolicyAudit, collectAssertionObservations } from '../../src/lib/policyAudit.js';

const policy = { oracle_id: 'policy:human_review_before_adverse_commit',
  scenario_node_id: 'physician_review', requiredness: 'REQUIRED', outcome: 'PASS' };
const notification = { oracle_id: 'notification:sent', scenario_node_id: 'notify_provider', outcome: 'PASS' };
const trace = [
  { event: 'execution_graph_node', scenario_node_id: 'physician_review', execution_instance_id: 'review:1', oracle_results: [policy] },
  { event: 'execution_graph_node', data: { scenario_node_id: 'notify_provider', oracle_results: [notification] } },
];
const verifiedPackage = { evidence_chain_valid: true,
  cryptographic_verification: { verified: true, authority_valid: true },
  verdict: { assertions: [policy, notification] } };

test('an uncertified policy PASS is observed, not a signature or authority rejection', () => {
  const result = buildPolicyAudit({ events: trace,
    audit: { has_certificate: false, is_valid: false, certificate_authoritative: false,
      verification_status: 'UNVERIFIED', evaluation_passed: true,
      failure_reason: 'Run has not been cryptographically certified.' },
    evidencePackage: { cryptographic_verification: {
      has_certificate: false, verified: false, authority_valid: false, errors: [],
    } } });
  assert.equal(result.state, 'OBSERVED');
  assert.equal(result.outcome, 'PASS');
  assert.equal(result.verified, false);
  assert.deepEqual(result.errors, []);
});

test('missing certification cannot hide explicit invalid evidence', () => {
  const result = buildPolicyAudit({ events: trace,
    audit: { has_certificate: false, verification_status: 'UNVERIFIED',
      failure_reason: 'Run has not been cryptographically certified.' },
    evidencePackage: { verdict: { verified_outcome: 'EVIDENCE_INVALID' } } });
  assert.equal(result.state, 'VERIFICATION_FAILED');
  assert.deepEqual(result.errors, ['Evidence package outcome: EVIDENCE_INVALID']);
});

test('physician policy PASS survives a later non-policy node and duplicate flat/wrapped carriers', () => {
  const result = buildPolicyAudit({ events: [...trace, { event: 'execution_graph_node', data: trace[0] }] });
  assert.equal(result.state, 'OBSERVED');
  assert.equal(result.outcome, 'PASS');
  assert.equal(result.observed.length, 1);
  assert.equal(result.verified, false);
  assert.equal(collectAssertionObservations(trace).length, 2);
});

test('signature failure retains recorded policy PASS but cannot certify compliance', () => {
  const result = buildPolicyAudit({ events: trace,
    audit: { has_certificate: true, is_valid: false },
    evidencePackage: { evidence_chain_valid: false, verdict: { assertions: [] },
      cryptographic_verification: { verified: false, has_certificate: true,
        errors: ["EnvelopeSignatureVerificationFailed: 'system_id'"] },
      manifest: { verification_package: { executed_oracle_results: [policy] } } } });
  assert.equal(result.state, 'VERIFICATION_FAILED');
  assert.equal(result.outcome, 'PASS');
  assert.equal(result.observed.length, 1);
  assert.equal(result.certified.length, 0);
  assert.match(result.errors[0], /EnvelopeSignatureVerificationFailed/);
});

for (const outcome of ['FAIL', 'INVALID', 'NOT_EVALUATED'] as const) {
  test(`required ${outcome} is not erased by a duplicate PASS or the notification node`, () => {
    const result = buildPolicyAudit({ events: [
      { event: 'oracle_result', ...policy, outcome, passed: false }, ...trace,
    ] });
    assert.equal(result.outcome, outcome);
    assert.equal(result.observed.length, 1);
    assert.equal(result.observed[0].outcome, outcome);
    assert.equal(result.verified, false);
  });
}

test('verified package policy outcomes take precedence over diagnostic observations', () => {
  const result = buildPolicyAudit({ evidencePackage: verifiedPackage, audit: { is_valid: true, certificate_authoritative: true },
    events: [{ event: 'oracle_result', ...policy, outcome: 'FAIL' }] });
  assert.equal(result.state, 'CERTIFIED');
  assert.equal(result.outcome, 'PASS');
  assert.equal(result.certified.length, 1);
  assert.equal(result.observed[0].outcome, 'FAIL');
});

test('package flags alone cannot bypass the authoritative verification result', () => {
  const result = buildPolicyAudit({ evidencePackage: verifiedPackage,
    audit: { is_valid: false, has_certificate: true }, events: trace });
  assert.equal(result.verified, false);
  assert.equal(result.certified.length, 0);
});

test('a verified package without policy assertions cannot certify diagnostic policy PASS', () => {
  const result = buildPolicyAudit({ evidencePackage: { ...verifiedPackage, verdict: { assertions: [notification] } },
    audit: { is_valid: true, certificate_authoritative: true }, events: trace });
  assert.equal(result.state, 'OBSERVED');
  assert.equal(result.verified, false);
  assert.equal(result.observations.length, 1);
  assert.equal(result.observations[0].certified, false);
});

test('empty violations and unrelated allowed events never imply compliance', () => {
  const result = buildPolicyAudit({ violations: [], events: [
    { event: 'agent_message', data: { decision: 'allowed' } },
    { event: 'oracle_result', oracle_id: 'policy_description_accuracy', outcome: 'PASS' },
  ] });
  assert.equal(result.state, 'ABSENT');
  assert.equal(result.outcome, 'UNKNOWN');
});

test('pending hydration, unavailable evidence, and genuinely absent checks are distinct', () => {
  assert.equal(buildPolicyAudit({ loading: true }).state, 'PENDING');
  assert.equal(buildPolicyAudit({ unavailable: true }).state, 'UNAVAILABLE');
  assert.equal(buildPolicyAudit({}).state, 'ABSENT');
  const partial = buildPolicyAudit({ unavailable: true, events: trace });
  assert.equal(partial.state, 'UNAVAILABLE');
  assert.equal(partial.observed.length, 1);
});

test('declared policy oracle identity is recognized without fuzzy name inference', () => {
  const result = buildPolicyAudit({ evidencePackage: { scenario: { metadata: { policies: {
    review: { oracle_id: 'human-review', required: true },
    missing: { oracle_id: 'approval-revocation', required: true },
  } } } }, events: [{ event: 'oracle_result', oracle_id: 'human-review', outcome: 'PASS' }] });
  assert.equal(result.observed.length, 1);
  assert.equal(result.outcome, 'NOT_EVALUATED');
  assert.deepEqual(result.missingChecks, ['approval-revocation']);
});

test('typed INVALID remains invalid even if a boolean passed flag is contradictory', () => {
  const result = buildPolicyAudit({ events: [{ event: 'oracle_result', ...policy, outcome: 'INVALID', passed: true }] });
  assert.equal(result.outcome, 'INVALID');
});

test('nested finalization and policy events preserve typed outcomes', () => {
  const result = buildPolicyAudit({ events: [
    { event: 'run_end', data: { finalization: { executed_oracle_results: [policy] } } },
    { event: 'policy_check', data: { policy_id: 'consent', decision: 'allowed' } },
    { event: 'policy_check', policy_id: 'pending', outcome: 'NOT_EVALUATED' },
  ] });
  assert.equal(result.observed.length, 3);
  assert.equal(result.outcome, 'NOT_EVALUATED');
});

test('workflow declarations classify policy checks and require all declared checks', () => {
  const result = buildPolicyAudit({ evidencePackage: { scenario: { workflow: { nodes: [{
    id: 'review', expected_outcome: [
      { oracle_id: 'review-required', target: 'policy:review' },
      { oracle_id: 'second-required', target: 'policy:approval' },
    ],
  }] } } }, events: [{ event: 'oracle_result', oracle_id: 'review-required', outcome: 'PASS' }] });
  assert.equal(result.observed.length, 1);
  assert.deepEqual(result.missingChecks, ['second-required']);
  assert.equal(result.outcome, 'NOT_EVALUATED');
});

test('provisional or rejected authority never establishes certified policy PASS', () => {
  for (const audit of [
    { is_valid: true, certificate_authoritative: false },
    { is_valid: true, certificate_authoritative: true, provisional: true },
  ]) {
    const result = buildPolicyAudit({ evidencePackage: verifiedPackage, audit, events: trace });
    assert.equal(result.verified, false);
    assert.equal(result.certified.length, 0);
  }
});
