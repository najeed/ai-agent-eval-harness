"""Signing binds the finalization carried by the provider's exact trace bytes."""

import pytest

from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_certification_service_and_trust_boundary import _seed_run


@pytest.fixture
def finalization_source(tmp_path, monkeypatch):
    root = tmp_path / "project"
    trust = root / ".aes" / "keys"
    trust.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "TRUST_ROOT", trust)
    for identity in ("system_id", "eval_kernel"):
        IdentityService._provision_local_identity(identity)
    provider = LocalFileRunStore(tmp_path / "provider")
    scenario = _seed_run(provider, "run-a")
    return provider, scenario


def test_signing_recovers_finalization_from_trace_without_metadata_hint(finalization_source):
    provider, scenario = finalization_source
    execution_manifest = provider.get_manifest("run-a")["execution_manifest"]
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    trace = provider.get_trace_bytes("run-a")

    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=execution_manifest,
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
        execution_mode="live",
        provisional=False,
        compliance_status="pass",
        compliance_score=1.0,
    )

    package = certificate["verification_package"]
    assert package["finalization_hash"] == finalization["finalization_hash"]
    result = VerificationAuthority.verify_certification_artifact(
        package,
        raw_trace_bytes=trace,
        canonical_manifest=execution_manifest,
        scenario_data=scenario,
    )
    assert result["verified"], result["failures"]


@pytest.mark.parametrize(
    ("carrier", "nested", "issuable"),
    [
        ("run_end", False, True),
        ("run_end", True, True),
        ("verification_decision", False, False),
        ("session_decision", True, False),
    ],
)
def test_certification_finalization_carrier_contract(
    finalization_source, tmp_path, carrier, nested, issuable
):
    source, scenario = finalization_source
    source_manifest = source.get_manifest("run-a")
    events = source.get_events("run-a", offset=0, limit=100)
    finalization = events[-1]["data"]
    final_event = {"event": carrier, "_seq": 4}
    if nested:
        final_event["data"] = {"finalization": finalization}
    else:
        final_event["finalization"] = finalization
    provider = LocalFileRunStore(tmp_path / "carrier-provider")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", [*events[:-1], final_event])
    provider.save_run_manifest("run-a", source_manifest)

    if not issuable:
        with pytest.raises(ValueError, match="missing mandatory authoritative"):
            execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)
        assert provider.get_run("run-a")["lifecycle"] != "SEALED"
        assert not TraceVerifier.verify_run("run-a", run_store=provider).get("verified")
        return

    issued = execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)

    assert issued["certified"] is True
    assert TraceVerifier.verify_run("run-a", run_store=provider)["verified"] is True
