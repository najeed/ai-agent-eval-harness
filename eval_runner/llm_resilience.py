"""
Centralized LLM Error Classifier & Resilience Layer.

Provides normalized typed domain exceptions, heuristic and SDK-level error classification,
and full-jitter exponential backoff retry execution for LLM providers across both
OSS evaluation harnesses and Enterprise services.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from collections.abc import Callable, Coroutine
from typing import Any

from . import config

logger = logging.getLogger("eval_runner.llm_resilience")


# =====================================================================
# 1. Typed Domain Exceptions Hierarchy
# =====================================================================


class LLMError(Exception):
    """Base exception for all LLM provider interactions."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        status_code: int | None = None,
        raw_error: Exception | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.raw_error = raw_error
        self.retry_after = retry_after

    def __str__(self) -> str:
        prefix = f"[{self.provider}] " if self.provider else ""
        code = f" (Status {self.status_code})" if self.status_code else ""
        return f"{prefix}{self.message}{code}"


class LLMTransientError(LLMError):
    """Retriable transient errors: network timeouts, 500/502/503/504 gateways, socket drops."""

    pass


class LLMRateLimitError(LLMTransientError):
    """
    Retriable rate limit or quota burst errors (HTTP 429, RESOURCE_EXHAUSTED burst).
    Expected to recover after a backoff window.
    """

    pass


class LLMQuotaExceededError(LLMError):
    """
    Non-retriable hard quota or billing depletion (account budget exhausted, billing inactive).
    Retrying will NOT succeed and wastes compute/time.
    """

    pass


class LLMAuthenticationError(LLMError):
    """Non-retriable credentials error (401/403, invalid or missing API key)."""

    pass


class LLMInvalidRequestError(LLMError):
    """Non-retriable client errors (400 Bad Request, context length exceeded, schema mismatch)."""

    pass


class LLMModelNotFoundError(LLMError):
    """Non-retriable model resolution errors (404 Not Found, deprecated or unavailable model)."""

    pass


# =====================================================================
# 2. Error Classifier
# =====================================================================

_RE_RETRY_AFTER = re.compile(r"(?:retry|wait)[^\d]*([\d\.]+)\s*(?:s|sec|seconds?)?", re.IGNORECASE)
_RE_STATUS_CODE = re.compile(r"\b(400|401|403|404|429|500|502|503|504)\b")


def extract_retry_after(error_str: str) -> float | None:
    """Extracts explicit retry-after duration in seconds if present in error message."""
    match = _RE_RETRY_AFTER.search(error_str)
    if match:
        try:
            val = float(match.group(1))
            if 0 < val <= 300:  # reasonable upper bound
                return val
        except (ValueError, TypeError):
            pass
    return None


def classify_llm_error(error: Exception, provider: str = "generic") -> LLMError:
    """
    Inspects raw SDK or HTTP errors and maps them to normalized typed domain exceptions.

    Handles:
    - Google GenAI SDK (google.genai.errors.APIError, RESOURCE_EXHAUSTED)
    - OpenAI API / aiohttp HTTP status codes
    - Anthropic SDK & REST payloads
    - Ollama & local model errors
    """
    if isinstance(error, LLMError):
        if not error.provider:
            error.provider = provider
        return error

    err_msg = str(error)
    err_type = type(error).__name__

    # Extract status code from error attributes if available
    status_code: int | None = None
    for attr in ("code", "status", "status_code", "http_status"):
        val = getattr(error, attr, None)
        if isinstance(val, int):
            status_code = val
            break

    # If not found on attributes, check for status codes in error message
    if status_code is None:
        match = _RE_STATUS_CODE.search(err_msg)
        if match:
            status_code = int(match.group(1))

    retry_after = extract_retry_after(err_msg)
    err_lower = err_msg.lower()

    # 1. Authentication & Permission Errors (401, 403, PERMISSION_DENIED)
    if (
        status_code in (401, 403)
        or "permission_denied" in err_lower
        or "unauthorized" in err_lower
        or "forbidden" in err_lower
        or "api key missing" in err_lower
        or "invalid api key" in err_lower
        or "authentication" in err_lower
    ):
        return LLMAuthenticationError(
            message=err_msg,
            provider=provider,
            status_code=status_code or 401,
            raw_error=error,
        )

    # 2. Hard Quota / Billing Depletion (Non-retriable)
    # Check for messages indicating credit or hard plan exhaustion vs transient per-minute burst
    is_hard_quota = (
        "exceeded your current quota" in err_lower
        or "check your plan and billing details" in err_lower
        or "insufficient_quota" in err_lower
        or "billing_not_active" in err_lower
        or "quota_exceeded" in err_lower
        or "credit balance is too low" in err_lower
    )
    if is_hard_quota:
        return LLMQuotaExceededError(
            message=err_msg,
            provider=provider,
            status_code=status_code or 429,
            raw_error=error,
        )

    # 3. Rate Limits & Transient Burst Quota (429, RESOURCE_EXHAUSTED)
    if (
        status_code == 429
        or "resource_exhausted" in err_lower
        or "rate limit" in err_lower
        or "ratelimit" in err_lower
        or "too many requests" in err_lower
        or "tpm" in err_lower
        or "rpm" in err_lower
    ):
        return LLMRateLimitError(
            message=err_msg,
            provider=provider,
            status_code=429,
            raw_error=error,
            retry_after=retry_after,
        )

    # 4. Model Not Found (404)
    if status_code == 404 or "model not found" in err_lower or "does not exist" in err_lower:
        return LLMModelNotFoundError(
            message=err_msg,
            provider=provider,
            status_code=404,
            raw_error=error,
        )

    # 5. Invalid Request / Context Window Exceeded (400)
    if (
        status_code == 400
        or "invalid_argument" in err_lower
        or "bad request" in err_lower
        or "context length" in err_lower
        or "maximum context" in err_lower
        or "tokens exceed" in err_lower
    ):
        return LLMInvalidRequestError(
            message=err_msg,
            provider=provider,
            status_code=400,
            raw_error=error,
        )

    # 6. Transient Gateway / Server / Network Errors (500, 502, 503, 504, Timeouts)
    if (
        status_code in (500, 502, 503, 504)
        or "timeout" in err_lower
        or "timed out" in err_lower
        or "connection reset" in err_lower
        or "server disconnected" in err_lower
        or "service unavailable" in err_lower
        or "temporarily unavailable" in err_lower
        or "aiohttp" in err_type.lower()
    ):
        return LLMTransientError(
            message=err_msg,
            provider=provider,
            status_code=status_code or 503,
            raw_error=error,
            retry_after=retry_after,
        )

    # Default fallback to generic LLMError
    return LLMError(
        message=err_msg,
        provider=provider,
        status_code=status_code,
        raw_error=error,
    )


