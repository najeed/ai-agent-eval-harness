export interface RunTraceEligibilityInput {
  evidence_nodes?: number | string;
  size?: number | string;
  can_certify?: boolean;
  score?: number | string;
  decision?: { score?: number | string };
  failed_oracles?: unknown[];
  verdict?: string;
  verification_status?: string;
}

export interface TraceEligibilityResult {
  isEmptyTrace: boolean;
  isCriteriaFailed: boolean;
}

/**
 * Evaluates whether an inspected run trace is empty/unattestable or has failed evaluation criteria.
 *
 * NOTE: runDetails.can_certify indicates whether the backend would certify the run as PASSING.
 * Ineligible/failed runs return can_certify: false even when dozens of evidence nodes were
 * recorded. Thus, can_certify MUST NOT be used to classify a trace as empty or unattestable.
 */
export function evaluateTraceEligibility(
  runDetails: RunTraceEligibilityInput | null | undefined
): TraceEligibilityResult {
  const isEmptyTrace = Boolean(
    runDetails &&
    ((runDetails.evidence_nodes !== undefined && Number(runDetails.evidence_nodes) === 0) ||
      (runDetails.size !== undefined && Number(runDetails.size) === 0))
  );

  const isCriteriaFailed = Boolean(
    runDetails &&
    !isEmptyTrace &&
    ((runDetails.score !== undefined && Number(runDetails.score) < 1.0) ||
      (runDetails.decision?.score !== undefined && Number(runDetails.decision.score) < 1.0) ||
      (Array.isArray(runDetails.failed_oracles) && runDetails.failed_oracles.length > 0) ||
      runDetails.verdict === 'FAILED' ||
      runDetails.verification_status === 'FAILED')
  );

  return { isEmptyTrace, isCriteriaFailed };
}
