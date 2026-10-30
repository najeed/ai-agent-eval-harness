"""A release cannot pass by omitting or skipping a required corruption case."""

import json
from xml.etree import ElementTree

import pytest

from tools.ci.verify_evidence_chain_matrix import REQUIRED_CASES, SEMANTIC_FAILURES, verify_report


def _report(tmp_path):
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite")
    for name, (boundary, expected) in REQUIRED_CASES.items():
        case = ElementTree.SubElement(
            suite, "testcase", name=f"test_release_evidence_chain_matrix[{name}]"
        )
        properties = ElementTree.SubElement(case, "properties")
        for key, value in {
            "boundary": boundary,
            "cryptographic_integrity": "True",
            "product_failures": json.dumps(
                [SEMANTIC_FAILURES[name]] if name in SEMANTIC_FAILURES else []
            ),
            "issuance_rejected": str(
                name in {"duplicate_finalizations", "unavailable_observation"}
            ),
            "expected_certified": str(expected),
            "certified": str(expected),
            "independent_verified": str(expected or name == "false_agent_success"),
            "artifact_certified": str(
                expected
                or name in {"altered_graph", "invalid_certificate_signature", "unsealed_run"}
            ),
            "run_verified": str(expected or name == "altered_graph"),
            "run_verdict": (
                "ATTESTED_FAIL"
                if name == "false_agent_success"
                else "UNVERIFIED"
                if name == "unavailable_observation"
                else "VERIFIED"
                if expected or name == "altered_graph"
                else "FAILED_VERIFICATION"
            ),
        }.items():
            ElementTree.SubElement(properties, "property", name=key, value=value)
    return root, suite, tmp_path / "matrix.xml"


def test_complete_matrix_report_is_required(tmp_path):
    root, _, path = _report(tmp_path)
    ElementTree.ElementTree(root).write(path)
    result = verify_report(path)
    assert result["passed"] and result["case_count"] == 22


@pytest.mark.parametrize("case_id", SEMANTIC_FAILURES)
@pytest.mark.parametrize("defect", ["missing_reason", "invalid_signature", "missing_integrity"])
def test_semantic_corruptions_require_valid_signature_proof(tmp_path, case_id, defect):
    root, suite, path = _report(tmp_path)
    case = next(
        case
        for case in suite
        if case.get("name") == f"test_release_evidence_chain_matrix[{case_id}]"
    )
    if defect == "missing_integrity":
        case.find("./properties/property[@name='cryptographic_integrity']").set("value", "False")
    else:
        reasons = (
            []
            if defect == "missing_reason"
            else [SEMANTIC_FAILURES[case_id], "SignatureVerificationFailed"]
        )
        case.find("./properties/property[@name='product_failures']").set(
            "value", json.dumps(reasons)
        )
    ElementTree.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="semantic rejection proof"):
        verify_report(path)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "skipped",
        "failure",
        "error",
        "wrong_boundary",
        "false_positive",
        "missing_proof",
    ],
)
def test_incomplete_or_corrupt_matrix_report_blocks_release(tmp_path, defect):
    root, suite, path = _report(tmp_path)
    case = suite[-1]
    if defect == "missing":
        suite.remove(case)
    elif defect == "duplicate":
        suite.append(case)
    elif defect in {"skipped", "failure", "error"}:
        ElementTree.SubElement(case, defect)
    elif defect == "wrong_boundary":
        case.find("./properties/property[@name='boundary']").set("value", "other")
    elif defect == "false_positive":
        case.find("./properties/property[@name='certified']").set("value", "True")
    else:
        positive = suite[0]
        positive.find("./properties/property[@name='independent_verified']").set("value", "False")
    ElementTree.ElementTree(root).write(path)
    with pytest.raises(ValueError):
        verify_report(path)


@pytest.mark.parametrize("key", ["independent_verified", "artifact_certified", "run_verified"])
def test_one_rejection_cannot_hide_another_verifier_accepting_corruption(tmp_path, key):
    root, suite, path = _report(tmp_path)
    corrupt = suite.find("./testcase[@name='test_release_evidence_chain_matrix[unsigned_package]']")
    corrupt.find(f"./properties/property[@name='{key}']").set("value", "True")
    ElementTree.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="proof"):
        verify_report(path)
