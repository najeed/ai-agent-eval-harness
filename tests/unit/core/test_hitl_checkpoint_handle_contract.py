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
