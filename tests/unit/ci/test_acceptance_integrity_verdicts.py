from types import SimpleNamespace

import pytest

from tests.acceptance.support.artifact_reader import normalize_actual_result


@pytest.mark.parametrize(
    ("gate_exit", "verify_exit", "admitted", "integrity_valid"),
    [(0, 0, True, True), (1, 0, False, True), (1, 1, False, False), (0, None, True, False)],
)
def test_acceptance_separates_admission_from_evidence_integrity(
    gate_exit, verify_exit, admitted, integrity_valid
):
    artifacts = SimpleNamespace(
        trace_reader=SimpleNamespace(execution_status="success", policy_decisions=[]),
        get_manifest=lambda: {"compliance": {"status": "pass"}},
        has_trace=True,
        has_certificate=True,
        is_sealed=True,
    )

    actual = normalize_actual_result(artifacts, gate_exit, verify_exit)

    assert actual["verification_success"] is admitted
    assert actual["evidence"]["ledger_verification_required"] is integrity_valid
