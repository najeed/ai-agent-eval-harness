"""Provider-native certification and trust-boundary contracts.

These tests deliberately seed evidence through ``RunStorageProvider`` only.
The local implementation is a reference provider; its internal filesystem is
never read or used as an alternate certification authority.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state
from eval_runner.services.certification import (
    CertificationService,
    execute_industrial_certification,
    issue_certification,
)
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def provider(tmp_path, monkeypatch):
    """A local provider with explicitly provisioned certification identities."""
    root = tmp_path / "project"
    trust_root = root / ".aes" / "keys"
    trust_root.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)
    for identity in ("system_id", "eval_kernel"):
        IdentityService._provision_local_identity(identity)
    return LocalFileRunStore(tmp_path / "provider-runs")


def _seed_run(
    provider: LocalFileRunStore,
    run_id: str,
    *,
    outcome: str = "pass",
    mode: str = "live",
    append_finalization: bool = True,
    corrupt_finalization: bool = False,
    terminal_seq: int = 3,
    evidence_root_hash: str | None = None,
    required_oracles: list[str] | None = None,
    manifest_required_oracles: list[str] | None = None,
    finalization_required_oracles: list[str] | None = None,
    scenario_override: dict | None = None,
    agent_id: str | None = None,
    model: str | None = None,
):
    """Publish a complete provider-owned evidence stream for one run."""
    req_oracles = required_oracles if required_oracles is not None else ["oracle-1"]
    scenario = (
        scenario_override
        if scenario_override is not None
        else {
            "id": f"scenario-{run_id}",
            "version": "1.0.0",
            "required_oracles": req_oracles,
        }
    )
    scenario_hash = compute_scenario_hash(scenario)
    manifest_oracles = (
        manifest_required_oracles if manifest_required_oracles is not None else req_oracles
    )
    finalization_oracles = (
        finalization_required_oracles if finalization_required_oracles is not None else req_oracles
    )
    execution_manifest = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        metadata={"required_oracle_ids": manifest_oracles},
        runtime_config={"required_oracle_ids": manifest_oracles, "execution_mode": mode},
    )
    provider.create_run(run_id, scenario["id"])
    start_ev = {"event": "run_start", "_seq": 1, "execution_mode": mode}
    if agent_id:
        start_ev["agent_id"] = agent_id
    if model:
        start_ev["model"] = model
    events = [
        start_ev,
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "assertion_id": "assertion-1",
            "passed": outcome == "pass",
            "outcome": outcome.upper(),
            "resolver": "fixture",
        },
        {
            "event": "session_decision",
            "_seq": 3,
            "decision": outcome.upper(),
            "score": 1.0 if outcome == "pass" else 0.0,
        },
    ]
    provider.append_events(run_id, events)
    exact_lines = provider.get_trace_bytes(run_id).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(event, line) for event, line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=manifest_oracles,
    )
    effective_root = (
        evidence_root_hash if evidence_root_hash is not None else graph["evidence_root_hash"]
    )
    finalization = EvaluatorFinalizationRecord(
        finalization_id=f"finalization-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        execution_manifest_hash=execution_manifest.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:evaluator-config",
        evaluator_identity="eval_kernel",
        required_oracle_ids=finalization_oracles,
        evidence_root_hash=effective_root,
        outcome=outcome,
        score=1.0 if outcome == "pass" else 0.0,
        terminal_seq=terminal_seq,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    if corrupt_finalization:
        finalization = EvaluatorFinalizationRecord.from_dict(
            {**finalization.to_dict(), "score": 0.5}, require_authoritative=False
        )
    if append_finalization:
        provider.append_events(
            run_id,
            [{"event": "evaluator_finalization", "_seq": 4, "data": finalization.to_dict()}],
        )
    provider.save_run_manifest(
        run_id,
        {
            "run_id": run_id,
            "execution_manifest": execution_manifest.to_dict(),
            "scenario_data": scenario,
        },
    )
    return scenario


def test_certification_signs_provider_owned_exact_trace_bytes(provider):
    run_id = "provider-certification-pass"
    scenario = _seed_run(provider, run_id)

    result = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    manifest = provider.get_manifest(run_id)
    assert result["certified"] is True
    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.SEALED
    assert TraceVerifier.verify_trace(
        provider.get_trace_bytes(run_id), manifest, run_store=provider
    )


def test_failed_evaluation_is_attested_but_never_certified(provider):
    run_id = "provider-certification-fail"
    scenario = _seed_run(provider, run_id, outcome="fail")

    result = execute_industrial_certification(
        run_id,
        run_store=provider,
        scenario_data=scenario,
        status="pass",
        score=1.0,
    )

    assert result["status"] == "attested_failed"
    assert result["certified"] is False
    assert result["manifest"]["compliance"]["status"] == "fail"


def test_provisional_execution_fails_closed(provider):
    run_id = "provider-certification-provisional"
    scenario = _seed_run(provider, run_id, mode="simulated")

    with pytest.raises(ValueError, match="ProviderTruthLevelNotLive"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.OPEN


def test_missing_finalization_fails_closed(provider):
    run_id = "provider-certification-no-finalization"
    scenario = _seed_run(provider, run_id, append_finalization=False)

    with pytest.raises(ValueError, match="mandatory authoritative EvaluatorFinalizationRecord"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_invalid_finalization_signature_fails_closed(provider):
    run_id = "provider-certification-bad-finalization"
    scenario = _seed_run(provider, run_id, corrupt_finalization=True)

    with pytest.raises(ValueError, match="mandatory authoritative EvaluatorFinalizationRecord"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_terminal_sequence_mismatch_fails_closed(provider):
    run_id = "provider-certification-terminal-seq"
    scenario = _seed_run(provider, run_id, terminal_seq=1)

    with pytest.raises(ValueError, match="TerminalSequenceMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_sealed_retry_is_read_only_and_returns_published_certificate(provider, monkeypatch):
    run_id = "provider-certification-idempotent"
    scenario = _seed_run(provider, run_id)
    first = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    published = copy.deepcopy(provider.get_manifest(run_id))

    monkeypatch.setattr(
        TraceVerifier,
        "sign_trace_bytes",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("sealed run was re-signed")),
    )
    retry = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    assert first["package_hash"] == retry["package_hash"]
    assert provider.get_manifest(run_id) == published


def test_certification_never_uses_a_different_provider(provider, tmp_path):
    run_id = "provider-affinity"
    scenario = _seed_run(provider, run_id)
    other = LocalFileRunStore(tmp_path / "other-provider")
    other.create_run(run_id, scenario["id"])

    with pytest.raises(
        (ValueError, FileNotFoundError),
        match="ProviderOwnedEvidenceRequired|inconclusive|ExecutionManifestMissing",
    ):
        execute_industrial_certification(run_id, run_store=other, scenario_data=scenario)

    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.OPEN


def test_provider_event_and_exact_byte_divergence_fails_closed(provider, monkeypatch):
    run_id = "provider-byte-divergence"
    scenario = _seed_run(provider, run_id)
    original = provider.get_events(run_id, limit=10_000_000)
    monkeypatch.setattr(
        provider,
        "get_events",
        lambda *_args, **_kwargs: [*original, {"event": "forged", "_seq": 999}],
    )

    with pytest.raises(ValueError, match="ProviderEventByteDivergence"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_certification_rejects_path_evidence(provider, tmp_path):
    run_id = "provider-path-evidence-rejected"
    scenario = _seed_run(provider, run_id)

    with pytest.raises(ValueError, match="TracePathCertificationUnsupported"):
        execute_industrial_certification(
            run_id,
            run_store=provider,
            scenario_data=scenario,
            trace_path=tmp_path / "run.jsonl",
        )


def test_count_assertion_and_evidence_nodes_behaviors(tmp_path):
    assert (
        CertificationService.count_assertion_and_evidence_nodes(tmp_path / "nonexistent.jsonl") == 0
    )

    unreadable_dir = tmp_path / "as_dir"
    unreadable_dir.mkdir()
    assert CertificationService.count_assertion_and_evidence_nodes(unreadable_dir) == 0

    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("invalid json line\n", encoding="utf-8")
    assert CertificationService.count_assertion_and_evidence_nodes(bad_json) == 0

    non_dict = tmp_path / "non_dict.jsonl"
    non_dict.write_text("[1, 2, 3]\n", encoding="utf-8")
    assert CertificationService.count_assertion_and_evidence_nodes(non_dict) == 0

    valid_file = tmp_path / "valid.jsonl"
    valid_content = "\n".join(
        [
            "",
            json.dumps({"event": "step_executed"}),
            json.dumps({"event": "other", "assertion": "check_1"}),
            json.dumps({"event": "other", "data": {"assertion": "check_2"}}),
            json.dumps({"event": "other", "oracle_results": ["res"]}),
            json.dumps({"event": "other", "data": {"oracle_results": ["res2"]}}),
            json.dumps({"event": "other", "metrics": {"m": 1}}),
            json.dumps({"event": "other", "data": {"metrics": {"m": 2}}}),
            json.dumps({"event": "unrelated", "data": {"status": "ok"}}),
            "",
        ]
    )
    valid_file.write_text(valid_content, encoding="utf-8")
    assert CertificationService.count_assertion_and_evidence_nodes(valid_file) == 7


def test_parse_trace_strict_behaviors(tmp_path):
    with pytest.raises(FileNotFoundError, match="Trace file not found"):
        CertificationService.parse_trace_strict(tmp_path / "missing.jsonl")

    corrupt_file = tmp_path / "corrupt.jsonl"
    corrupt_file.write_text('{"event": "start"}\n{bad json}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="MalformedTraceRecord:2"):
        CertificationService.parse_trace_strict(corrupt_file)

    non_dict_file = tmp_path / "not_dict.jsonl"
    non_dict_file.write_text('{"event": "start"}\n"a string"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="InvalidTraceRecord:2"):
        CertificationService.parse_trace_strict(non_dict_file)

    foreign_file = tmp_path / "foreign.jsonl"
    foreign_file.write_text(
        json.dumps({"event": "run_start", "run_id": "run-expected"})
        + "\n"
        + json.dumps({"event": "step", "run_id": "run-foreign"})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ForeignTraceRecord:2"):
        CertificationService.parse_trace_strict(foreign_file, run_id="run-expected")

    valid_file = tmp_path / "valid_strict.jsonl"
    valid_file.write_text(
        "\n"
        + json.dumps({"event": "run_start", "run_id": "run-1"})
        + "\n"
        + json.dumps({"event": "step", "data": {"run_id": "run-1"}})
        + "\n",
        encoding="utf-8",
    )
    events = CertificationService.parse_trace_strict(valid_file, run_id="run-1")
    assert len(events) == 2


def test_extract_finalization_record_behaviors(provider, tmp_path, monkeypatch):
    assert CertificationService.extract_finalization_record(tmp_path / "missing.jsonl") is None

    unreadable_dir = tmp_path / "finalization_dir"
    unreadable_dir.mkdir()
    assert CertificationService.extract_finalization_record(unreadable_dir) is None

    no_fin_file = tmp_path / "no_fin.jsonl"
    no_fin_file.write_text(
        "\n{bad line}\n" + json.dumps({"event": "run_start"}) + "\n",
        encoding="utf-8",
    )
    assert CertificationService.extract_finalization_record(no_fin_file) is None

    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-test",
        run_id="run-test",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    untrusted_fin_file = tmp_path / "untrusted_fin.jsonl"
    untrusted_payload = {**fin.to_dict(), "evaluator_identity": "untrusted_actor"}
    untrusted_fin_file.write_text(
        json.dumps({"event": "evaluator_finalization", "data": untrusted_payload}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="EvaluatorIdentityUntrusted"):
        CertificationService.extract_finalization_record(untrusted_fin_file)

    lookup_err_file = tmp_path / "lookup_err.jsonl"
    lookup_err_file.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin.to_dict()}) + "\n",
        encoding="utf-8",
    )
    orig_pub = IdentityService.get_public_key
    monkeypatch.setattr(
        IdentityService,
        "get_public_key",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("KMS connection refused")),
    )
    with pytest.raises(ValueError, match="EvaluatorIdentityUntrusted"):
        CertificationService.extract_finalization_record(lookup_err_file)
    monkeypatch.setattr(IdentityService, "get_public_key", orig_pub)

    invalid_sig_file = tmp_path / "invalid_sig.jsonl"
    corrupt_fin = copy.deepcopy(fin.to_dict())
    corrupt_fin["evaluator_signature"] = "00" * 64
    invalid_sig_file.write_text(
        json.dumps({"event": "evaluator_finalization", "data": corrupt_fin}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="EvaluatorSignatureInvalid"):
        CertificationService.extract_finalization_record(invalid_sig_file)

    run_end_fin_file = tmp_path / "run_end_fin.jsonl"
    run_end_fin_file.write_text(
        json.dumps({"event": "run_end", "finalization": fin.to_dict()}) + "\n",
        encoding="utf-8",
    )
    extracted = CertificationService.extract_finalization_record(run_end_fin_file)
    assert extracted is not None
    assert extracted.finalization_id == "fin-test"

    run_end_data_fin_file = tmp_path / "run_end_data_fin.jsonl"
    run_end_data_fin_file.write_text(
        json.dumps({"event": "run_end", "data": {"finalization": fin.to_dict()}}) + "\n",
        encoding="utf-8",
    )
    extracted_data = CertificationService.extract_finalization_record(run_end_data_fin_file)
    assert extracted_data is not None
    assert extracted_data.finalization_id == "fin-test"


def test_materialize_provider_trace_behaviors(provider, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "canonical_runs")
    run_id = "materialize-test"
    provider.create_run(run_id, "scen-mat")

    with pytest.raises(ValueError, match="IncompleteProviderStream: no trace events"):
        CertificationService.materialize_provider_trace(run_id, provider)

    provider.append_events(run_id, [{"event": "node_executed", "_seq": 1}])
    with pytest.raises(ValueError, match="IncompleteProviderStream: missing start event"):
        CertificationService.materialize_provider_trace(run_id, provider)

    provider_2 = LocalFileRunStore(tmp_path / "provider_2")
    run_id_2 = "materialize-success"
    provider_2.create_run(run_id_2, "scen-mat-2")
    events_2 = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {"event": "run_end", "_seq": 2},
    ]
    provider_2.append_events(run_id_2, events_2)
    path, manifest = CertificationService.materialize_provider_trace(run_id_2, provider_2)
    assert path.is_file()
    assert path.name == "run.jsonl"

    cached_path, _ = CertificationService.materialize_provider_trace(run_id_2, provider_2)
    assert cached_path == path

    path.write_text(json.dumps({"event": "divergent", "_seq": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ProviderStreamDivergence"):
        CertificationService.materialize_provider_trace(run_id_2, provider_2)

    path.write_text("{bad json}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        CertificationService.materialize_provider_trace(run_id_2, provider_2)


def test_parse_trace_bytes_behaviors():
    with pytest.raises(ValueError, match="MalformedProviderTraceBytes"):
        CertificationService.parse_trace_bytes(b"\xff\xfe\x00\x00", "run-1")

    with pytest.raises(ValueError, match="MalformedTraceRecord:1"):
        CertificationService.parse_trace_bytes(b"{not json}\n", "run-1")

    with pytest.raises(ValueError, match="InvalidTraceRecord:1"):
        CertificationService.parse_trace_bytes(b'"just a string"\n', "run-1")

    with pytest.raises(ValueError, match="ForeignTraceRecord:1"):
        CertificationService.parse_trace_bytes(
            json.dumps({"event": "step", "run_id": "other"}).encode("utf-8"),
            "run-1",
        )

    with pytest.raises(ValueError, match="IncompleteProviderStream: no trace events"):
        CertificationService.parse_trace_bytes(b"\n   \n", "run-1")

    valid_bytes = (
        b"\n" + json.dumps({"event": "run_start", "run_id": "run-1"}).encode("utf-8") + b"\n"
    )
    evs = CertificationService.parse_trace_bytes(valid_bytes, "run-1")
    assert len(evs) == 1


def test_execution_truth_and_finalization_internal_helpers(provider):
    with pytest.raises(ValueError, match="IncompleteProviderStream: missing run_start event"):
        CertificationService._execution_truth([{"event": "step"}])

    mode, prov = CertificationService._execution_truth(
        [{"event": "start", "execution_mode": "hybrid", "provisional": False}]
    )
    assert mode == "hybrid"
    assert prov is True

    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-hlp",
        run_id="run-hlp",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    events_end_sub = [
        {"event": "run_start"},
        {"event": "run_end", "finalization": fin.to_dict()},
    ]
    res_fin = CertificationService._finalization(events_end_sub, "run-hlp")
    assert res_fin.finalization_id == "fin-hlp"

    events_untrusted = [
        {"event": "run_start"},
        {
            "event": "evaluator_finalization",
            "data": {**fin.to_dict(), "evaluator_identity": "unknown"},
        },
    ]
    with pytest.raises(ValueError, match="mandatory authoritative EvaluatorFinalizationRecord"):
        CertificationService._finalization(events_untrusted, "run-hlp")

    with pytest.raises(ValueError, match="FinalizationRunIdMismatch"):
        CertificationService._finalization(events_end_sub, "mismatched-run-id")


def test_read_run_truth_level_behaviors(provider, tmp_path, monkeypatch):
    assert CertificationService.read_run_truth_level("") == (None, False)
    assert CertificationService.read_run_truth_level("path/traversal") == (None, False)
    assert CertificationService.read_run_truth_level("..\\windows\\traversal") == (None, False)

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "truth_runs")
    assert CertificationService.read_run_truth_level("nonexistent") == (None, False)
    assert CertificationService.read_run_truth_level("nonexistent", run_store=provider) == (
        None,
        False,
    )

    vault = tmp_path / "truth_runs" / "run-on-disk"
    vault.mkdir(parents=True)
    assert CertificationService.read_run_truth_level("run-on-disk") == ("unknown", True)

    trace = vault / "run.jsonl"
    trace.write_text("\n{corrupt}\n", encoding="utf-8")
    assert CertificationService.read_run_truth_level("run-on-disk") == ("unknown", True)

    trace.write_text('"not a dict"\n', encoding="utf-8")
    assert CertificationService.read_run_truth_level("run-on-disk") == ("unknown", True)

    trace.write_text(json.dumps({"event": "step"}) + "\n", encoding="utf-8")
    assert CertificationService.read_run_truth_level("run-on-disk") == ("unknown", True)

    trace.write_text(
        json.dumps(
            {"event": "run_start", "data": {"execution_mode": "simulated", "provisional": True}}
        )
        + "\n",
        encoding="utf-8",
    )
    assert CertificationService.read_run_truth_level("run-on-disk") == ("simulated", True)

    trace.write_text(
        json.dumps({"event": "run_start", "data": {"execution_mode": "live", "provisional": False}})
        + "\n",
        encoding="utf-8",
    )
    assert CertificationService.read_run_truth_level("run-on-disk") == ("live", False)


def test_extract_computed_run_outcome_behaviors(tmp_path):
    assert CertificationService.extract_computed_run_outcome() == ("inconclusive", 0.0)

    vault = tmp_path / "outcome_vault"
    assert CertificationService.extract_computed_run_outcome(vault_dir=vault) == (
        "inconclusive",
        0.0,
    )

    vault.mkdir(parents=True)
    trace = vault / "run.jsonl"
    trace.write_text("\n   \n", encoding="utf-8")
    assert CertificationService.extract_computed_run_outcome(vault_dir=vault) == (
        "inconclusive",
        0.0,
    )

    trace.write_text("{bad line}\n", encoding="utf-8")
    assert CertificationService.extract_computed_run_outcome(vault_dir=vault) == (
        "inconclusive",
        0.0,
    )

    ev_post_fin = [
        {"event": "evaluator_finalization", "data": {"status": "pass"}},
        {"event": "post_event"},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_post_fin) == (
        "inconclusive",
        0.0,
    )

    ev_multi_fin = [
        {"event": "evaluator_finalization", "data": {"status": "pass"}},
        {"event": "evaluator_finalization", "data": {"status": "pass"}},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_multi_fin) == (
        "inconclusive",
        0.0,
    )

    ev_bad_fin_payload = [{"event": "evaluator_finalization", "data": "not a mapping"}]
    assert CertificationService.extract_computed_run_outcome(events=ev_bad_fin_payload) == (
        "inconclusive",
        0.0,
    )

    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-outcome",
        run_id="run-outcome",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    ev_fin_conflicting = [
        {"event": "evaluator_finalization", "data": fin.to_dict()},
        {"event": "session_decision", "data": {"status": "fail"}},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_fin_conflicting) == (
        "inconclusive",
        0.0,
    )

    ev_fin_ok = [{"event": "evaluator_finalization", "data": fin.to_dict()}]
    assert CertificationService.extract_computed_run_outcome(events=ev_fin_ok) == ("pass", 1.0)

    ev_eval_invalid = [{"event": "step", "status": "evaluation_invalid"}]
    assert CertificationService.extract_computed_run_outcome(events=ev_eval_invalid) == (
        "fail",
        0.0,
    )

    ev_multi_terminal = [
        {"event": "session_decision", "status": "pass"},
        {"event": "evaluation_result", "status": "pass"},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_multi_terminal) == (
        "inconclusive",
        0.0,
    )

    ev_term_invalid = [{"event": "session_decision", "data": {"status": "evaluation_invalid"}}]
    assert CertificationService.extract_computed_run_outcome(events=ev_term_invalid) == (
        "fail",
        0.0,
    )

    ev_term_policy_breach = [
        {"event": "session_decision", "data": {"status": "policy_breach", "score": 0.2}}
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_term_policy_breach) == (
        "fail",
        0.2,
    )

    ev_term_pass = [{"event": "session_decision", "data": {"status": "pass", "score": 0.95}}]
    assert CertificationService.extract_computed_run_outcome(events=ev_term_pass) == ("pass", 0.95)

    ev_term_fail_default = [{"event": "session_decision", "data": {"status": "fail"}}]
    assert CertificationService.extract_computed_run_outcome(events=ev_term_fail_default) == (
        "fail",
        0.0,
    )

    ev_empty_outcome = [{"event": "step_executed"}]
    assert CertificationService.extract_computed_run_outcome(events=ev_empty_outcome) == (
        "inconclusive",
        0.0,
    )


def test_execute_industrial_certification_boundary_and_validation_errors(provider, monkeypatch):
    with pytest.raises(ValueError, match="Invalid or unsafe run_id"):
        execute_industrial_certification("")
    with pytest.raises(ValueError, match="Invalid or unsafe run_id"):
        execute_industrial_certification("bad/run/id")

    with pytest.raises(FileNotFoundError, match="Run vault not found"):
        execute_industrial_certification("nonexistent-vault-run", run_store=provider)

    run_id_inv = "run-invalid-state"
    scenario = _seed_run(provider, run_id_inv)
    vault_dir = provider._get_run_vault(run_id_inv)
    monkeypatch.setattr(
        provider, "get_run", lambda *a, **k: {"run_id": run_id_inv, "status": "INVALID_STATE"}
    )
    with pytest.raises(ValueError, match="InvalidLifecycleState"):
        execute_industrial_certification(run_id_inv, run_store=provider, scenario_data=scenario)
    monkeypatch.undo()

    run_id_no_bytes = "run-no-bytes"
    scenario_no_b = _seed_run(provider, run_id_no_bytes)
    (vault_dir.parent / run_id_no_bytes / "run.jsonl").unlink()
    with pytest.raises(ValueError, match="ProviderOwnedEvidenceRequired"):
        execute_industrial_certification(
            run_id_no_bytes, run_store=provider, scenario_data=scenario_no_b
        )

    run_id_scope = "run-scope-violation"
    scen_scope = _seed_run(provider, run_id_scope)
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: {"run_id": "other-run-id"})
    with pytest.raises(ValueError, match="ProviderScopeViolation"):
        execute_industrial_certification(run_id_scope, run_store=provider, scenario_data=scen_scope)


def test_certification_convenience_wrappers(provider):
    run_id = "run-convenience-test"
    scenario = _seed_run(provider, run_id)
    res_top = issue_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res_top["certified"] is True
    assert res_top["status"] == "certified"

    res_cls = CertificationService.issue_certification(
        run_id, run_store=provider, scenario_data=scenario
    )
    assert res_cls["certified"] is True


def test_certification_assertion_targets_and_prohibitions(provider):
    run_id_map = "run-shim-mapping"
    scen_map = _seed_run(provider, run_id_map)
    provider.append_events(
        run_id_map,
        [{"event": "assertion_evaluated", "_seq": 99, "assertion": {"target": "shim:mock_db"}}],
    )
    with pytest.raises(ValueError, match="SimulatedStateEvidenceProhibited"):
        execute_industrial_certification(run_id_map, run_store=provider, scenario_data=scen_map)

    run_id_str = "run-shim-str"
    scen_str = _seed_run(provider, run_id_str)
    provider.append_events(
        run_id_str,
        [{"event": "assertion_evaluated", "_seq": 99, "assertion": "shim:virtual_vfs"}],
    )
    with pytest.raises(ValueError, match="SimulatedStateEvidenceProhibited"):
        execute_industrial_certification(run_id_str, run_store=provider, scenario_data=scen_str)


def test_certification_evidence_graph_and_provenance_validation(provider, monkeypatch):
    run_id_mismatch = "run-ev-root-mismatch"
    scen_mismatch = _seed_run(
        provider, run_id_mismatch, evidence_root_hash="sha3_256:mismatched_root"
    )
    with pytest.raises(ValueError, match="EvidenceRootMismatch"):
        execute_industrial_certification(
            run_id_mismatch, run_store=provider, scenario_data=scen_mismatch
        )

    run_id_empty = "run-decision-only"
    scenario = {
        "id": f"scenario-{run_id_empty}",
        "version": "1.0.0",
        "required_oracles": [],
    }
    scenario_hash = compute_scenario_hash(scenario)
    execution_manifest = ExecutionManifest(
        manifest_id=f"manifest-{run_id_empty}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        metadata={"required_oracle_ids": []},
        runtime_config={"required_oracle_ids": [], "execution_mode": "live"},
    )
    provider.create_run(run_id_empty, scenario["id"])
    provider.save_run_manifest(
        run_id_empty,
        {
            "run_id": run_id_empty,
            "execution_manifest": execution_manifest.to_dict(),
            "scenario_data": scenario,
        },
    )
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {"event": "session_decision", "_seq": 2, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_empty, events)
    exact_lines = provider.get_trace_bytes(run_id_empty).decode("utf-8").splitlines()
    raw_pairs = [(ev, line) for ev, line in zip(events, exact_lines, strict=True)]
    computed_graph = build_evidence_graph_from_events(raw_pairs, required_oracle_ids=[])
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_empty}",
        run_id=run_id_empty,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        execution_manifest_hash=execution_manifest.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=[],
        evidence_root_hash=computed_graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=2,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_empty,
        [{"event": "evaluator_finalization", "_seq": 3, "data": fin.to_dict()}],
    )
    with pytest.raises(ValueError, match="DecisionOnlyTrace"):
        execute_industrial_certification(run_id_empty, run_store=provider, scenario_data=scenario)


def test_certification_scenario_resolution_and_validation(provider, monkeypatch):
    run_id = "run-scen-res"
    _seed_run(provider, run_id)

    with pytest.raises(ValueError, match="ScenarioIdMismatch"):
        execute_industrial_certification(
            run_id,
            run_store=provider,
            scenario_data={"id": "mismatched-scenario-id", "version": "1.0.0"},
        )

    run_id_no_scen = "run-no-scen-arg"
    _seed_run(provider, run_id_no_scen)
    res = execute_industrial_certification(run_id_no_scen, run_store=provider, scenario_data=None)
    assert res["certified"] is True

    run_id_unres = "run-unresolvable-scen"
    _seed_run(provider, run_id_unres)
    man = provider.get_manifest(run_id_unres)
    orig_get_manifest = provider.get_manifest
    monkeypatch.setattr(
        provider,
        "get_manifest",
        lambda rid, *a, **k: (
            {
                "run_id": run_id_unres,
                "execution_manifest": man["execution_manifest"],
            }
            if rid == run_id_unres
            else orig_get_manifest(rid, *a, **k)
        ),
    )
    monkeypatch.setattr("eval_runner.loader.load_scenario", lambda *a, **k: None)
    with pytest.raises(ValueError, match="cannot resolve authoritative scenario definition"):
        execute_industrial_certification(run_id_unres, run_store=provider, scenario_data=None)

    run_id_bad_hash = "run-bad-scen-hash"
    bad_hash_scen = _seed_run(provider, run_id_bad_hash)
    bad_hash_scen = copy.deepcopy(bad_hash_scen)
    bad_hash_scen["description"] = "tampered scenario definition"
    with pytest.raises(ValueError, match="ScenarioHashMismatch"):
        execute_industrial_certification(
            run_id_bad_hash, run_store=provider, scenario_data=bad_hash_scen
        )


def test_certification_manifest_field_validation(provider, monkeypatch):
    run_id = "run-man-val"
    scenario = _seed_run(provider, run_id)
    man = provider.get_manifest(run_id)

    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: {"run_id": run_id})
    with pytest.raises(ValueError, match="ExecutionManifestMissing"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    monkeypatch.setattr(
        provider,
        "get_manifest",
        lambda *a, **k: {"run_id": run_id, "execution_manifest": {"scope": 12345}},
    )
    with pytest.raises(ValueError, match="Invalid provider execution manifest"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    scen_id_man = copy.deepcopy(man)
    scen_id_man["execution_manifest"]["scenario_id"] = "different-scen"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: scen_id_man)
    with pytest.raises(ValueError, match="ManifestScenarioIdMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    scen_ver_man = copy.deepcopy(man)
    scen_ver_man["execution_manifest"]["scenario_version"] = "9.9.9"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: scen_ver_man)
    with pytest.raises(ValueError, match="ManifestScenarioVersionMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    scen_h_man = copy.deepcopy(man)
    scen_h_man["execution_manifest"]["scenario_hash"] = "sha3_256:different"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: scen_h_man)
    with pytest.raises(ValueError, match="ManifestScenarioHashMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    mode_man = copy.deepcopy(man)
    mode_man["execution_manifest"]["runtime_config"]["execution_mode"] = "hybrid"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: mode_man)
    with pytest.raises(ValueError, match="ManifestExecutionModeMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    cfg_h_man = copy.deepcopy(man)
    cfg_h_man["execution_manifest"]["runtime_config"]["evaluator_config_hash"] = "sha3_256:bad"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: cfg_h_man)
    with pytest.raises(ValueError, match="ManifestEvaluatorConfigHashMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    man_mismatch = copy.deepcopy(man)
    man_mismatch["execution_manifest"]["manifest_id"] = "manifest-altered-id"
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: man_mismatch)
    with pytest.raises(ValueError, match="ManifestHashMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_certification_oracle_inventory_and_reconciliation(provider, monkeypatch):
    run_id = "run-oracle-inv"
    scenario = _seed_run(
        provider,
        run_id,
        manifest_required_oracles=["oracle-1"],
        finalization_required_oracles=["oracle-1", "oracle-extra"],
    )
    with pytest.raises(ValueError, match="ManifestRequiredOracleMismatch"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)

    run_id_req = "run-req-oracle-mismatch"
    scen_with_steps = {
        "id": f"scenario-{run_id_req}",
        "version": "1.0.0",
        "steps": [{"assertions": [{"oracle_id": "oracle-1"}, {"oracle_id": "oracle-extra"}]}],
    }
    scen_diff = _seed_run(
        provider,
        run_id_req,
        scenario_override=scen_with_steps,
        manifest_required_oracles=["oracle-1"],
        finalization_required_oracles=["oracle-1"],
    )
    with pytest.raises(ValueError, match="RequiredOracleInventoryMismatch"):
        execute_industrial_certification(run_id_req, run_store=provider, scenario_data=scen_diff)

    run_id_block = "run-blocking-mismatch"
    scen_block = _seed_run(provider, run_id_block, append_finalization=False)
    provider.append_events(
        run_id_block,
        [
            {
                "event": "assertion_evaluated",
                "_seq": 4,
                "assertion": "security_check",
                "passed": False,
            }
        ],
    )
    exact_lines = provider.get_trace_bytes(run_id_block).decode("utf-8").splitlines()
    all_events = provider.get_events(run_id_block)
    graph = build_evidence_graph_from_events(
        [(ev, line) for ev, line in zip(all_events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    manifest = provider.get_manifest(run_id_block)
    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"finalization-{run_id_block}",
        run_id=run_id_block,
        scenario_id=scen_block["id"],
        scenario_version=scen_block["version"],
        scenario_hash=compute_scenario_hash(scen_block),
        execution_manifest_hash=ExecutionManifest.from_dict(
            manifest["execution_manifest"]
        ).compute_manifest_hash(),
        evaluator_config_hash="sha3_256:evaluator-config",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=4,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_block,
        [{"event": "evaluator_finalization", "_seq": 5, "data": fin_rec.to_dict()}],
    )
    with pytest.raises(ValueError, match="BlockingAssertionOutcomeMismatch"):
        execute_industrial_certification(run_id_block, run_store=provider, scenario_data=scen_block)


def test_certification_commit_failure_and_sealed_state(provider, monkeypatch):
    run_id = "run-commit-fail"
    scenario = _seed_run(provider, run_id)
    orig_commit = provider.commit_certification
    monkeypatch.setattr(provider, "commit_certification", lambda *a, **k: False)
    with pytest.raises(
        RuntimeError, match="RunStorageProvider rejected atomic certification commit"
    ):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.OPEN
    monkeypatch.setattr(provider, "commit_certification", orig_commit)

    run_id_sealed = "run-sealed-invalid"
    scen_sealed = _seed_run(provider, run_id_sealed)
    execute_industrial_certification(run_id_sealed, run_store=provider, scenario_data=scen_sealed)
    monkeypatch.setattr(TraceVerifier, "verify_trace", lambda *a, **k: False)
    with pytest.raises(ValueError, match="SealedRunCertificateInvalid"):
        execute_industrial_certification(
            run_id_sealed, run_store=provider, scenario_data=scen_sealed
        )


def test_count_assertion_and_evidence_nodes_io_error(tmp_path, monkeypatch):
    test_file = tmp_path / "mock_io_error.jsonl"
    test_file.write_text("{}", encoding="utf-8")
    orig_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("Simulated read failure")),
    )
    assert CertificationService.count_assertion_and_evidence_nodes(test_file) == 0
    monkeypatch.setattr("builtins.open", orig_open)


def test_extract_finalization_record_edge_cases(provider, tmp_path, monkeypatch):
    test_file = tmp_path / "extract_edges.jsonl"
    test_file.write_text("{}", encoding="utf-8")
    orig_open = open
    monkeypatch.setattr(
        "builtins.open",
        lambda *a, **k: (_ for _ in ()).throw(OSError("Simulated read failure")),
    )
    assert CertificationService.extract_finalization_record(test_file) is None
    monkeypatch.setattr("builtins.open", orig_open)

    non_dict_trace = tmp_path / "non_dict_fin.jsonl"
    non_dict_trace.write_text('"not a dict"\n123\n', encoding="utf-8")
    assert CertificationService.extract_finalization_record(non_dict_trace) is None

    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-edges",
        run_id="run-edges",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    fin_no_id = copy.deepcopy(fin.to_dict())
    fin_no_id["evaluator_identity"] = ""
    run_end_top = tmp_path / "run_end_top.jsonl"
    run_end_top.write_text(
        json.dumps({"event": "run_end", "finalization": fin_no_id}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Missing mandatory finalization trust field"):
        CertificationService.extract_finalization_record(run_end_top)

    fin_val_err = tmp_path / "fin_val_err.jsonl"
    fin_val_err.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin.to_dict()}) + "\n",
        encoding="utf-8",
    )
    orig_from_dict = EvaluatorFinalizationRecord.from_dict
    monkeypatch.setattr(
        EvaluatorFinalizationRecord,
        "from_dict",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("GenericParseValueError")),
    )
    with pytest.raises(ValueError, match="GenericParseValueError"):
        CertificationService.extract_finalization_record(fin_val_err)

    monkeypatch.setattr(
        EvaluatorFinalizationRecord,
        "from_dict",
        lambda *a, **k: (_ for _ in ()).throw(TypeError("UnexpectedExceptionType")),
    )
    assert CertificationService.extract_finalization_record(fin_val_err) is None
    monkeypatch.setattr(EvaluatorFinalizationRecord, "from_dict", orig_from_dict)


def test_materialize_provider_trace_edge_cases(provider, tmp_path, monkeypatch):
    run_id = "mat-edges"
    provider.create_run(run_id, "scen-mat")
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {"event": "run_end", "_seq": 2},
    ]
    provider.append_events(run_id, events)
    canonical_dir = Path(config.RUN_LOG_DIR) / run_id
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_trace = canonical_dir / "run.jsonl"
    canonical_trace.write_text(
        json.dumps(events[0]) + "\n\n" + json.dumps(events[1]) + "\n",
        encoding="utf-8",
    )
    path, _ = CertificationService.materialize_provider_trace(run_id, provider)
    assert path == canonical_trace

    orig_open = open

    def mock_open_mat(p, *a, **k):
        if str(canonical_trace) in str(p):
            raise OSError("Read failure on canonical trace")
        return orig_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", mock_open_mat)
    with pytest.raises(ValueError, match="ProviderStreamDivergence: Read failure"):
        CertificationService.materialize_provider_trace(run_id, provider)
    monkeypatch.setattr("builtins.open", orig_open)


def test_finalization_helper_edge_cases(provider, monkeypatch):
    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-hlp-edges",
        run_id="run-hlp-edges",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    evs_top = [
        {"event": "run_start"},
        {"event": "run_end", "finalization": fin.to_dict()},
    ]
    res = CertificationService._finalization(evs_top, "run-hlp-edges")
    assert res.finalization_id == "fin-hlp-edges"

    fin_no_id = copy.deepcopy(fin.to_dict())
    fin_no_id["evaluator_identity"] = ""
    evs_no_id = [
        {"event": "run_start"},
        {"event": "evaluator_finalization", "data": fin_no_id},
    ]
    with pytest.raises(ValueError, match="mandatory authoritative EvaluatorFinalizationRecord"):
        CertificationService._finalization(evs_no_id, "run-hlp-edges")

    orig_pub = IdentityService.get_public_key
    monkeypatch.setattr(
        IdentityService,
        "get_public_key",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("KMS connection refused")),
    )
    with pytest.raises(ValueError, match="mandatory authoritative EvaluatorFinalizationRecord"):
        CertificationService._finalization(evs_top, "run-hlp-edges")
    monkeypatch.setattr(IdentityService, "get_public_key", orig_pub)

    orig_from_dict = EvaluatorFinalizationRecord.from_dict
    monkeypatch.setattr(
        EvaluatorFinalizationRecord,
        "from_dict",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("FinalizationRunIdMismatch")),
    )
    with pytest.raises(ValueError, match="FinalizationRunIdMismatch"):
        CertificationService._finalization(evs_top, "run-hlp-edges")
    monkeypatch.setattr(EvaluatorFinalizationRecord, "from_dict", orig_from_dict)


def test_read_run_truth_level_edge_cases(provider, tmp_path, monkeypatch):
    class ExplodingRunStore:
        def get_run(self, *a, **k):
            raise RuntimeError("Database error")

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "truth_runs_edges")
    assert CertificationService.read_run_truth_level(
        "run-db-err", run_store=ExplodingRunStore()
    ) == (None, False)

    vault = tmp_path / "truth_runs_edges" / "run-type-err"
    vault.mkdir(parents=True)
    trace = vault / "run.jsonl"
    trace.write_text("{}", encoding="utf-8")
    orig_open = open

    def mock_open_truth(p, *a, **k):
        if str(trace) in str(p):
            raise TypeError("Non-OS error during read")
        return orig_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", mock_open_truth)
    assert CertificationService.read_run_truth_level("run-type-err") == (None, False)
    monkeypatch.setattr("builtins.open", orig_open)


def test_extract_computed_run_outcome_edge_cases(provider, tmp_path, monkeypatch):
    trace_file = tmp_path / "direct_trace.jsonl"
    trace_file.write_text('{"event": "run_start"}\n"not_dict"\n', encoding="utf-8")
    assert CertificationService.extract_computed_run_outcome(target_trace=trace_file) == (
        "inconclusive",
        0.0,
    )

    orig_open = open

    def mock_open_fail(p, *a, **k):
        if str(trace_file) in str(p):
            raise OSError("Read failure")
        return orig_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", mock_open_fail)
    assert CertificationService.extract_computed_run_outcome(target_trace=trace_file) == (
        "inconclusive",
        0.0,
    )
    monkeypatch.setattr("builtins.open", orig_open)

    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-out-edges",
        run_id="run-out-edges",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    ev_multi = [
        {"event": "evaluator_finalization", "data": fin.to_dict()},
        {"event": "evaluator_finalization", "data": fin.to_dict()},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_multi) == (
        "inconclusive",
        0.0,
    )

    ev_bad_payload = [{"event": "run_end", "finalization": 12345}]
    assert CertificationService.extract_computed_run_outcome(events=ev_bad_payload) == (
        "inconclusive",
        0.0,
    )

    ev_conflict = [
        {"event": "evaluator_finalization", "data": fin.to_dict()},
        {"event": "session_decision", "data": {"status": "fail"}},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_conflict) == (
        "inconclusive",
        0.0,
    )

    ev_invalid_terminal = [{"event": "session_decision", "data": {"status": "evaluation_invalid"}}]
    assert CertificationService.extract_computed_run_outcome(events=ev_invalid_terminal) == (
        "fail",
        0.0,
    )


def test_execute_industrial_certification_unspecified_store_and_metadata(provider, monkeypatch):
    run_id = "run-unspec-store"
    scenario = _seed_run(provider, run_id, agent_id="agent-unit-007", model="gemini-2.5-pro")

    import eval_runner.runtime_services

    orig_resolve = eval_runner.runtime_services.resolve_run_store
    monkeypatch.setattr(eval_runner.runtime_services, "resolve_run_store", lambda: provider)
    res = execute_industrial_certification(run_id, scenario_data=scenario)
    assert res["certified"] is True
    assert res["manifest"]["metadata"]["agent_id"] == "agent-unit-007"
    assert res["manifest"]["metadata"]["model"] == "gemini-2.5-pro"
    monkeypatch.setattr(eval_runner.runtime_services, "resolve_run_store", orig_resolve)


def test_execute_industrial_certification_direct_provenance_and_oracle_reconciliation(
    provider, monkeypatch
):
    run_id = "run-prov-violation"
    scenario = _seed_run(provider, run_id)
    events = provider.get_events(run_id)
    fin_rec = next(e["data"] for e in events if e.get("event") == "evaluator_finalization")
    ev_root = fin_rec["evidence_root_hash"]

    import agentv_runtime.evidence_graph

    orig_build = agentv_runtime.evidence_graph.build_evidence_graph_from_events
    monkeypatch.setattr(
        agentv_runtime.evidence_graph,
        "build_evidence_graph_from_events",
        lambda *a, **k: {
            "evidence_root_hash": ev_root,
            "is_complete_provenance": False,
            "total_nodes": 5,
        },
    )
    with pytest.raises(ValueError, match="DirectProvenanceViolation"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    monkeypatch.setattr(
        agentv_runtime.evidence_graph, "build_evidence_graph_from_events", orig_build
    )

    run_id_unknown_field = "run-unknown-manifest-field"
    scen_unknown = _seed_run(provider, run_id_unknown_field)
    man = provider.get_manifest(run_id_unknown_field)
    bad_manifest = copy.deepcopy(man)
    bad_manifest["execution_manifest"]["unrecognized_field_xyz"] = True
    monkeypatch.setattr(provider, "get_manifest", lambda *a, **k: bad_manifest)
    with pytest.raises(ValueError, match="ExecutionManifestUnknownFields"):
        execute_industrial_certification(
            run_id_unknown_field, run_store=provider, scenario_data=scen_unknown
        )


def test_execute_industrial_certification_scenario_resolution_sources(provider, monkeypatch):
    run_id_data = "run-scen-data-field"
    scenario = {
        "id": f"scenario-{run_id_data}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scen_hash = compute_scenario_hash(scenario)
    execution_manifest = ExecutionManifest(
        manifest_id=f"manifest-{run_id_data}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id_data, scenario["id"])
    provider.save_run_manifest(
        run_id_data,
        {
            "run_id": run_id_data,
            "execution_manifest": execution_manifest.to_dict(),
        },
    )
    events = [
        {
            "event": "run_start",
            "_seq": 1,
            "execution_mode": "live",
            "data": {"scenario_data": scenario},
        },
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_data, events)
    exact_lines = provider.get_trace_bytes(run_id_data).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(ev, line) for ev, line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_data}",
        run_id=run_id_data,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=execution_manifest.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_data,
        [{"event": "evaluator_finalization", "_seq": 4, "data": fin.to_dict()}],
    )
    res = execute_industrial_certification(run_id_data, run_store=provider, scenario_data=None)
    assert res["certified"] is True

    run_id_loader = "run-scen-loader-list"
    scenario_loader = {
        "id": f"scenario-{run_id_loader}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scen_hash_l = compute_scenario_hash(scenario_loader)
    exec_man_l = ExecutionManifest(
        manifest_id=f"manifest-{run_id_loader}",
        scenario_id=scenario_loader["id"],
        scenario_version=scenario_loader["version"],
        scenario_hash=scen_hash_l,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id_loader, scenario_loader["id"])
    provider.save_run_manifest(
        run_id_loader,
        {
            "run_id": run_id_loader,
            "execution_manifest": exec_man_l.to_dict(),
        },
    )
    events_l = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_loader, events_l)
    exact_lines_l = provider.get_trace_bytes(run_id_loader).decode("utf-8").splitlines()
    graph_l = build_evidence_graph_from_events(
        [(ev, line) for ev, line in zip(events_l, exact_lines_l, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin_l = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_loader}",
        run_id=run_id_loader,
        scenario_id=scenario_loader["id"],
        scenario_version=scenario_loader["version"],
        scenario_hash=scen_hash_l,
        execution_manifest_hash=exec_man_l.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph_l["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_loader,
        [{"event": "evaluator_finalization", "_seq": 4, "data": fin_l.to_dict()}],
    )
    monkeypatch.setattr("eval_runner.loader.load_scenario", lambda *a, **k: [scenario_loader])
    res_l = execute_industrial_certification(run_id_loader, run_store=provider, scenario_data=None)
    assert res_l["certified"] is True


def test_execute_industrial_certification_missing_required_oracles(provider):
    run_id = "run-missing-oracles"
    scenario = {
        "id": f"scenario-{run_id}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1", "oracle-unexecuted"],
    }
    scen_hash = compute_scenario_hash(scenario)
    exec_man = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1", "oracle-unexecuted"]},
        runtime_config={
            "required_oracle_ids": ["oracle-1", "oracle-unexecuted"],
            "execution_mode": "live",
        },
    )
    provider.create_run(run_id, scenario["id"])
    provider.save_run_manifest(
        run_id,
        {
            "run_id": run_id,
            "execution_manifest": exec_man.to_dict(),
            "scenario_data": scenario,
        },
    )
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id, events)
    exact_lines = provider.get_trace_bytes(run_id).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(ev, line) for ev, line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1", "oracle-unexecuted"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1", "oracle-unexecuted"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id,
        [{"event": "evaluator_finalization", "_seq": 4, "data": fin.to_dict()}],
    )
    with pytest.raises(ValueError, match="MissingRequiredOracles"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_execute_industrial_certification_oracle_result_formats(provider):
    run_id = "run-oracle-formats"
    scenario = {
        "id": f"scenario-{run_id}",
        "version": "1.0.0",
        "required_oracles": ["o-res", "m-res", "a-res"],
    }
    scen_hash = compute_scenario_hash(scenario)
    exec_man = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["o-res", "m-res", "a-res"]},
        runtime_config={
            "required_oracle_ids": ["o-res", "m-res", "a-res"],
            "execution_mode": "live",
        },
    )
    provider.create_run(run_id, scenario["id"])
    provider.save_run_manifest(
        run_id,
        {
            "run_id": run_id,
            "execution_manifest": exec_man.to_dict(),
            "scenario_data": scenario,
        },
    )
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "o-res",
            "passed": True,
            "outcome": "PASS",
            "data": {
                "oracle_results": [{"oracle_id": "o-res"}],
                "executed_oracle_results": [{"metric": "m-res"}, {"assertion": "a-res"}],
            },
        },
        {
            "event": "oracle_result",
            "_seq": 3,
            "metric": "m-res",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "oracle_result",
            "_seq": 4,
            "assertion": "a-res",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 5, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id, events)
    exact_lines = provider.get_trace_bytes(run_id).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(ev, line) for ev, line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["o-res", "m-res", "a-res"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o-res", "m-res", "a-res"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=5,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id,
        [{"event": "evaluator_finalization", "_seq": 6, "data": fin.to_dict()}],
    )
    res = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res["certified"] is True


def test_finalization_split_data_and_ev_mappings(provider, tmp_path):
    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-split",
        run_id="run-split",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    evs_split = [
        {"event": "run_start"},
        {"event": "run_end", "data": {"duration": 10}, "finalization": fin.to_dict()},
    ]
    res_split = CertificationService._finalization(evs_split, "run-split")
    assert res_split.finalization_id == "fin-split"

    evs_no_fin_in_end = [
        {"event": "run_start"},
        {"event": "run_end", "data": {"duration": 10}},
    ]
    with pytest.raises(
        ValueError, match="missing mandatory authoritative EvaluatorFinalizationRecord"
    ):
        CertificationService._finalization(evs_no_fin_in_end, "run-no-fin")

    run_end_none = tmp_path / "run_end_none.jsonl"
    run_end_none.write_text(
        json.dumps({"event": "run_end", "data": {"duration": 10}}) + "\n",
        encoding="utf-8",
    )
    assert CertificationService.extract_finalization_record(run_end_none) is None


def test_extract_computed_run_outcome_terminal_and_run_end_variations(provider):
    IdentityService._provision_local_identity("eval_kernel")
    fin = EvaluatorFinalizationRecord(
        finalization_id="fin-run-end-var",
        run_id="run-var",
        scenario_id="scen-1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        execution_manifest_hash="sha3_256:dummy",
        evaluator_config_hash="sha3_256:dummy",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:dummy",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    ev_data = [{"event": "run_end", "data": {"finalization": fin.to_dict()}}]
    assert CertificationService.extract_computed_run_outcome(events=ev_data) == ("pass", 1.0)

    ev_top = [{"event": "run_end", "finalization": fin.to_dict()}]
    assert CertificationService.extract_computed_run_outcome(events=ev_top) == ("pass", 1.0)

    ev_conflict_preceding = [
        {"event": "session_decision", "data": {"status": "fail"}},
        {"event": "evaluator_finalization", "data": fin.to_dict()},
    ]
    assert CertificationService.extract_computed_run_outcome(events=ev_conflict_preceding) == (
        "inconclusive",
        0.0,
    )


def test_execute_industrial_certification_post_finalization_noise(provider):
    run_id = "run-post-fin-noise"
    scenario = _seed_run(provider, run_id)
    provider.append_events(run_id, [{"event": "post_noise", "_seq": 99}])
    with pytest.raises(ValueError, match="has inconclusive outcome"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_execute_industrial_certification_terminal_seq_zero(provider):
    run_id = "run-terminal-seq-zero"
    scenario = _seed_run(provider, run_id, terminal_seq=0)
    res = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res["certified"] is True


def test_execute_industrial_certification_scenario_in_event_root(provider):
    run_id = "run-scen-ev-root"
    scenario = {
        "id": f"scenario-{run_id}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scen_hash = compute_scenario_hash(scenario)
    exec_man = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id, scenario["id"])
    provider.save_run_manifest(run_id, {"run_id": run_id, "execution_manifest": exec_man.to_dict()})
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live", "scenario_data": scenario},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id, events)
    exact_lines = provider.get_trace_bytes(run_id).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(ev, raw_line) for ev, raw_line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id, [{"event": "evaluator_finalization", "_seq": 4, "data": fin.to_dict()}]
    )
    res = execute_industrial_certification(run_id, run_store=provider, scenario_data=None)
    assert res["certified"] is True


def test_execute_industrial_certification_loader_mapping_and_exception(provider, monkeypatch):
    run_id_map = "run-scen-loader-map"
    scenario = {
        "id": f"scenario-{run_id_map}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scen_hash = compute_scenario_hash(scenario)
    exec_man = ExecutionManifest(
        manifest_id=f"manifest-{run_id_map}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id_map, scenario["id"])
    provider.save_run_manifest(
        run_id_map, {"run_id": run_id_map, "execution_manifest": exec_man.to_dict()}
    )
    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_map, events)
    exact_lines = provider.get_trace_bytes(run_id_map).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(ev, raw_line) for ev, raw_line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_map}",
        run_id=run_id_map,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_map, [{"event": "evaluator_finalization", "_seq": 4, "data": fin.to_dict()}]
    )

    monkeypatch.setattr("eval_runner.loader.load_scenario", lambda *a, **k: scenario)
    res = execute_industrial_certification(run_id_map, run_store=provider, scenario_data=None)
    assert res["certified"] is True

    run_id_list = "run-scen-loader-list"
    exec_man_list = ExecutionManifest(
        manifest_id=f"manifest-{run_id_list}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id_list, scenario["id"])
    provider.save_run_manifest(
        run_id_list, {"run_id": run_id_list, "execution_manifest": exec_man_list.to_dict()}
    )
    events_list = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_list, events_list)
    exact_lines_list = provider.get_trace_bytes(run_id_list).decode("utf-8").splitlines()
    graph_list = build_evidence_graph_from_events(
        [(ev, raw_line) for ev, raw_line in zip(events_list, exact_lines_list, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin_list = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_list}",
        run_id=run_id_list,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man_list.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph_list["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_list, [{"event": "evaluator_finalization", "_seq": 4, "data": fin_list.to_dict()}]
    )
    monkeypatch.setattr("eval_runner.loader.load_scenario", lambda *a, **k: [scenario])
    res_list = execute_industrial_certification(run_id_list, run_store=provider, scenario_data=None)
    assert res_list["certified"] is True

    run_id_fail = "run-scen-loader-fail"
    exec_man_fail = ExecutionManifest(
        manifest_id=f"manifest-{run_id_fail}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id_fail, scenario["id"])
    provider.save_run_manifest(
        run_id_fail, {"run_id": run_id_fail, "execution_manifest": exec_man_fail.to_dict()}
    )
    events_fail = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {"event": "session_decision", "_seq": 3, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id_fail, events_fail)
    exact_lines_fail = provider.get_trace_bytes(run_id_fail).decode("utf-8").splitlines()
    graph_fail = build_evidence_graph_from_events(
        [(ev, raw_line) for ev, raw_line in zip(events_fail, exact_lines_fail, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin_fail = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id_fail}",
        run_id=run_id_fail,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man_fail.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph_fail["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id_fail, [{"event": "evaluator_finalization", "_seq": 4, "data": fin_fail.to_dict()}]
    )

    monkeypatch.setattr(
        "eval_runner.loader.load_scenario",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Loader failure")),
    )
    with pytest.raises(ValueError, match="cannot resolve authoritative scenario definition"):
        execute_industrial_certification(run_id_fail, run_store=provider, scenario_data=None)


def test_execute_industrial_certification_extended_trace_and_oracle_edge_cases(provider):
    run_id = "run-trace-oracle-edges"
    scenario = {
        "id": "scenario-trace-oracle-edges",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scen_hash = compute_scenario_hash(scenario)
    exec_man = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"required_oracle_ids": ["oracle-1"], "execution_mode": "live"},
    )
    provider.create_run(run_id, scenario["id"])
    provider.save_run_manifest(run_id, {"run_id": run_id, "execution_manifest": exec_man.to_dict()})

    events = [
        {"event": "run_start", "_seq": 1, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "step",
            "_seq": 3,
            "data": {"oracle_results": [123, {}]},
        },
        {
            "event": "oracle_result",
            "_seq": 4,
            "data": {},
        },
        {"event": "session_decision", "_seq": 5, "decision": "PASS", "score": 1.0},
    ]
    provider.append_events(run_id, events)

    # Insert empty lines into trace file on disk to test whitespace line filtering
    trace_path = provider._resolve_trace_file(run_id)
    with open(trace_path, "a", encoding="utf-8") as f:
        f.write("\n   \n\n")

    exact_lines = [
        line_item
        for line_item in provider.get_trace_bytes(run_id).decode("utf-8").splitlines()
        if line_item.strip()
    ]
    graph = build_evidence_graph_from_events(
        [(ev, raw_line) for ev, raw_line in zip(events, exact_lines, strict=True)],
        required_oracle_ids=["oracle-1"],
    )
    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scen_hash,
        execution_manifest_hash=exec_man.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:cfg",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=5,
        finalized_at="2026-10-24T00:00:00Z",
    ).sign()

    provider.append_events(
        run_id, [{"event": "evaluator_finalization", "_seq": 6, "data": fin.to_dict()}]
    )

    res = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res["certified"] is True


def test_execute_industrial_certification_sealed_state_exception_branch(provider, monkeypatch):
    run_id = "run-sealed-ex-branch"
    scenario = _seed_run(provider, run_id)
    orig_commit = provider.commit_certification

    def commit_then_raise(*a, **k):
        orig_commit(*a, **k)
        raise RuntimeError("Post-commit failure")

    monkeypatch.setattr(provider, "commit_certification", commit_then_raise)
    with pytest.raises(RuntimeError, match="Post-commit failure"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.SEALED
    monkeypatch.setattr(provider, "commit_certification", orig_commit)


def test_certification_provider_contract_suite(provider, monkeypatch):
    """Provider contract suite for certification guarantees.

    Verifies:
    1. provider==verified==signed==package byte equality across boundaries.
    2. Sealed retry: idempotent return without re-certifying or mutating.
    3. No-unseal: appending events to a sealed run raises PermissionError (WORM retention).
    4. Pre-seal rollback: failure before commit rolls lifecycle state back to OPEN.
    """
    import hashlib

    # 1. Byte Equality & Authoritative Certification
    run_id = "contract-byte-equality-run"
    scenario = _seed_run(provider, run_id, outcome="pass", mode="live")

    provider_trace_bytes = provider.get_trace_bytes(run_id)
    assert provider_trace_bytes is not None
    assert len(provider_trace_bytes) > 0

    res = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res["certified"] is True
    manifest = res["manifest"]
    pkg = res["verification_package"]

    # Byte equality checks:
    expected_hash = hashlib.sha3_256(provider_trace_bytes).hexdigest()
    assert manifest["trace_hash"] == expected_hash
    assert pkg["trace_hash"] == expected_hash
    assert pkg["trace_seal"]["trace_digest"] == expected_hash

    assert (
        TraceVerifier.verify_trace(
            provider_trace_bytes,
            manifest,
            run_store=provider,
            scenario_data=scenario,
        )
        is True
    )

    from eval_runner.verifier import VerificationAuthority

    events = [
        json.loads(line)
        for line in provider_trace_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    pkg_verif = VerificationAuthority.verify_package_artifacts(
        package=pkg,
        raw_trace_bytes=provider_trace_bytes,
        raw_trace_events=events,
        canonical_manifest=manifest.get("execution_manifest") or manifest,
        scenario_data=scenario,
    )
    assert pkg_verif["verified"] is True
    assert pkg_verif["failures"] == []

    # 2. Sealed Retry (Idempotence)
    assert get_run_lifecycle_state(run_id, run_store=provider) is RunLifecycleState.SEALED
    res_retry = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    assert res_retry["certified"] is True
    assert res_retry["manifest"]["trace_hash"] == manifest["trace_hash"]
    assert res_retry["package_hash"] == res["package_hash"]

    # 3. No-Unseal: Appending events to a sealed run raises PermissionError
    with pytest.raises(PermissionError):
        provider.append_events(run_id, [{"event": "tamper_attempt", "_seq": 999}])

    # 4. Pre-Seal Rollback
    rollback_run_id = "contract-rollback-run"
    rb_scenario = _seed_run(provider, rollback_run_id, outcome="pass", mode="live")
    assert get_run_lifecycle_state(rollback_run_id, run_store=provider) is RunLifecycleState.OPEN

    def aborting_commit(*a, **k):
        raise RuntimeError("Simulated pre-commit error")

    monkeypatch.setattr(provider, "commit_certification", aborting_commit)
    with pytest.raises(RuntimeError, match="Simulated pre-commit error"):
        execute_industrial_certification(
            rollback_run_id, run_store=provider, scenario_data=rb_scenario
        )

    # Lifecycle state must be rolled back to OPEN
    assert get_run_lifecycle_state(rollback_run_id, run_store=provider) is RunLifecycleState.OPEN
