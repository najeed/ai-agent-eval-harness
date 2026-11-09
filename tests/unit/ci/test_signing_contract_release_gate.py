"""Missing, duplicated, failed or skipped signing evidence must block the local gate."""

import xml.etree.ElementTree as ET

import pytest

from tools.ci.verify_signing_contract_matrix import (
    REQUIRED,
    check_purity,
    load_required_matrix,
    sync_matrix,
    verify,
)


def report(path):
    root = ET.Element("testsuite")
    for function, count in REQUIRED.items():
        for index in range(count):
            ET.SubElement(root, "testcase", name=f"{function}[{index}]")
    ET.ElementTree(root).write(path)
    return root


def test_local_signing_evidence_cannot_claim_live_kms_or_release_approval(tmp_path):
    path = tmp_path / "junit.xml"
    report(path)
    result = verify(path)
    assert result["passed_cases"] == 153
    assert result["core_local_evidence_verified"]
    assert not result["live_kms_evidence_verified"]
    assert not result["large_payload_kms_feature_claim_ready"]
    assert not result["release_approval"]


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "failure", "error", "skipped", "unexpected"]
)
def test_incomplete_signing_evidence_is_rejected(tmp_path, defect):
    path = tmp_path / "junit.xml"
    root = report(path)
    case = root.find("testcase")
    if defect == "missing":
        root.remove(case)
    elif defect == "duplicate":
        ET.SubElement(root, "testcase", name=case.get("name"))
    elif defect == "unexpected":
        ET.SubElement(root, "testcase", name="unexpected")
    else:
        ET.SubElement(case, defect)
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError):
        verify(path)


def test_signing_contract_ast_purity_matches_manifest():
    violations = check_purity()
    assert not violations, f"Signing contract purity violations: {violations}"


def test_sync_matrix_from_junit_xml(tmp_path):
    junit_path = tmp_path / "sample.xml"
    report(junit_path)
    manifest_path = tmp_path / "synced_manifest.json"

    num_funcs, total_cases = sync_matrix(source_junit=junit_path, manifest_path=manifest_path)
    assert total_cases == 153
    assert num_funcs == 30

    reloaded = load_required_matrix(manifest_path)
    assert reloaded == REQUIRED
