"""Missing, duplicated, failed or skipped signing evidence must block the local gate."""

import xml.etree.ElementTree as ET

import pytest

from tools.ci.verify_signing_contract_matrix import REQUIRED, verify


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
    assert result["passed_cases"] == 148
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
