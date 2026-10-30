"""Fail release certification when any required evidence-chain case is absent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree

REQUIRED_CASES = {
    "complete_chain": ("all", True),
    "altered_scenario": ("scenario", False),
    "omitted_execution": ("execution", False),
    "omitted_observation": ("independent_observation", False),
    "altered_observation": ("independent_observation", False),
    "omitted_oracle": ("oracle_outcomes", False),
    "failed_oracle": ("oracle_outcomes", False),
    "omitted_finalization": ("signed_finalization", False),
    "unsigned_finalization": ("signed_finalization", False),
    "duplicate_finalizations": ("signed_finalization", False),
    "altered_graph": ("evidence_graph", False),
    "altered_root": ("evidence_graph", False),
    "altered_manifest": ("certificate", False),
    "provisional_certificate": ("certificate", False),
    "legacy_certificate_profile": ("certificate", False),
    "contradictory_execution_mode": ("execution", False),
    "unsigned_package": ("certificate", False),
    "invalid_certificate_signature": ("certificate", False),
    "omitted_trace": ("independent_verification", False),
    "unsealed_run": ("independent_verification", False),
    "false_agent_success": ("execution_to_observation", False),
    "unavailable_observation": ("execution_to_observation", False),
}

SEMANTIC_FAILURES = {
    "provisional_certificate": "ProvisionalExecutionCertificationProhibited",
    "legacy_certificate_profile": "UnsupportedCertificateProfile",
    "contradictory_execution_mode": "ExecutionModeMismatch",
}


def verify_report(path: Path) -> dict:
    root = ElementTree.parse(path).getroot()  # nosec B314
    for suite in root.iter("testsuite"):
        if any(int(suite.get(key, "0")) != 0 for key in ("failures", "errors", "skipped")):
            raise ValueError("Evidence-chain suite contains failures, errors, or skipped cases")
    rows = {}
    prefix = "test_release_evidence_chain_matrix["
    for case in root.iter("testcase"):
        name = case.get("name", "")
        if not name.startswith(prefix) or not name.endswith("]"):
            raise ValueError(f"Unexpected matrix testcase: {name}")
        case_id = name[len(prefix) : -1]
        if case_id not in REQUIRED_CASES or case_id in rows:
            raise ValueError(f"Unexpected or duplicate matrix case: {case_id}")
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError(f"Required matrix case did not pass: {case_id}")
        properties = {
            prop.get("name"): prop.get("value") for prop in case.findall("./properties/property")
        }
        boundary, expected = REQUIRED_CASES[case_id]
        if case_id in SEMANTIC_FAILURES:
            failures = json.loads(properties.get("product_failures", "[]"))
            if (
                properties.get("cryptographic_integrity", "").lower() != "true"
                or not isinstance(failures, list)
                or not all(isinstance(reason, str) for reason in failures)
                or not any(SEMANTIC_FAILURES[case_id] in reason for reason in failures)
                or any(
                    "SignatureVerificationFailed" in reason or "TraceHashMismatch" in reason
                    for reason in failures
                )
            ):
                raise ValueError(f"Missing valid-signature semantic rejection proof: {case_id}")
        if properties.get("boundary") != boundary:
            raise ValueError(f"Missing or incorrect boundary proof: {case_id}")
        for key in ("expected_certified", "certified"):
            if properties.get(key, "").lower() != str(expected).lower():
                raise ValueError(f"Incorrect or missing {key} verdict: {case_id}")
        if case_id == "unavailable_observation":
            if (
                properties.get("issuance_rejected", "").lower() != "true"
                or properties.get("run_verdict") != "UNVERIFIED"
            ):
                raise ValueError("Unavailable observation lacks issuance rejection proof")
        else:
            independent_expected = expected or case_id == "false_agent_success"
            if (
                properties.get("independent_verified", "").lower()
                != str(independent_expected).lower()
            ):
                raise ValueError(f"Incorrect or missing independent verification proof: {case_id}")
            if case_id == "false_agent_success":
                if properties.get("run_verdict") != "ATTESTED_FAIL":
                    raise ValueError("False agent success must yield a valid negative attestation")
            else:
                run_expected = expected or case_id == "altered_graph"
                artifact_expected = expected or case_id in {
                    "altered_graph",
                    "invalid_certificate_signature",
                    "unsealed_run",
                }
                for key, value in (
                    ("run_verified", run_expected),
                    ("artifact_certified", artifact_expected),
                ):
                    if properties.get(key, "").lower() != str(value).lower():
                        raise ValueError(f"Incorrect or missing {key} proof: {case_id}")
                verdict = properties.get("run_verdict")
                if verdict != ("VERIFIED" if run_expected else "FAILED_VERIFICATION"):
                    raise ValueError(f"Run verdict contradicts verification proof: {case_id}")
        if (
            case_id == "duplicate_finalizations"
            and properties.get("issuance_rejected", "").lower() != "true"
        ):
            raise ValueError("Duplicate finalization lacks pre-seal issuance rejection proof")
        rows[case_id] = {"boundary": boundary, "certified": expected, "proof": properties}
    missing = set(REQUIRED_CASES) - set(rows)
    if missing:
        raise ValueError(f"Required evidence-chain cases missing: {sorted(missing)}")
    return {"passed": True, "case_count": len(rows), "cases": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_report(args.report)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        print(f"Evidence-chain release gate FAILED: {exc}")
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence-chain release gate PASSED: {result['case_count']} required cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
