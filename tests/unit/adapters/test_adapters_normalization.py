import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.common import DualNormalizationHub
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin


class MockResponse:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.parametrize(
    "text, expected_action",
    [
        ("The process is pending", "processing"),
        ("Manual review required (HITL)", "hitl_pause"),
        ("Critical system error occurred", "error"),
        ("Task completed successfully", "final_answer"),
        ("I have decided to deny the loan", "final_answer"),
        ("Just some random text", "final_answer"),
    ],
)
def test_normalization_hub_text_heuristics(text, expected_action):
    assert DualNormalizationHub.normalize_text(text) == expected_action


def test_normalization_hub_json_heuristics():
    res = DualNormalizationHub.normalize({"status": "pending"}, 200)
    assert res == "processing"

    res = DualNormalizationHub.normalize({"state": "hitl"}, 200)
    assert res == "hitl_pause"

    res = DualNormalizationHub.normalize({"outcome": "error"}, 200)
    assert res == "error"

    res = DualNormalizationHub.normalize({"status": "success"}, 500)
    assert res == "error"

    overrides = {"custom_done": "final_answer"}
    res = DualNormalizationHub.normalize({"status": "custom_done"}, 200, overrides=overrides)
    assert res == "final_answer"


@pytest.mark.asyncio
async def test_all_adapters_return_action_key():
    adapters = [
        (OpenAIAdapterPlugin(), "execute_openai_query", {"task": "test", "api_key": "sk-123"}),
        (ClaudeAdapterPlugin(), "execute_claude_query", {"task": "test", "api_key": "sk-123"}),
        (GrokAdapterPlugin(), "execute_grok_query", {"task": "test", "api_key": "sk-123"}),
        (OllamaAdapterPlugin(), "execute_ollama_query", {"task": "test"}),
    ]

    for plugin, method_name, payload in adapters:
        with patch("aiohttp.ClientSession.post") as mock_post:
            with patch("os.getenv", return_value="fake-key"):
                if isinstance(plugin, ClaudeAdapterPlugin):
                    json_data = {"content": [{"text": "ok"}]}
                elif isinstance(plugin, OllamaAdapterPlugin):
                    json_data = {"message": {"content": "ok"}}
                else:
                    json_data = {"choices": [{"message": {"content": "ok"}}]}

                mock_post.return_value = MockResponse(json_data=json_data)
                method = getattr(plugin, method_name)

                if isinstance(plugin, OpenAIAdapterPlugin):
                    res = await method(payload, base_url="http://test")
                else:
                    res = await method(payload, url="http://test")

                assert "action" in res
                if res["status"] == "success":
                    assert res["action"] == "final_answer"
                else:
                    assert res["action"] == "error"


@pytest.mark.asyncio
async def test_gemini_adapter_returns_action():
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.usage_metadata = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        res = await plugin.execute_gemini_query({"task": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"


@pytest.mark.asyncio
async def test_framework_adapters_return_action():
    plugin = LangChainAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "done"})
        res = await plugin.execute_langchain_query({"input": "hi", "url": "http://langserve"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"

    plugin = AutoGenAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "done"})
        res = await plugin.execute_autogen_query({"message": "hi", "url": "http://autogen"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"

    plugin = CrewAIAdapterPlugin()
    with patch.dict(sys.modules, {"crewai": MagicMock(__version__="1.0")}):
        res = await plugin.execute_crewai_task({"task_id": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"

    plugin = LangGraphAdapterPlugin()
    with patch.dict(sys.modules, {"langgraph": MagicMock(__version__="2.0")}):
        res = await plugin.execute_langgraph_node({"node_id": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"
