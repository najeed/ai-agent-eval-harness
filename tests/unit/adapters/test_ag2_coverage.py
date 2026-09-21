"""Current AG2 adapter dispatch and fail-closed contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.adapters.ag2 import AG2AdapterPlugin


@pytest.mark.asyncio
async def test_ag2_dispatches_explicit_a2a_endpoint() -> None:
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test-agent", "message": "hello", "url": "https://a2a.example"}

    with patch.object(adapter, "_execute_remote_a2a", new_callable=AsyncMock) as execute_remote:
        execute_remote.return_value = {"status": "success", "action": "final_answer"}
        result = await adapter.execute_ag2_query(payload)

    assert result["status"] == "success"
    assert execute_remote.call_args.kwargs["url"] == "https://a2a.example"
    assert execute_remote.call_args.kwargs["message"] == "hello"


@pytest.mark.asyncio
async def test_ag2_missing_sdk_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AG2AdapterPlugin()

    def missing_ag2() -> None:
        raise ImportError("missing")

    monkeypatch.setattr(adapter, "_import_ag2", missing_ag2)
    monkeypatch.setattr(config, "AG2_A2A_URL", None, raising=False)
    monkeypatch.setattr(config, "AG2_API_URL", None, raising=False)

    result = await adapter.execute_ag2_query({"message": "hello"})

    assert result["status"] == "error"
    assert "missing" in result["message"]


@pytest.mark.asyncio
async def test_ag2_native_agent_preserves_reply_continuity(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AG2AdapterPlugin()
    first_reply = SimpleNamespace(body="first response", events=[])
    second_reply = SimpleNamespace(body="second response", events=[])
    first_reply.ask = AsyncMock(return_value=second_reply)
    agent = SimpleNamespace(name="release-agent", ask=AsyncMock(return_value=first_reply))
    monkeypatch.setattr(adapter, "_import_ag2", lambda: SimpleNamespace(__version__="1.0.5"))
    monkeypatch.setattr(adapter, "_resolve_agent", AsyncMock(return_value=agent))
    monkeypatch.setattr(adapter, "_build_observer_stream", lambda _: None)
    monkeypatch.setattr(config, "AG2_A2A_URL", None, raising=False)
    monkeypatch.setattr(config, "AG2_API_URL", None, raising=False)
    monkeypatch.delenv("AG2_A2A_URL", raising=False)
    monkeypatch.delenv("AG2_API_URL", raising=False)

    first = await adapter.execute_ag2_query({"agent_id": "release", "message": "first"})
    second = await adapter.execute_ag2_query({"agent_id": "release", "message": "second"})

    assert first["status"] == "success"
    assert second["status"] == "success"
    agent.ask.assert_awaited_once_with("first")
    first_reply.ask.assert_awaited_once_with("second")


@pytest.mark.asyncio
async def test_ag2_rejects_empty_message_before_execution() -> None:
    with pytest.raises(ValueError, match="non-empty task/message"):
        await AG2AdapterPlugin().execute_ag2_query({"agent_id": "release"})


def test_ag2_registers_current_protocol() -> None:
    adapter = AG2AdapterPlugin()
    registry = MagicMock()

    adapter.on_discover_adapters(registry)

    registry.register.assert_called_once_with("ag2", adapter.execute_ag2_query)
