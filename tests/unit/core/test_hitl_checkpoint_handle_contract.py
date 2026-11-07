"""Approval suspension distinguishes missing checkpoint handles from usable snapshots."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from eval_runner.context import TurnContext
from eval_runner.run_lifecycle import RunSuspendedForApproval
from tests.unit.core.test_core_session import _session_with_local_providers


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_id", [None, "", "checkpoint-present"])
async def test_durable_approval_suspends_with_optional_checkpoint_handle(
    tmp_path, monkeypatch, checkpoint_id
):
    session = _session_with_local_providers(tmp_path, "checkpoint-handle", {"id": "scenario"})
    session.event_bus = MagicMock()
    request = SimpleNamespace(approval_token="pending-token", checkpoint_id=checkpoint_id)
    monkeypatch.setattr(
        session.approval_manager, "create_durable_request", lambda **kwargs: request
    )
    checkpoint = {"turn": 1}
    load = MagicMock(
        return_value=checkpoint,
        side_effect=None
        if checkpoint_id
        else AssertionError("missing checkpoint must not be read"),
    )
    monkeypatch.setattr(session.checkpoint_manager, "load_checkpoint", load)

    with pytest.raises(RunSuspendedForApproval) as suspended:
        await session._handle_hitl(
            1,
            {"gate_type": "scenario_declared", "prompt": "Approve transfer"},
            [],
            {},
            TurnContext("transfer", 1, "", ()),
        )

    assert suspended.value.approval_token == "pending-token"
    assert suspended.value.checkpoint == (checkpoint if checkpoint_id else {})
    assert session.run_store.get_run(session.run_id)["lifecycle"] == "PAUSED_FOR_APPROVAL"


@pytest.mark.asyncio
async def test_raise_if_pending_durable_approval_empty_checkpoint_id(tmp_path, monkeypatch):
    """Empty string checkpoint_id must not invoke load_checkpoint."""
    session = _session_with_local_providers(tmp_path, "empty-chk-handle", {"id": "scenario"})
    session.event_bus = MagicMock()
    req = SimpleNamespace(
        approval_token="tok-1",
        checkpoint_id="",
        prompt="Review",
        turn_index=1,
        metadata={"task_id": "t1"},
        action_payload={},
    )
    monkeypatch.setattr(session.approval_manager, "list_durable_pending", lambda: [req])
    load_mock = MagicMock(side_effect=AssertionError("empty checkpoint_id must not be loaded"))
    monkeypatch.setattr(session.checkpoint_manager, "load_checkpoint", load_mock)

    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await session._raise_if_pending_durable_approval()
    assert exc_info.value.approval_token == "tok-1"
    load_mock.assert_not_called()


@pytest.mark.asyncio
async def test_handle_hitl_resumption_token_metadata_and_decision_variants(tmp_path, monkeypatch):
    """Tests resumption token task_id matching, empty task_id, and decision fallbacks."""
    session = _session_with_local_providers(tmp_path, "resump-variants", {"id": "scenario"})
    session.event_bus = MagicMock()
    session.resumption_token = "tok-approved"
    monkeypatch.setenv("CI", "true")
    session.approval_manager.wait_for_durable_resolution = MagicMock(
        side_effect=AssertionError(
            "wait_for_durable_resolution must not be invoked during resumption tests"
        )
    )

    # 1. Request has no task_id in metadata (None) -> matches any task
    req_no_task = SimpleNamespace(
        status="APPROVED",
        decision_reason="",
        decision="DECISION_OVERRIDE",
        metadata=None,
        created_at=100.0,
        decided_at=105.0,
    )
    mock_store = MagicMock()
    mock_store.get_request.return_value = req_no_task
    monkeypatch.setattr("eval_runner.runtime_services.resolve_approval_store", lambda: mock_store)

    res = await session._handle_hitl(
        1,
        {"prompt": "Authorize"},
        [],
        {},
        TurnContext("random_task", 1, "", ()),
    )
    assert res == "DECISION_OVERRIDE"

    # Decision_reason="" and decision="" defaults to "APPROVED"
    req_default_appr = SimpleNamespace(
        status="APPROVED",
        decision_reason="",
        decision="",
        metadata=None,
        created_at=100.0,
        decided_at=105.0,
    )
    mock_store.get_request.return_value = req_default_appr
    res_default = await session._handle_hitl(
        1,
        {"prompt": "Authorize"},
        [],
        {},
        TurnContext("random_task", 1, "", ()),
    )
    assert res_default == "APPROVED"

    # 2. Request has status="REJECTED" -> must not resolve via resumption branch
    req_rejected = SimpleNamespace(
        status="REJECTED",
        decision_reason="Denied",
        decision="REJECTED",
        metadata={"task_id": "random_task"},
        created_at=100.0,
        decided_at=105.0,
    )
    mock_store.get_request.return_value = req_rejected
    monkeypatch.setenv("CI", "true")
    res_rejected = await session._handle_hitl(
        1,
        {"prompt": "Authorize"},
        [],
        {},
        TurnContext("random_task", 1, "", ()),
    )
    assert "[HITL_UNRESOLVED]" in res_rejected


@pytest.mark.asyncio
async def test_handle_hitl_ci_mode_and_env_suspension_guards(tmp_path, monkeypatch):
    """Tests CI unresolved path vs scenario gate and env suspensions."""
    session = _session_with_local_providers(tmp_path, "ci-guards", {"id": "scenario"})
    session.event_bus = MagicMock()
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.delenv("FORCE_HITL_SUSPEND", raising=False)
    session.approval_manager.wait_for_durable_resolution = MagicMock(
        side_effect=AssertionError(
            "wait_for_durable_resolution must not be invoked during CI guard tests"
        )
    )

    # 1. Non-scenario gate in CI without suspension env -> produces [HITL_UNRESOLVED]
    res = await session._handle_hitl(
        1,
        {"prompt": "Needs human approval"},
        [],
        {},
        TurnContext("t1", 1, "", ()),
    )
    assert "[HITL_UNRESOLVED]" in res
    assert session._hitl_unresolved is True

    # 2. Scenario gate in CI -> raises RunSuspendedForApproval even in CI
    monkeypatch.setattr(
        session.approval_manager,
        "create_durable_request",
        lambda **kw: SimpleNamespace(approval_token="tok-gate", checkpoint_id="chk-1"),
    )
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"gate_type": "scenario_declared", "prompt": "Needs human approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    # 3. FORCE_HITL_SUSPEND=1 without AGENTV_CLI_HITL_SUSPEND in CI suspends
    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.setattr(
        session.approval_manager,
        "create_durable_request",
        lambda **kw: SimpleNamespace(approval_token="tok-force", checkpoint_id="chk-force"),
    )
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"prompt": "Needs human approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )


@pytest.mark.asyncio
async def test_handle_hitl_non_durable_test_mode_and_tty_guards(tmp_path, monkeypatch):
    """Tests AGENTV_TEST_NON_DURABLE_HITL, resolution status, and isatty guards."""

    session = _session_with_local_providers(tmp_path, "non-durable-mode", {"id": "scenario"})
    session.event_bus = MagicMock()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.delenv("FORCE_HITL_SUSPEND", raising=False)
    monkeypatch.setenv("AGENTV_TEST_NON_DURABLE_HITL", "1")

    # With AGENTV_TEST_NON_DURABLE_HITL=1 and non-tty, it does not durable-suspend;
    # it awaits wait_for_durable_resolution
    req = SimpleNamespace(
        approval_token="tok-nondurable",
        checkpoint_id="chk-nd",
        created_at=100.0,
        timeout_seconds=5,
    )
    monkeypatch.setattr(session.approval_manager, "create_durable_request", lambda **kw: req)
    monkeypatch.setattr(session.checkpoint_manager, "create_checkpoint", MagicMock())
    resolved = SimpleNamespace(status="APPROVED", decision_reason="Test approved")

    async def fake_wait(*args, **kwargs):
        return resolved

    monkeypatch.setattr(session.approval_manager, "wait_for_durable_resolution", fake_wait)

    res = await session._handle_hitl(
        1,
        {"prompt": "Needs approval"},
        [],
        {},
        TurnContext("t1", 1, "", ()),
    )
    assert res == "Test approved"

    # Status != APPROVED (e.g. PENDING or REJECTED) raises InterruptedError
    pending_res = SimpleNamespace(status="PENDING", decision_reason="Awaiting review")

    async def fake_pending_wait(*args, **kwargs):
        return pending_res

    monkeypatch.setattr(session.approval_manager, "wait_for_durable_resolution", fake_pending_wait)
    with pytest.raises(InterruptedError, match="Human reviewer rejected"):
        await session._handle_hitl(
            1,
            {"prompt": "Needs approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    # 2. With AGENTV_TEST_NON_DURABLE_HITL unset and non-tty, must durably-suspend
    monkeypatch.delenv("AGENTV_TEST_NON_DURABLE_HITL", raising=False)
    req_durable = SimpleNamespace(approval_token="tok-395", checkpoint_id="chk-395")
    monkeypatch.setattr(
        session.approval_manager, "create_durable_request", lambda **kw: req_durable
    )
    with pytest.raises(RunSuspendedForApproval) as exc_395:
        await session._handle_hitl(
            1,
            {"prompt": "Needs approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )
    assert exc_395.value.approval_token == "tok-395"


@pytest.mark.asyncio
async def test_handle_hitl_tty_interactive_and_env_guards(tmp_path, monkeypatch):
    """Tests interactive stdin guard logic when isatty is True."""
    import sys

    session = _session_with_local_providers(tmp_path, "tty-guards", {"id": "scenario"})
    session.event_bus = MagicMock()

    # Simulate interactive TTY
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.delenv("FORCE_HITL_SUSPEND", raising=False)

    # 1. Scenario gate overrides isatty -> suspends instead of reading stdin
    monkeypatch.setattr(
        session.approval_manager,
        "create_durable_request",
        lambda **kw: SimpleNamespace(approval_token="tok-tty-gate", checkpoint_id="chk-gate"),
    )
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"gate_type": "scenario_declared", "prompt": "Gate prompt"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    # 2. AGENTV_CLI_HITL_SUSPEND=1 overrides isatty -> suspends
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    monkeypatch.delenv("FORCE_HITL_SUSPEND", raising=False)
    monkeypatch.setattr(
        session.approval_manager,
        "create_durable_request",
        lambda **kw: SimpleNamespace(approval_token="tok-tty-cli", checkpoint_id="chk-cli"),
    )
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"prompt": "Non-gate prompt"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    # 3. FORCE_HITL_SUSPEND=1 overrides isatty -> suspends
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.setattr(
        session.approval_manager,
        "create_durable_request",
        lambda **kw: SimpleNamespace(approval_token="tok-tty-force", checkpoint_id="chk-force"),
    )
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"prompt": "Non-gate prompt"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    # 4. Truly interactive (no env vars, no gate) -> reads from stdin input()
    monkeypatch.delenv("AGENTV_CLI_HITL_SUSPEND", raising=False)
    monkeypatch.delenv("FORCE_HITL_SUSPEND", raising=False)
    monkeypatch.setattr("builtins.input", lambda: "User input response")
    res = await session._handle_hitl(
        1,
        {"prompt": "Interactive prompt"},
        [],
        {},
        TurnContext("t1", 1, "", ()),
    )
    assert res == "User input response"


@pytest.mark.asyncio
async def test_handle_hitl_correlation_id_inheritance(tmp_path, monkeypatch):
    """Inherits scenario correlation_id or preserves metadata."""
    session = _session_with_local_providers(
        tmp_path, "corr-inherit", {"id": "scenario", "correlation_id": "scen-corr-val-123"}
    )
    session.event_bus = MagicMock()
    captured_metadata = {}

    def capture_request(**kwargs):
        captured_metadata.update(kwargs.get("metadata", {}))
        return SimpleNamespace(approval_token="tok-corr", checkpoint_id="chk-corr")

    monkeypatch.setattr(session.approval_manager, "create_durable_request", capture_request)
    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")

    # Case 1: metadata has no correlation_id -> inherits from scenario
    with pytest.raises(RunSuspendedForApproval):
        await session._handle_hitl(
            1,
            {"prompt": "Needs approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )

    assert captured_metadata.get("correlation_id") == "scen-corr-val-123"

    # Session metadata has correlation_id -> must NOT be overridden by scenario
    session_with_meta = _session_with_local_providers(
        tmp_path, "corr-meta", {"id": "scenario", "correlation_id": "scen-corr-other"}
    )
    session_with_meta.metadata["correlation_id"] = "meta-p0-override"
    session_with_meta.event_bus = MagicMock()
    captured_override = {}

    def capture_override(**kwargs):
        captured_override.update(kwargs.get("metadata", {}))
        return SimpleNamespace(approval_token="tok-override", checkpoint_id="chk-override")

    monkeypatch.setattr(
        session_with_meta.approval_manager, "create_durable_request", capture_override
    )
    with pytest.raises(RunSuspendedForApproval):
        await session_with_meta._handle_hitl(
            1,
            {"prompt": "Needs approval"},
            [],
            {},
            TurnContext("t1", 1, "", ()),
        )
    assert captured_override.get("correlation_id") == "meta-p0-override"


def test_save_and_restore_from_checkpoint_contract(tmp_path):
    """Direct contract test for save_checkpoint and restore_from_checkpoint."""
    session = _session_with_local_providers(tmp_path, "save-restore-run", {"id": "scenario"})
    session.turn_number = 3
    session.metadata["custom_key"] = "custom_val"

    # save_checkpoint
    ckpt_id = session.save_checkpoint(checkpoint_id="ckpt_1", metadata={"custom_meta": 123})
    assert ckpt_id is not None

    # restore_from_checkpoint with None data when no latest checkpoint exists -> False
    session.checkpoint_manager.load_latest_checkpoint = MagicMock(return_value=None)
    assert session.restore_from_checkpoint() is False

    # restore_from_checkpoint with explicit data
    chk_data = {
        **session._execution_checkpoint_state(),
        "turn": 5,
        "metadata": {"restored_meta": 789},
        "session_metadata": {"extra": 101},
        "completed_execution_results": {"node_1": {"status": "ok"}},
        "approval_token": "tok_auto_restore",
    }
    assert session.restore_from_checkpoint(chk_data) is True
    assert session.turn_number == 5
    assert session.session_metadata["restored_meta"] == 789
    assert session.session_metadata["extra"] == 101
    assert session._completed_execution_results == {"node_1": {"status": "ok"}}
    assert session.resumption_token == "tok_auto_restore"

    # restore_from_checkpoint with explicit resumption_token override
    session.restore_from_checkpoint(chk_data, resumption_token="explicit_token")
    assert session.resumption_token == "explicit_token"

    # Turn_state_manager=None does not attempt restore
    session.turn_state_manager = None
    assert session.restore_from_checkpoint(chk_data) is True

    # Minimal checkpoint without optional dict fields restores without KeyError
    minimal_chk = {"turn": 1}
    assert session.restore_from_checkpoint(minimal_chk) is True


@pytest.mark.asyncio
async def test_verify_state_parity_delegation(tmp_path):
    """Direct contract test for _verify_state_parity delegation."""

    session = _session_with_local_providers(tmp_path, "parity-run", {"id": "scenario"})
    mock_verifier = MagicMock()

    async def fake_parity(*args, **kwargs):
        return (True, [{"transition": 1}])

    mock_verifier.verify_state_parity = fake_parity
    session.state_parity_verifier = mock_verifier

    passed, evidence = await session._verify_state_parity(
        {"id": "node_1"}, MagicMock(), [], state_before={}, external_state_before={}
    )
    assert passed is True
    assert evidence == [{"transition": 1}]
