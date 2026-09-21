"""OpenAPI normalization and current polling contracts."""

from unittest.mock import AsyncMock

import pytest

from eval_runner.adapters.common import DualNormalizationHub
from eval_runner.adapters.openapi import OpenAPIAdapterPlugin, OpenAPIResolutionError


def test_normalization_hub_invalid_action(caplog: pytest.LogCaptureFixture) -> None:
    result = DualNormalizationHub.normalize(
        {"status": "STATUS_X"}, 200, overrides={"STATUS_X": "invalid_action"}
    )

    assert "Ignoring invalid adapter override action 'invalid_action'" in caplog.text
    assert result == "final_answer"


def test_normalization_hub_semantic_status_fields() -> None:
    overrides = {"STALLED": "hitl_pause"}

    assert (
        DualNormalizationHub.normalize({"state": "STALLED"}, 200, overrides=overrides)
        == "hitl_pause"
    )
    assert (
        DualNormalizationHub.normalize({"result": "stalled"}, 200, overrides=overrides)
        == "hitl_pause"
    )
    assert (
        DualNormalizationHub.normalize({"custom_status_field": "review_required"}, 200)
        == "hitl_pause"
    )
    assert DualNormalizationHub.normalize({"status": "crash_detected"}, 200) == "error"


@pytest.mark.asyncio
async def test_openapi_executes_when_spec_discovery_is_unavailable() -> None:
    adapter = OpenAPIAdapterPlugin()
    adapter._fetch_document = AsyncMock(side_effect=OpenAPIResolutionError("missing spec"))
    adapter._request = AsyncMock(return_value=({"status": "done"}, 200, {}, ""))

    result = await adapter.execute_openapi_query(
        {"input_payload": {"key": "value"}}, endpoint="http://api.example.com/run"
    )

    assert result["action"] == "final_answer"
    assert adapter._request.call_args.kwargs["url"] == "http://api.example.com/run"


@pytest.mark.asyncio
async def test_openapi_polling_returns_terminal_result() -> None:
    adapter = OpenAPIAdapterPlugin()
    adapter._request = AsyncMock(return_value=({"status": "approved"}, 200, {}, ""))

    result = await adapter._poll_for_result("http://api.example.com/poll", None, {})

    assert result["action"] == "final_answer"
    assert result["metadata"]["attempts"] == 1


@pytest.mark.asyncio
async def test_openapi_polling_times_out_after_configured_attempts() -> None:
    adapter = OpenAPIAdapterPlugin()
    adapter.max_poll_attempts = 3
    adapter.poll_interval = 0
    adapter._request = AsyncMock(return_value=({"status": "processing"}, 200, {}, ""))

    result = await adapter._poll_for_result("http://api.example.com/poll", None, {})

    assert result["action"] == "error"
    assert "Polling timeout exceeded" in result["content"]
