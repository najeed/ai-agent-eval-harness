"""Provider-native tests for :mod:`eval_runner.services.run_summary`."""

from unittest.mock import MagicMock, patch

from eval_runner.services.run_summary import RunSummaryService


def _store(*, run=None, manifest=None, events=None, trace=b'{"event":"run_end"}\n'):
    provider = MagicMock()
    provider.get_run.return_value = run
    provider.get_manifest.return_value = manifest
    provider.get_events.return_value = events or []
    provider.get_trace_bytes.return_value = trace
    return provider


def test_verdict_is_not_executed_when_provider_has_no_run_or_trace():
    provider = _store(run=None, trace=None)
    assert (
        RunSummaryService.get_authoritative_verdict("missing", run_store=provider) == "NOT_EXECUTED"
    )


def test_verdict_uses_provider_owned_bytes_and_manifest():
    provider = _store(
        run={"run_id": "run-1"},
        manifest={
            "trace_hash": "hash",
            "signature": "signature",
            "execution_mode": "live",
            "compliance_status": "pass",
        },
        events=[{"event": "run_start", "data": {"execution_mode": "live"}}],
    )
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes", return_value=True
    ) as verify:
        assert (
            RunSummaryService.get_authoritative_verdict("run-1", run_store=provider) == "VERIFIED"
        )
    verify.assert_called_once_with(
        b'{"event":"run_end"}\n',
        provider.get_manifest.return_value,
        run_store=provider,
        context=None,
        trace_only=False,
    )


def test_summary_uses_provider_events_without_trace_path_recovery():
    provider = _store(
        run={"run_id": "run-1", "scenario_id": "scenario", "status": "COMPLETED"},
        manifest={"execution_mode": "live", "score": 1.0},
        events=[
            {
                "event": "run_start",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": {"execution_mode": "live"},
            },
            {"event": "run_end", "data": {"outcome": "PASS"}},
        ],
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("run-1", run_store=provider)
    assert summary["status"] == "PASSED"
    assert summary["trace_integrity"] == "COMPLETE"
    assert summary["scenario"] == "scenario"


def test_terminal_state_edge_cases():
    # 1. No terminal event
    assert RunSummaryService._terminal_state([]) == ("RUNNING", "RUNNING", "PARTIAL")

    # 2. certification_failed
    assert RunSummaryService._terminal_state([{"event": "certification_failed"}]) == (
        "FAILED",
        "FAILED",
        "COMPLETE",
    )

    # 3. Outcome / decision variants
    assert RunSummaryService._terminal_state(
        [{"event": "session_decision", "outcome": "SUCCESS"}]
    ) == (
        "PASSED",
        "COMPLETED",
        "COMPLETE",
    )
    assert RunSummaryService._terminal_state(
        [{"event": "workflow_verdict", "verdict": "ERROR"}]
    ) == (
        "FAILED",
        "FAILED",
        "COMPLETE",
    )

    # 4. run_end with no recognized outcome -> ("PASSED", "COMPLETED", "PARTIAL")
    assert RunSummaryService._terminal_state(
        [{"event": "run_end", "data": {"status": "OTHER"}}]
    ) == (
        "PASSED",
        "COMPLETED",
        "PARTIAL",
    )

    # 5. Non-run_end terminal event with unrecognized outcome -> ("INVALID", "INVALID", "INVALID")
    assert RunSummaryService._terminal_state(
        [{"event": "workflow_verdict", "data": {"verdict": "UNKNOWN"}}]
    ) == (
        "INVALID",
        "INVALID",
        "INVALID",
    )


def test_truth_level_hierarchies():
    # 1. Nested execution_manifest metadata/runtime_config
    manifest = {
        "execution_manifest": {
            "runtime_config": {"execution_mode": "hybrid"},
            "metadata": {"execution_mode": "live"},
        },
        "provisional": True,
    }
    mode, provisional = RunSummaryService._truth_level([], manifest)
    assert mode == "hybrid"
    assert provisional is True

    # 2. Non-dict execution_manifest and metadata
    manifest_invalid = {
        "execution_manifest": "not-a-dict",
    }
    mode, provisional = RunSummaryService._truth_level([], manifest_invalid)
    assert mode == "unknown"
    assert provisional is True

    # 3. Events iteration with other events before run_start
    events = [
        {"event": "some_other_event"},
        {
            "event": "run_start",
            "data": {"execution_mode": "live", "metadata": {"provisional": False}},
            "metadata": {},
        },
    ]
    mode, provisional = RunSummaryService._truth_level(events, {})
    assert mode == "live"
    assert provisional is False


def test_get_authoritative_verdict_all_branches():
    # 1. Empty run_id
    assert RunSummaryService.get_authoritative_verdict("", run_store=MagicMock()) == "NOT_EXECUTED"

    # 2. Missing manifest or trace_bytes
    provider = _store(run={"run_id": "r1"}, manifest=None, trace=None)
    assert RunSummaryService.get_authoritative_verdict("r1", run_store=provider) == "UNKNOWN"

    provider = _store(run={"run_id": "r1"}, manifest={"a": 1}, trace=None)
    assert (
        RunSummaryService.get_authoritative_verdict("r1", run_store=provider)
        == "FAILED_VERIFICATION"
    )

    # 3. TraceVerifier returns False
    provider = _store(run={"run_id": "r1"}, manifest={"a": 1}, trace=b"data")
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes", return_value=False
    ):
        assert (
            RunSummaryService.get_authoritative_verdict("r1", run_store=provider)
            == "FAILED_VERIFICATION"
        )

    # 4. TraceVerifier raises Exception
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes",
        side_effect=RuntimeError("Cryptographic error"),
    ):
        assert (
            RunSummaryService.get_authoritative_verdict("r1", run_store=provider)
            == "FAILED_VERIFICATION"
        )

    # 5. Verified provisional (simulated or provisional flag)
    provider = _store(
        run={"run_id": "r1"},
        manifest={"execution_mode": "simulated", "status": "passed"},
        trace=b"data",
    )
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes", return_value=True
    ):
        assert (
            RunSummaryService.get_authoritative_verdict("r1", run_store=provider)
            == "FAILED_VERIFICATION"
        )

    # 6. Attested fail
    provider = _store(
        run={"run_id": "r1"},
        manifest={
            "execution_mode": "live",
            "certification": {"outcome": "FAILED"},
        },
        trace=b"data",
    )
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes", return_value=True
    ):
        assert (
            RunSummaryService.get_authoritative_verdict("r1", run_store=provider) == "ATTESTED_FAIL"
        )


