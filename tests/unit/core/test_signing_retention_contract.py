"""Signing enforces the provider's declared immutable-retention capability."""

from types import SimpleNamespace

import pytest

from eval_runner import runtime_services
from eval_runner.verifier import CertificationFailedError, TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize(
    ("guarantee", "accepted"),
    [
        ("HARDWARE_OR_CLOUD_ENFORCED_WORM", True),
        ("TAMPER_EVIDENT_LOGICAL_SEAL", False),
        ("APPEND_ONLY", False),
        (None, False),
        ("", False),
    ],
)
def test_signing_retention_provider_capability(
    finalization_source, monkeypatch, guarantee, accepted
):
    provider, scenario = finalization_source
    monkeypatch.setattr(
        runtime_services,
        "resolve_artifact_store",
        lambda: SimpleNamespace(immutability_guarantee=guarantee),
    )
    trace = provider.get_trace_bytes("run-a")
    execution_manifest = provider.get_manifest("run-a")["execution_manifest"]
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]

    def sign():
        return TraceVerifier.sign_trace_bytes(
            trace,
            run_id="run-a",
            run_store=provider,
            scenario_data=scenario,
            execution_manifest=execution_manifest,
            metadata={"required_oracle_ids": ["oracle-1"], "require_immutable_worm": True},
            evidence_root_hash=finalization["evidence_root_hash"],
            execution_mode="live",
            provisional=False,
            compliance_status="pass",
            compliance_score=1.0,
        )

    if not accepted:
        with pytest.raises(CertificationFailedError, match="ImmutableRetentionRequired"):
            sign()
        return

    certificate = sign()
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=trace,
        canonical_manifest=execution_manifest,
        scenario_data=scenario,
    )
    assert result["verified"], result["failures"]
