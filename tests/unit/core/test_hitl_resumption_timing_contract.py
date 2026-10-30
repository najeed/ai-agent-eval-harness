"""Resumed approval evidence preserves a nonnegative observed wait duration."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.events import CoreEvents
from eval_runner.session import SessionManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decided_at", "expected_ms"), [(0, 3000.0), (1002, 2000.0), (999, 3000.0)]
)
async def test_hitl_resumption_wait_uses_decision_time_only_when_available_and_ordered(
    decided_at, expected_ms
):
    approval = SimpleNamespace(
        status="APPROVED",
        metadata={"task_id": "transfer"},
        decision_reason="reviewed",
        created_at=1000,
        decided_at=decided_at,
    )
    session = SimpleNamespace(resumption_token="approved-token", event_bus=MagicMock())
    provider = SimpleNamespace(get_request=lambda token: approval)
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=provider),
        patch("eval_runner.session.time.time", return_value=1003),
    ):
        response = await SessionManager._handle_hitl(
            session, 1, {}, [], {}, SimpleNamespace(task_id="transfer")
        )

    assert response == "reviewed"
    name, evidence = session.event_bus.emit.call_args.args
    assert name == CoreEvents.HITL_RESUME
    assert evidence["wait_duration_ms"] == expected_ms
