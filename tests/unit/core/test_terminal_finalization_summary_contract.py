"""Terminal diagnostics cannot replace the graph committed before finalization."""

import pytest

from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("nested", [False, True])
def test_terminal_summary_preserves_pre_finalization_evidence(
    finalization_source, tmp_path, nested
):
    source, scenario = finalization_source
    events = source.get_events("run-a", offset=0, limit=100)
    finalization = events[-1]["data"]
    payload = {
        "finalization": finalization,
        "assertions": [{"oracle_id": "terminal-note", "passed": True, "severity": "informational"}],
    }
    terminal = {"event": "run_end", "_seq": 4}
    if nested:
        terminal["data"] = payload
    else:
        terminal.update(payload)
    provider = LocalFileRunStore(tmp_path / "terminal-provider")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", [*events[:-1], terminal])
    provider.save_run_manifest("run-a", source.get_manifest("run-a"))

    issued = execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)

    assert issued["certified"] is True
    assert TraceVerifier.verify_run("run-a", run_store=provider)["verified"] is True
    manifest = provider.get_manifest("run-a")
    diagnostic = VerificationAuthority.verify_package(
        manifest["verification_package"],
        raw_trace_bytes=provider.get_trace_bytes("run-a"),
        canonical_manifest=manifest["execution_manifest"],
        scenario_data=scenario,
        require_signature=False,
    )
    assert diagnostic["verified"], diagnostic["failures"]
    assert diagnostic["certified"] is False
    assert diagnostic["authoritative"] is False