# =====================================================================
# 3. Resilient Execution Harness (Full-Jitter Backoff)
# =====================================================================


async def execute_with_resilience[T](
    coro_fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    provider: str = "generic",
    max_retries: int | None = None,
    initial_delay: float | None = None,
    max_delay: float | None = None,
    backoff_factor: float | None = None,
    jitter: bool = True,
    **kwargs: Any,
) -> T:
    """
    Executes an asynchronous LLM provider operation with intelligent retry resilience.

    - Automatically catches and classifies SDK exceptions.
    - Applies exponential backoff with full jitter on transient errors (429, 503, timeouts).
    - Respects provider `retry_after` hints when supplied.
    - Immediately aborts without retrying on hard failures (401/403, 400 bad request, quota).
    """
    retries = max_retries if max_retries is not None else getattr(config, "LLM_MAX_RETRIES", 4)
    init_delay = (
        initial_delay
        if initial_delay is not None
        else getattr(config, "LLM_INITIAL_RETRY_DELAY", 1.0)
    )
    cap_delay = max_delay if max_delay is not None else getattr(config, "LLM_MAX_RETRY_DELAY", 30.0)
    factor = (
        backoff_factor if backoff_factor is not None else getattr(config, "LLM_BACKOFF_FACTOR", 2.0)
    )

    last_error: LLMError | None = None

    for attempt in range(retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as raw_e:
            classified = classify_llm_error(raw_e, provider=provider)
            last_error = classified

            # If not retriable, fail immediately
            if not isinstance(classified, LLMTransientError):
                logger.debug(
                    "[LLM Resilience] Non-retriable %s for provider '%s': %s",
                    type(classified).__name__,
                    provider,
                    classified,
                )
                raise classified from raw_e

            # If we've exhausted retry budget, stop
            if attempt >= retries:
                logger.warning(
                    "[LLM Resilience] Exhausted %d retries for provider '%s': %s",
                    retries,
                    provider,
                    classified,
                )
                break

            # Calculate delay with exponential backoff and jitter
            if classified.retry_after and 0 < classified.retry_after <= cap_delay:
                delay = classified.retry_after
            else:
                base_delay = min(cap_delay, init_delay * (factor**attempt))
                if jitter:
                    delay = random.uniform(base_delay * 0.5, base_delay * 1.5)
                else:
                    delay = base_delay
                delay = min(cap_delay, max(0.05, delay))

            # In test environments, avoid artificial latency unless explicitly requested
            if "PYTEST_CURRENT_TEST" in os.environ and initial_delay is None:
                delay = min(delay, 0.005)

            logger.info(
                "[LLM Resilience] Retrying provider '%s' in %.2fs (attempt %d/%d) due to %s: %s",
                provider,
                delay,
                attempt + 1,
                retries,
                type(classified).__name__,
                classified.message,
            )

            await asyncio.sleep(delay)

    if last_error:
        raise last_error
    raise LLMError(f"Execution failed with unknown error for provider '{provider}'.")
