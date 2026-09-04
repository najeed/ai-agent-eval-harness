"""
Unit test suite for Centralized LLM Error Classifier & Resilience Layer.

Verifies:
1. Error classification against status codes, string heuristics, and SDK error shapes.
2. Distinction between retriable burst rate limits (429) vs non-retriable hard quota depletion.
3. Resilient retry execution with exponential backoff, retry budget exhaustion, and fail-fast.
4. Seamless integration with GeminiProvider and OpenAIProvider.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.llm_providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMProviderFactory,
    OllamaProvider,
    OpenAIProvider,
)
from eval_runner.llm_resilience import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMQuotaExceededError,
    LLMRateLimitError,
    LLMTransientError,
    classify_llm_error,
    execute_with_resilience,
    extract_retry_after,
)

# =====================================================================
# 1. Error Classification Unit Tests
# =====================================================================


def test_classify_passthrough():
    err = LLMRateLimitError("already typed", provider="test_prov", status_code=429)
    res = classify_llm_error(err)
    assert res is err
    assert res.provider == "test_prov"


def test_extract_retry_after():
    assert extract_retry_after("Rate limit reached. Please retry after 15.5s.") == 15.5
    assert extract_retry_after("RESOURCE_EXHAUSTED: wait 3 seconds before next request") == 3.0
    assert extract_retry_after("No delay specified") is None


def test_classify_authentication_errors():
    e1 = Exception("401 Unauthorized: Invalid API key provided.")
    res1 = classify_llm_error(e1, provider="openai")
    assert isinstance(res1, LLMAuthenticationError)
    assert res1.status_code == 401

    e2 = Exception("Google API key missing.")
    res2 = classify_llm_error(e2, provider="gemini")
    assert isinstance(res2, LLMAuthenticationError)

    e3 = MagicMock(spec=Exception, code=403, __str__=lambda self: "PERMISSION_DENIED")
    res3 = classify_llm_error(e3, provider="gemini")
    assert isinstance(res3, LLMAuthenticationError)
    assert res3.status_code == 403


def test_classify_hard_quota_vs_rate_limit():
    # Hard quota: billing or account credits exhausted -> non-retriable
    hard_err = Exception(
        "You exceeded your current quota, please check your plan and billing details."
    )
    res_hard = classify_llm_error(hard_err, provider="openai")
    assert isinstance(res_hard, LLMQuotaExceededError)
    assert not isinstance(res_hard, LLMTransientError)

    # Burst rate limit: per-minute or concurrent requests -> retriable
    burst_err = Exception(
        "429 Too Many Requests: Rate limit reached for requests per minute (RPM)."
    )
    res_burst = classify_llm_error(burst_err, provider="openai")
    assert isinstance(res_burst, LLMRateLimitError)
    assert isinstance(res_burst, LLMTransientError)

    # Gemini RESOURCE_EXHAUSTED
    gemini_429 = MagicMock(
        spec=Exception, code=429, __str__=lambda self: "429 RESOURCE_EXHAUSTED: Quota exceeded"
    )
    res_gemini = classify_llm_error(gemini_429, provider="gemini")
    assert isinstance(res_gemini, LLMRateLimitError)


def test_classify_client_and_model_errors():
    # 400 Bad Request / context length
    bad_req = Exception("400 Invalid argument: context length exceeded (35000 > 32768 tokens)")
    res_bad = classify_llm_error(bad_req, provider="anthropic")
    assert isinstance(res_bad, LLMInvalidRequestError)
    assert res_bad.status_code == 400

    # 404 Model Not Found
    not_found = Exception("404 Model 'gemini-99.0' does not exist")
    res_not_found = classify_llm_error(not_found, provider="gemini")
    assert isinstance(res_not_found, LLMModelNotFoundError)
    assert res_not_found.status_code == 404


def test_classify_transient_network_errors():
    e_503 = Exception("503 Service Unavailable: backend gateway timeout")
    res_503 = classify_llm_error(e_503, provider="openai")
    assert isinstance(res_503, LLMTransientError)
    assert res_503.status_code == 503

    e_conn = Exception("Connection reset by peer; timed out after 30s")
    res_conn = classify_llm_error(e_conn, provider="ollama")
    assert isinstance(res_conn, LLMTransientError)


# =====================================================================
# 2. Resilient Execution & Retry Logic Tests
# =====================================================================


@pytest.mark.asyncio
async def test_resilience_immediate_success():
    coro = AsyncMock(return_value="all good")
    result = await execute_with_resilience(coro, provider="test", max_retries=3)
    assert result == "all good"
    assert coro.call_count == 1


@pytest.mark.asyncio
async def test_resilience_retry_recovery():
    # Fails twice with 429, succeeds on third attempt
    call_counts = 0

    async def _flaky():
        nonlocal call_counts
        call_counts += 1
        if call_counts < 3:
            raise Exception("429 RESOURCE_EXHAUSTED: Rate limit hit, retry after 0.001s")
        return "recovered"

    result = await execute_with_resilience(_flaky, provider="gemini", max_retries=4)
    assert result == "recovered"
    assert call_counts == 3


@pytest.mark.asyncio
async def test_resilience_fail_fast_on_non_retriable():
    call_counts = 0

    async def _auth_failure():
        nonlocal call_counts
        call_counts += 1
        raise Exception("401 Unauthorized: Invalid API key")

    with pytest.raises(LLMAuthenticationError) as exc_info:
        await execute_with_resilience(_auth_failure, provider="openai", max_retries=5)

    # Must abort immediately on attempt 1 with zero retries
    assert call_counts == 1
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_resilience_fail_fast_on_hard_quota():
    call_counts = 0

    async def _quota_failure():
        nonlocal call_counts
        call_counts += 1
        raise Exception(
            "You exceeded your current quota, please check your plan and billing details."
        )

    with pytest.raises(LLMQuotaExceededError):
        await execute_with_resilience(_quota_failure, provider="openai", max_retries=5)

    assert call_counts == 1


@pytest.mark.asyncio
async def test_resilience_exhaust_retries():
    call_counts = 0

    async def _persistent_503():
        nonlocal call_counts
        call_counts += 1
        raise Exception("503 Service Unavailable")

    with pytest.raises(LLMTransientError) as exc_info:
        await execute_with_resilience(_persistent_503, provider="anthropic", max_retries=2)

    # 1 initial call + 2 retries = 3 calls total
    assert call_counts == 3
    assert exc_info.value.status_code == 503


# =====================================================================
# 3. Provider Integration Verification
# =====================================================================


@pytest.mark.asyncio
async def test_gemini_provider_resilience_recovery():
    provider = GeminiProvider(api_key="g-test-key")
    call_attempts = 0

    async def mock_generate_content(*args, **kwargs):
        nonlocal call_attempts
        call_attempts += 1
        if call_attempts == 1:
            raise Exception("429 RESOURCE_EXHAUSTED: Rate limit reached")
        resp = MagicMock()
        resp.text = "Gemini resilience success"
        return resp

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.models.generate_content = mock_generate_content

        result = await provider.generate("test prompt")
        assert result == "Gemini resilience success"
        assert call_attempts == 2


@pytest.mark.asyncio
async def test_gemini_missing_key_fail_fast():
    provider = GeminiProvider(api_key="")
    with pytest.raises(LLMAuthenticationError, match="Google API key missing"):
        await provider.generate("test prompt")


@pytest.mark.asyncio
async def test_openai_missing_key_fail_fast():
    provider = OpenAIProvider(api_key="")
    with pytest.raises(LLMAuthenticationError, match="OpenAI API key missing"):
        await provider.generate("test prompt")


# =====================================================================
# 4. Comprehensive Branch & Boundary Edge Cases
# =====================================================================


def test_classify_passthrough_assigns_missing_provider():
    err = LLMError("test message", provider=None)
    res = classify_llm_error(err, provider="assigned_provider")
    assert res.provider == "assigned_provider"


def test_extract_retry_after_bounds():
    assert extract_retry_after("retry after 500s") is None
    assert extract_retry_after("wait 0s") is None
    assert extract_retry_after("retry after 1.2.3.4s") is None


def test_classify_attribute_status_codes():
    # Attribute 'status'
    e_status = MagicMock(spec=Exception, status=502, __str__=lambda self: "Bad Gateway")
    res_status = classify_llm_error(e_status, provider="openai")
    assert res_status.status_code == 502
    assert isinstance(res_status, LLMTransientError)

    # Attribute 'status_code'
    e_status_code = MagicMock(
        spec=Exception, status_code=504, __str__=lambda self: "Gateway Timeout"
    )
    res_status_code = classify_llm_error(e_status_code, provider="openai")
    assert res_status_code.status_code == 504
    assert isinstance(res_status_code, LLMTransientError)

    # Attribute 'http_status'
    e_http_status = MagicMock(spec=Exception, http_status=404, __str__=lambda self: "Not Found")
    res_http_status = classify_llm_error(e_http_status, provider="gemini")
    assert res_http_status.status_code == 404
    assert isinstance(res_http_status, LLMModelNotFoundError)


def test_classify_all_heuristic_variants():
    # Hard quota variations
    hard_quota_keywords = (
        "insufficient_quota",
        "billing_not_active",
        "quota_exceeded",
        "credit balance is too low",
    )
    for kw in hard_quota_keywords:
        err = Exception(f"Account issue: {kw}")
        assert isinstance(classify_llm_error(err), LLMQuotaExceededError)

    # Rate limit variations
    for kw in ("too many requests", "tpm", "rpm", "ratelimit"):
        err = Exception(f"Throttled: {kw}")
        assert isinstance(classify_llm_error(err), LLMRateLimitError)

    # Auth variations
    for kw in ("forbidden", "invalid api key", "authentication failure"):
        err = Exception(f"Credentials: {kw}")
        assert isinstance(classify_llm_error(err), LLMAuthenticationError)

    # Client error variations
    for kw in ("bad request", "maximum context", "tokens exceed"):
        err = Exception(f"Payload error: {kw}")
        assert isinstance(classify_llm_error(err), LLMInvalidRequestError)

    # Transient error variations
    for kw in ("timed out", "server disconnected", "temporarily unavailable"):
        err = Exception(f"Network glitch: {kw}")
        assert isinstance(classify_llm_error(err), LLMTransientError)

    # Fallback to generic LLMError
    generic_err = Exception("completely unusual unexpected error pattern")
    res_generic = classify_llm_error(generic_err, provider="test_prov")
    assert type(res_generic) is LLMError
    assert res_generic.provider == "test_prov"
    assert "completely unusual" in str(res_generic)


@pytest.mark.asyncio
async def test_resilience_explicit_retry_after_and_no_jitter():
    attempts = 0

    async def _retry_after_coro():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise Exception("429 Too Many Requests: wait 0.002s")
        return "success_after_wait"

    res = await execute_with_resilience(
        _retry_after_coro,
        provider="test",
        max_retries=3,
        jitter=False,
        initial_delay=0.001,
    )
    assert res == "success_after_wait"
    assert attempts == 2


@pytest.mark.asyncio
async def test_resilience_no_jitter_standard_backoff():
    attempts = 0

    async def _no_retry_after_coro():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise Exception("503 Service Unavailable")
        return "recovered_without_jitter"

    res = await execute_with_resilience(
        _no_retry_after_coro,
        provider="test",
        max_retries=2,
        jitter=False,
        initial_delay=0.001,
    )
    assert res == "recovered_without_jitter"
    assert attempts == 2


@pytest.mark.asyncio
async def test_resilience_negative_retries_fallthrough():
    async def _failing_coro():
        raise Exception("503 Service Unavailable")

    with pytest.raises(LLMError):
        await execute_with_resilience(_failing_coro, provider="test_fail", max_retries=-1)


@pytest.mark.asyncio
async def test_ollama_provider_connection_failure():
    with patch(
        "aiohttp.ClientSession.post", side_effect=aiohttp.ClientConnectionError("conn fail")
    ):
        p = OllamaProvider()
        with pytest.raises(Exception, match="Ollama connection failed"):
            await p.generate("test prompt")


@pytest.mark.asyncio
async def test_openai_provider_connection_failure():
    with patch(
        "aiohttp.ClientSession.post", side_effect=aiohttp.ClientConnectionError("conn fail")
    ):
        p = OpenAIProvider(api_key="sk-test")
        with pytest.raises(Exception, match="OpenAI request failed"):
            await p.generate("test prompt")


@pytest.mark.asyncio
async def test_anthropic_provider_connection_failure():
    with patch(
        "aiohttp.ClientSession.post", side_effect=aiohttp.ClientConnectionError("conn fail")
    ):
        p = AnthropicProvider(api_key="sk-test")
        with pytest.raises(Exception, match="Anthropic request failed"):
            await p.generate("test prompt")


@pytest.mark.asyncio
async def test_gemini_provider_sdk_crash():
    p = GeminiProvider(api_key="g-test")
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("SDK crash"))
        with pytest.raises(Exception, match="Gemini SDK request failed"):
            await p.generate("test prompt")


@pytest.mark.asyncio
async def test_anthropic_list_models_success():
    p = AnthropicProvider()
    models = await p.list_models()
    assert len(models) == 1
    assert models[0]["id"] == "claude-opus-5"


def test_gemini_vertex_ai_detection():
    p1 = GeminiProvider(api_key="g-test", base_url="https://vertexai.googleapis.com")
    assert p1.vertex_ai is True

    p2 = GeminiProvider(api_key="g-test", base_url="https://generativelanguage.googleapis.com")
    assert p2.vertex_ai is False


def test_provider_factory_remaining_branches():
    # None default to JUDGE_PROVIDER
    p_default = LLMProviderFactory.create(None)
    assert p_default is not None

    # Explicit string aliases
    assert LLMProviderFactory.create("google").__class__.__name__ == "GeminiProvider"
    assert LLMProviderFactory.create("anthropic").__class__.__name__ == "AnthropicProvider"
