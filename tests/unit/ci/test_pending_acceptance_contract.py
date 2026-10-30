import pytest

from tests.acceptance.support.oracle import compare_expectations


@pytest.mark.parametrize(
    ("forbidden", "observed"),
    [
        ("certificate_forbidden", "certificate_required"),
        ("sealed_forbidden", "sealed_required"),
        ("verification_forbidden", "ledger_verification_required"),
    ],
)
def test_pending_acceptance_rejects_premature_authority(forbidden, observed):
    expected = {"evidence": {forbidden: True}}
    assert compare_expectations(expected, {"evidence": {observed: False}}) == []
    failures = compare_expectations(expected, {"evidence": {observed: True}})
    assert [failure.dimension for failure in failures] == [f"evidence.{forbidden}"]
