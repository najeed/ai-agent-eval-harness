from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataproc_engine.core.llm_manager import LLMManager


def test_llm_manager_initialization_defaults():
    """Cover default config logic (lines 20-33)."""
    manager = LLMManager({})
    assert manager.strategy == "auto"
    assert manager.preferred_provider == "gemini"


@pytest.mark.asyncio
async def test_llm_manager_cloud_provider_retry_logic():
    """Cover cloud call paths and provider selection (lines 196-217)."""
    # 1. Skip if no API key (lines 202-204)
    manager = LLMManager({"llm_provider": "openai"})
    with patch("os.getenv", return_value=None):
        res = await manager._try_cloud_providers("content", {})
        assert res is None

    # 2. Unknown provider (line 217)
    manager_unknown = LLMManager({"llm_provider": "unknown_box"})
    with patch("os.getenv", return_value="fake_key"):
        res = await manager_unknown._try_cloud_providers("content", {})
        assert res is None


@pytest.mark.asyncio
async def test_llm_manager_call_openai_success():
    """Cover OpenAI success path (lines 235-238)."""
    manager = LLMManager({"llm_provider": "openai"})
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "choices": [{"message": {"content": '{"key": "val"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value = mock_ctx

        res = await manager._call_openai("prompt", {}, "key")
        assert res == {"key": "val"}
        assert manager.estimated_cost_cents > 0


@pytest.mark.asyncio
async def test_llm_manager_call_claude_success():
    """Cover Claude success path (lines 288-291)."""
    manager = LLMManager({"llm_provider": "claude"})
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"content": [{"text": '{"key": "val"}'}]})
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value = mock_ctx

        res = await manager._call_claude("prompt", {}, "key")
        assert res == {"key": "val"}


@pytest.mark.asyncio
async def test_llm_manager_call_grok_success():
    """Cover Grok success path (lines 312-314)."""
    manager = LLMManager({"llm_provider": "grok"})
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"choices": [{"message": {"content": '{"key": "val"}'}}]}
        )
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value = mock_ctx

        res = await manager._call_grok("prompt", {}, "key")
        assert res == {"key": "val"}


@pytest.mark.asyncio
async def test_llm_manager_mock_unsupported_type():
    """Cover line 63 (unknown type in mock strategy)."""
    manager = LLMManager({"llm_strategy": "mock"})
    res = await manager.extract_structured_data("content", {"key": "unknown_type"})
    assert res["key"] is None


def test_llm_manager_verify_schema_inference():
    """Cover inference logic in verify_schema (lines 415-416)."""
    manager = LLMManager({})
    schema = {"revenue": "number"}
    # Should infer 'revenue' from 'total_revenue'
    res = manager._verify_schema({"total_revenue": 100.0}, schema)
    assert res["revenue"] == 100.0


def test_llm_manager_verify_schema_strict_inference_failure():
    """Cover strict failure after inference failed (lines 420-421)."""
    manager = LLMManager({})
    schema = {"missing_key": "string"}
    # Inference fails, and strict is True
    res = manager._verify_schema({"unrelated": "val"}, schema, strict=True)
    assert res is None


def test_llm_manager_verify_schema_default_types():
    """Cover default value population (lines 428-431)."""
    manager = LLMManager({})
    schema = {"cnt": "integer", "price": "number", "name": "string"}
    # Inference fails, strict is False
    res = manager._verify_schema({}, schema, strict=False)
    assert res["cnt"] == 0
    assert res["price"] == 0.0
    assert res["name"] == ""


@pytest.mark.asyncio
async def test_llm_manager_token_guard_hits():
    """Cover token guard interception (lines 464-475)."""
    manager = LLMManager({"llm_strategy": "auto"})
    # Content contains public domain
    await manager.extract_structured_data(
        "Visit sec.gov for details", {"k": "s"}, source_hint="test"
    )
    assert manager.strategy == "heuristic"
