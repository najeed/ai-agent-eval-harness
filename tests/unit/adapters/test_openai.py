from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.openai import OpenAIAdapterPlugin


@pytest.mark.asyncio
async def test_openai_adapter_telemetry():
    """Verify that OpenAI adapter emits token usage telemetry."""
    adapter = OpenAIAdapterPlugin()
    payload = {"task": "test task", "model": "gpt-test"}

    mock_response_data = {
        "choices": [{"message": {"content": "Hello world"}}],
        "usage": {"total_tokens": 100, "prompt_tokens": 40, "completion_tokens": 60},
    }

    # Mock SessionManager and response at source
    with patch(
        "eval_runner.adapters.common.SessionManager.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_session = MagicMock()  # Use MagicMock for context manager support
        mock_get_session.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session.post.return_value = mock_resp

        with patch("eval_runner.adapters.openai.emit") as mock_emit:
            result = await adapter.execute_openai_query(payload)

            assert result["status"] == "success"
            assert result["output"] == "Hello world"

            # Verify telemetry emission
            mock_emit.assert_any_call(
                "metric_update",
                {"adapter": "openai", "tokens": 100, "prompt_tokens": 40, "completion_tokens": 60},
            )


@pytest.mark.asyncio
async def test_openai_adapter_error_handling():
    """Verify that OpenAI adapter handles and reports errors correctly."""
    adapter = OpenAIAdapterPlugin()
    payload = {"task": "test task"}

    with patch(
        "eval_runner.adapters.common.SessionManager.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Simulate a 401 Unauthorized (should not retry)
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")

        request_info = MagicMock()
        request_info.real_url = "http://test"
        mock_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info, (), status=401
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session.post.return_value = mock_resp

        result = await adapter.execute_openai_query(payload)

        assert result["status"] == "error"
        assert "401" in result["message"]
        # Since it's a 401, call_with_retry should have called post only once
        assert mock_session.post.call_count == 1
