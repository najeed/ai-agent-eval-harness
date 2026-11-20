import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evaluateTraceEligibility } from '../../src/lib/trustCenterLogic.js';

test('run with failed evaluation criteria and can_certify:false is NOT classified as an empty trace', () => {
  const failedRun = {
    run_id: 'run-agentv-demo-um-adverse-review-v3-physician-hitl-01a1f6320a6477e9896604d19288533d',
    evidence_nodes: 28,
    size: 76,
    can_certify: false,
    score: 0,
    status: 'COMPLETED',
    verdict: 'FAILED',
    failed_oracles: ['policy:human_review_before_adverse_commit'],
  };

  const { isEmptyTrace, isCriteriaFailed } = evaluateTraceEligibility(failedRun);

  // Must not be an empty trace because it contains 28 evidence nodes and 76 trace events
  assert.equal(isEmptyTrace, false);
  // Must be criteria failed so the user can issue an Attestation of Non-Certification
  assert.equal(isCriteriaFailed, true);
});

test('pre-flight aborted run with 0 evidence nodes is classified as an empty trace', () => {
  const abortedRun = {
    run_id: 'run-aborted-preflight',
    evidence_nodes: 0,
    size: 1,
    can_certify: false,
    score: 0,
    status: 'FAILED',
  };

  const { isEmptyTrace, isCriteriaFailed } = evaluateTraceEligibility(abortedRun);

  assert.equal(isEmptyTrace, true);
  assert.equal(isCriteriaFailed, false);
});

test('run with 0 trace events is classified as an empty trace', () => {
  const zeroEventRun = {
    run_id: 'run-zero-events',
    evidence_nodes: 0,
    size: 0,
    can_certify: false,
  };

  const { isEmptyTrace, isCriteriaFailed } = evaluateTraceEligibility(zeroEventRun);

  assert.equal(isEmptyTrace, true);
  assert.equal(isCriteriaFailed, false);
});

test('passing certified run with high score is neither empty trace nor criteria failed', () => {
  const passingRun = {
    run_id: 'run-passed-cert',
    evidence_nodes: 15,
    size: 40,
    can_certify: true,
    score: 1.0,
    status: 'COMPLETED',
    verdict: 'PASSED',
    failed_oracles: [],
  };

  const { isEmptyTrace, isCriteriaFailed } = evaluateTraceEligibility(passingRun);

  assert.equal(isEmptyTrace, false);
  assert.equal(isCriteriaFailed, false);
});