def test_compute_summary_all_verdicts_scores_and_fallbacks():
    # 1. run is None
    provider = _store(run=None)
    provider.get_run.return_value = None
    summary = RunSummaryService.compute_summary("missing-run", run_store=provider)
    assert summary["status"] == "NOT_EXECUTED"

    # 2. VERIFIED verdict -> status="CERTIFIED", lifecycle="SEALED"
    provider = _store(
        run={"run_id": "r-cert"},
        manifest={"execution_mode": "live", "score": None},
        events=[{"event": "run_end", "data": {"passed": True}}],
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="VERIFIED"):
        summary = RunSummaryService.compute_summary("r-cert", run_store=provider)
    assert summary["status"] == "CERTIFIED"
    assert summary["lifecycle"] == "SEALED"
    assert summary["score"] == 1.0

    # 3. VERIFIED_PROVISIONAL verdict -> status="PROVISIONAL"
    with patch.object(
        RunSummaryService, "get_authoritative_verdict", return_value="VERIFIED_PROVISIONAL"
    ):
        summary = RunSummaryService.compute_summary("r-cert", run_store=provider)
    assert summary["status"] == "PROVISIONAL"
    assert summary["lifecycle"] == "SEALED"

    # 4. ATTESTED_FAIL verdict -> status="ATTESTED_FAIL"
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="ATTESTED_FAIL"):
        summary = RunSummaryService.compute_summary("r-cert", run_store=provider)
    assert summary["status"] == "ATTESTED_FAIL"
    assert summary["lifecycle"] == "SEALED"

    # 5. Empty events -> status = lifecycle = run.get("status")
    provider = _store(run={"run_id": "r-empty", "status": "PAUSED"}, events=[])
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("r-empty", run_store=provider)
    assert summary["status"] == "PAUSED"
    assert summary["score"] is None

    # 6. Failed run with default score 0.0
    provider = _store(
        run={"run_id": "r-fail"},
        manifest={},
        events=[{"event": "run_end", "data": {"passed": False}}],
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("r-fail", run_store=provider)
    assert summary["status"] == "FAILED"
    assert summary["score"] == 0.0

    # 7. Failed oracles and root cause events (with message and without message)
    provider = _store(
        run={"run_id": "r-oracles"},
        manifest={
            "verification_package": {
                "executed_oracle_results": [
                    {"oracle_id": "o1", "outcome": "FAIL"},
                    {"oracle_id": "o2", "passed": True},
                ]
            }
        },
        events=[
            {"event": "run_start", "_ts_iso": "2026-02-01T00:00:00Z"},
            {"event": "error_event", "is_root_cause": True, "error": "Disk failure"},
            {
                "event": "empty_root_cause",
                "is_root_cause": True,
            },  # branch 226->217: message is empty
        ],
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("r-oracles", run_store=provider)
    assert summary["score_category"] == "ORACLE_DEFECT"
    assert "Oracle 'o1' failed." in summary["failure_reasons"]
    assert "Root cause: Disk failure" in summary["failure_reasons"]
    assert summary["timestamp"] == "2026-02-01T00:00:00Z"

    # 8. Non-dict runtime_config and metadata in execution_manifest (lines 70, 73)
    manifest_non_dict_children = {
        "execution_manifest": {
            "runtime_config": "not-a-dict",
            "metadata": 123,
        }
    }
    mode, prov = RunSummaryService._truth_level([], manifest_non_dict_children)
    assert mode == "unknown"
    assert prov is True

    # 8. Manifest fallback chains for scenario, identifier, target, model, agent
    provider = _store(
        run={"run_id": "r-fallbacks"},
        manifest={
            "trace_hash": "thash",
            "signature": "sig",
            "execution_manifest": {
                "scenario_id": "sc-nested",
                "agent_config": {
                    "agent_id": "ag-id-1",
                    "agent_name": "ag-name-1",
                    "configured_model_id": "m-id-1",
                    "model": "m-1",
                },
            },
        },
        events=[{"event": "run_start", "data": {"timestamp": "2026-03-01T10:00:00Z"}}],
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("r-fallbacks", run_store=provider)
    assert summary["scenario"] == "sc-nested"
    assert summary["identifier"] == "ag-id-1"
    assert summary["target"] == "m-id-1"
    assert summary["model"] == "m-id-1"
    assert summary["agent"] == "ag-name-1"
    assert summary["has_certificate"] is True
