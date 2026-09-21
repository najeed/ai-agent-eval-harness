from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.openai import OpenAIAdapterPlugin


@pytest.mark.asyncio
async def test_openai_adapter_telemetry():
    """Verify that OpenAI adapter emits token usage telemetry."""
    adapter = OpenAIAdapterPlugin()
    payload = {
        "api_key": "test",
        "task": "test task",
        "model": "gpt-test",
        "api_mode": "chat_completions",
    }

    mock_response_data = {
        "choices": [{"message": {"content": "Hello world"}}],
        "usage": {"total_tokens": 100, "prompt_tokens": 40, "completion_tokens": 60},
    }

    with patch.object(
        adapter,
        "_post_json",
        new_callable=AsyncMock,
        return_value=(mock_response_data, {}),
    ):
        with patch("eval_runner.adapters.openai.emit") as mock_emit:
            result = await adapter.execute_openai_query(payload)

            assert result["status"] == "success"
            assert result["output"] == "Hello world"

            # Verify telemetry emission
            mock_emit.assert_any_call(
                "metric_update",
                {
                    "adapter": "openai",
                    "provider": "openai",
                    "tokens": 100,
                    "prompt_tokens": 40,
                    "completion_tokens": 60,
                },
            )


@pytest.mark.asyncio
async def test_openai_adapter_error_handling():
    """Verify that OpenAI adapter handles and reports errors correctly."""
    adapter = OpenAIAdapterPlugin()
    payload = {"api_key": "test", "task": "test task", "api_mode": "chat_completions"}

    with patch.object(adapter, "_post_json", new_callable=AsyncMock) as post_json:
        post_json.side_effect = aiohttp.ClientResponseError(MagicMock(), (), status=401)
        result = await adapter.execute_openai_query(payload)

        assert result["status"] == "error"
        assert "401" in result["message"]
        assert post_json.await_count == 1
