"""Terminal finalization carriers retain their hash without a caller metadata hint."""

import pytest

from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("nested", [False, True])
def test_signing_derives_terminal_finalization_hash_without_hint(
    finalization_source, tmp_path, nested
):
    source, scenario = finalization_source
    events = source.get_events("run-a", offset=0, limit=100)
    finalization = events.pop()["data"]
    terminal = {"event": "run_end", "_seq": 4}
    if nested:
        terminal["data"] = {"finalization": finalization}
    else:
        terminal["finalization"] = finalization
    provider = LocalFileRunStore(tmp_path / "terminal-hash")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", [*events, terminal])
    provider.save_run_manifest("run-a", source.get_manifest("run-a"))
    provider.update_run_status("run-a", "FINALIZING")
    raw = provider.get_trace_bytes("run-a")
    manifest = provider.get_manifest("run-a")["execution_manifest"]
    certificate = TraceVerifier.sign_trace_bytes(
        raw,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=manifest,
        metadata={"required_oracle_ids": ["oracle-1"]},
        execution_mode="live",
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    package = certificate["verification_package"]
    assert package["finalization_hash"] == finalization["finalization_hash"]
    assert package["evaluation_hash"] == finalization["finalization_hash"]
    result = VerificationAuthority.verify_certification_artifact(
        package, raw_trace_bytes=raw, canonical_manifest=manifest, scenario_data=scenario
    )
    assert result["certified"], result["failures"]
