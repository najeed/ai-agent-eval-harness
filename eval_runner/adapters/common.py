"""
eval_runner/adapters/common.py

Shared infrastructure for AgentV adapter implementations.

Architecture decision:
- AdapterSessionPool is the lifecycle-scoped resource manager.
- SessionManager is retained only as a backwards-compatible facade for existing
  adapters/tests that call SessionManager.get_session()/close_all().
- New runtime code should own an AdapterSessionPool explicitly and close it with
  the lifecycle that owns the adapter execution.

Responsibilities:
- lifecycle-safe aiohttp connection pooling
- event-loop-safe session recreation
- bounded retry with exponential backoff, jitter, Retry-After and deadline support
- standardized LangChain/LangGraph telemetry
- deterministic response/action normalization
- no success-on-unknown transport/status failures
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import aiohttp

from .. import config
from ..events import CoreEvents, emit
from ..utils import crypto

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Optional LangChain dependency
# ---------------------------------------------------------------------------

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:

    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Minimal fallback so the core package remains importable."""

        pass


# ---------------------------------------------------------------------------
# AdapterSessionPool
# ---------------------------------------------------------------------------


class AdapterSessionPool:
    """
    Lifecycle-scoped aiohttp connection pool.

    This is intentionally an instance rather than a singleton. A runtime,
    tenant, test harness, worker, or evaluation session can own one pool and
    explicitly close it.

    The pool is safe against event-loop changes. aiohttp ClientSession objects
    are loop-affine, so a session created on a previous loop is discarded and a
    fresh session is created on the current loop.
    """

    def __init__(
        self,
        *,
        timeout: float | aiohttp.ClientTimeout | None = None,
        connection_limit: int = 100,
        dns_cache_ttl: int = 300,
        keepalive_timeout: float = 30.0,
        trust_env: bool = True,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()
        self._timeout = (
            timeout
            if isinstance(timeout, aiohttp.ClientTimeout)
            else aiohttp.ClientTimeout(
                total=(
                    float(timeout) if timeout is not None else float(config.DEFAULT_ADAPTER_TIMEOUT)
                )
            )
        )
        self._connection_limit = max(1, int(connection_limit))
        self._dns_cache_ttl = max(0, int(dns_cache_ttl))
        self._keepalive_timeout = max(0.0, float(keepalive_timeout))
        self._trust_env = bool(trust_env)
        self._headers = dict(headers or {})

    @staticmethod
    def _current_loop() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    @staticmethod
    def _session_loop(session: aiohttp.ClientSession | None):
        if session is None:
            return None
        return getattr(session, "_loop", None)

    def _is_usable(
        self,
        session: aiohttp.ClientSession | None,
        current_loop: asyncio.AbstractEventLoop | None,
    ) -> bool:
        if session is None or session.closed:
            return False

        session_loop = self._session_loop(session)
        if current_loop is not None and session_loop is not None:
            return session_loop is current_loop

        return True

    async def _close_session(self, session: aiohttp.ClientSession | None) -> None:
        if session is None or session.closed:
            return

        try:
            await session.close()
        except Exception as exc:
            logger.debug("Adapter session close failed: %s", exc, exc_info=True)

    def _build_session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(
            limit=self._connection_limit,
            ttl_dns_cache=self._dns_cache_ttl,
            keepalive_timeout=self._keepalive_timeout,
            enable_cleanup_closed=True,
        )

        return aiohttp.ClientSession(
            connector=connector,
            connector_owner=True,
            timeout=self._timeout,
            trust_env=self._trust_env,
            headers=self._headers or None,
        )

    async def get_session(self) -> aiohttp.ClientSession:
        """
        Return the current reusable ClientSession.

        The session is reused within its owning event loop. If that loop
        changes, the stale session is discarded and recreated.
        """
        current_loop = self._current_loop()
        session = self._session

        if self._is_usable(session, current_loop):
            return session  # type: ignore[return-value]

        async with self._lock:
            current_loop = self._current_loop()
            session = self._session

            if self._is_usable(session, current_loop):
                return session  # type: ignore[return-value]

            if session is not None:
                await self._close_session(session)

            self._session = self._build_session()
            return self._session

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """
        Create a request using the managed session.

        The caller owns the response context manager:
            async with await pool.request(...) as response:
                ...
        """
        session = await self.get_session()
        return session.request(method, url, **kwargs)

    async def close(self) -> None:
        """Close the owned session and release its connector."""
        async with self._lock:
            session = self._session
            self._session = None

            if session is not None:
                await self._close_session(session)

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Read-only diagnostic access to the currently owned session."""
        return self._session


# ---------------------------------------------------------------------------
# Backwards-compatible facade
# ---------------------------------------------------------------------------


class SessionManager:
    """
    Compatibility facade around the default AdapterSessionPool.

    This class intentionally exists only for compatibility with the current
    adapter API. It is not the preferred lifecycle boundary for new code.

    New code should prefer:
        pool = AdapterSessionPool()
        ...
        await pool.close()

    Existing code may continue using:
        await SessionManager.get_session()
        await SessionManager.close_all()
    """

    _pool = AdapterSessionPool()
    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        session = await cls._pool.get_session()
        cls._session = session
        return session

    @classmethod
    async def close_all(cls) -> None:
        await cls._pool.close()
        cls._session = None

    @classmethod
    def reset(cls) -> None:
        """
        Reset the facade object.

        This method is intentionally synchronous and does not close an active
        session. Call close_all() when releasing live resources.
        """
        cls._pool = AdapterSessionPool()
        cls._session = None


# ---------------------------------------------------------------------------
# Retry infrastructure
# ---------------------------------------------------------------------------


class AdapterRetryError(RuntimeError):
    """Raised when retry execution exceeds an explicit adapter deadline."""


class BaseAdapter:
    """
    Shared adapter resilience implementation.

    Retry semantics:
    - HTTP: configurable retry status set, default 429/502/503/504
    - network: connector failures and timeouts
    - no retry on ordinary application errors
    - exponential backoff with full jitter
    - honors Retry-After where available
    - optional total retry deadline
    - asyncio cancellation always propagates
    """

    DEFAULT_RETRY_CODES = frozenset({429, 502, 503, 504})

    def __init__(self, name: str) -> None:
        if not name or not str(name).strip():
            raise ValueError("Adapter name must be non-empty.")

        self.name = str(name)
        self.max_retries = max(0, int(config.ADAPTER_MAX_RETRIES))
        self.retry_delay = max(0.0, float(config.ADAPTER_RETRY_DELAY))
        self.max_retry_delay = max(
            self.retry_delay,
            float(getattr(config, "ADAPTER_MAX_RETRY_DELAY", 30.0)),
        )

    @staticmethod
    def _retry_after_seconds(
        exc: aiohttp.ClientResponseError,
        *,
        now: float | None = None,
    ) -> float | None:
        """
        Resolve Retry-After from response headers.

        Supports:
        - integer/float delay-seconds
        - RFC 7231 HTTP-date
        """
        headers = getattr(exc, "headers", None)
        if not headers:
            return None

        value = headers.get("Retry-After")
        if value is None:
            return None

        value = str(value).strip()
        if not value:
            return None

        try:
            seconds = float(value)
            return max(0.0, seconds)
        except ValueError:
            pass

        try:
            retry_dt = parsedate_to_datetime(value)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=UTC)

            current = (
                datetime.fromtimestamp(now or time.time(), tz=UTC)
                if now is not None
                else datetime.now(UTC)
            )
            return max(0.0, (retry_dt - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _is_retryable_exception(
        exc: BaseException,
        retry_codes: set[int],
    ) -> bool:
        if isinstance(exc, aiohttp.ClientResponseError):
            return exc.status in retry_codes

        return isinstance(
            exc,
            (
                asyncio.TimeoutError,
                TimeoutError,
                aiohttp.ClientConnectionError,
            ),
        )

    def _backoff_seconds(
        self,
        retry_number: int,
        *,
        base_delay: float,
        max_delay: float,
    ) -> float:
        """
        Full-jitter exponential backoff.

        retry_number is 1-based:
            cap = base_delay * 2^(retry_number - 1)
            delay = random(0, cap)
        """
        cap = min(
            max_delay,
            base_delay * (2 ** max(0, retry_number - 1)),
        )

        if cap <= 0.0:
            return 0.0

        return random.SystemRandom().uniform(0.0, cap)

    async def call_with_retry(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        retry_codes: set[int] | frozenset[int] | None = None,
        deadline: float | None = None,
        respect_retry_after: bool = True,
        **kwargs: Any,
    ) -> T:
        """
        Execute an async operation with bounded retry.

        Args:
            func:
                Async callable to execute.
            max_attempts:
                Total attempts including the first attempt.
            base_delay:
                Initial exponential backoff cap.
            max_delay:
                Maximum backoff cap.
            retry_codes:
                HTTP status codes eligible for retry.
            deadline:
                Maximum total elapsed retry time in seconds.
            respect_retry_after:
                Prefer server-supplied Retry-After for HTTP retries.

        Returns:
            The successful callable result.

        Raises:
            Original exception when retries are exhausted.
            AdapterRetryError when an explicit deadline expires.
        """
        if max_attempts is None:
            max_attempts = self.max_retries + 1
        else:
            max_attempts = int(max_attempts)

        if max_attempts <= 0:
            raise ValueError("max_attempts must be >= 1.")

        if base_delay is None:
            base_delay = self.retry_delay
        base_delay = max(0.0, float(base_delay))

        if max_delay is None:
            max_delay = self.max_retry_delay
        max_delay = max(base_delay, float(max_delay))

        if retry_codes is None:
            effective_retry_codes = set(self.DEFAULT_RETRY_CODES)
        else:
            effective_retry_codes = {int(code) for code in retry_codes}

        start = time.monotonic()

        for attempt in range(1, max_attempts + 1):
            try:
                return await func(*args, **kwargs)

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                if attempt >= max_attempts:
                    raise

                if not self._is_retryable_exception(exc, effective_retry_codes):
                    raise

                elapsed = time.monotonic() - start

                if deadline is not None:
                    remaining = float(deadline) - elapsed
                    if remaining <= 0.0:
                        raise AdapterRetryError(
                            f"Adapter '{self.name}' retry deadline exceeded after "
                            f"{attempt} attempt(s)."
                        ) from exc
                else:
                    remaining = None

                retry_after = None
                if (
                    respect_retry_after
                    and isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status in effective_retry_codes
                ):
                    retry_after = self._retry_after_seconds(exc)

                delay = (
                    retry_after
                    if retry_after is not None
                    else self._backoff_seconds(
                        attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                    )
                )

                if remaining is not None:
                    if remaining <= 0:
                        raise AdapterRetryError(
                            f"Adapter '{self.name}' retry deadline exceeded."
                        ) from exc
                    delay = min(delay, remaining)

                logger.warning(
                    "[Adapter:%s] transient failure on attempt %d/%d: %s; retrying in %.3fs",
                    self.name,
                    attempt,
                    max_attempts,
                    self._format_exception(exc),
                    delay,
                )

                if delay > 0:
                    await asyncio.sleep(delay)

        raise AssertionError("Unreachable retry state.")

    @staticmethod
    def _format_exception(exc: BaseException) -> str:
        if isinstance(exc, aiohttp.ClientResponseError):
            return f"HTTP {exc.status}: {exc.message or type(exc).__name__}"
        return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# LangChain / LangGraph telemetry
# ---------------------------------------------------------------------------


class AESCallbackHandler(BaseCallbackHandler):
    """
    Standardized LangChain/LangGraph telemetry bridge.

    Deliberately emits summaries and hashes rather than raw prompts/state so
    adapter telemetry does not become an uncontrolled data-exfiltration path.
    """

    def __init__(
        self,
        adapter_name: str,
        identifier: str,
        span_context: dict[str, Any] | None = None,
    ) -> None:
        self.adapter_name = str(adapter_name)
        self.identifier = str(identifier)
        self.span_context = span_context

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        payload.setdefault("adapter", self.adapter_name)
        payload.setdefault("id", self.identifier)

        if self.span_context is None:
            emit(event_name, payload)
        else:
            emit(event_name, payload, span_context=self.span_context)

    @staticmethod
    def _safe_type_summary(value: Any) -> str:
        if value is None:
            return "NoneType"
        return type(value).__name__

    @classmethod
    def _state_hash_and_summary(
        cls,
        inputs: Any,
    ) -> tuple[str | None, Any]:
        try:
            canonical = json.dumps(
                inputs,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            return crypto.checksum(canonical), cls._summarize_inputs(inputs)
        except Exception as exc:
            logger.debug("State hashing failed: %s", exc, exc_info=True)
            return None, {"error": "serialization_failed"}

    @classmethod
    def _summarize_inputs(cls, inputs: Any) -> Any:
        if isinstance(inputs, Mapping):
            return {str(key): cls._safe_type_summary(value) for key, value in inputs.items()}

        if isinstance(inputs, (list, tuple)):
            return {
                "container": type(inputs).__name__,
                "length": len(inputs),
                "item_types": [cls._safe_type_summary(value) for value in inputs[:20]],
            }

        return cls._safe_type_summary(inputs)

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        """
        Normalize token usage from several LangChain response representations.
        """
        candidates: list[Mapping[str, Any]] = []

        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, Mapping):
            token_usage = llm_output.get("token_usage")
            if isinstance(token_usage, Mapping):
                candidates.append(token_usage)
            candidates.append(llm_output)

        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, Mapping):
            usage = response_metadata.get("usage")
            if isinstance(usage, Mapping):
                candidates.append(usage)
            candidates.append(response_metadata)

        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, Mapping):
            candidates.append(usage_metadata)

        aliases = {
            "prompt_tokens": (
                "prompt_tokens",
                "input_tokens",
                "input_token_count",
            ),
            "completion_tokens": (
                "completion_tokens",
                "output_tokens",
                "output_token_count",
                "candidates_token_count",
            ),
            "total_tokens": (
                "total_tokens",
                "total_token_count",
            ),
        }

        normalized: dict[str, int] = {}

        for target, keys in aliases.items():
            for candidate in candidates:
                for key in keys:
                    value = candidate.get(key)
                    if isinstance(value, (int, float)):
                        normalized[target] = int(value)
                        break
                if target in normalized:
                    break

        if "total_tokens" not in normalized:
            prompt = normalized.get("prompt_tokens", 0)
            completion = normalized.get("completion_tokens", 0)
            if prompt or completion:
                normalized["total_tokens"] = prompt + completion

        return normalized

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        state_hash, inputs_summary = self._state_hash_and_summary(inputs)

        self._emit(
            CoreEvents.CHAIN_START,
            {
                "state_hash": state_hash,
                "inputs_summary": inputs_summary,
                "chain_name": (serialized.get("name") if isinstance(serialized, Mapping) else None),
            },
        )

    def on_chain_end(
        self,
        outputs: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.CHAIN_END,
            {
                "output_type": self._safe_type_summary(outputs),
            },
        )

    def on_chain_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "phase": "chain",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def on_node_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        node_id = "unknown"

        if isinstance(serialized, Mapping):
            raw_id = serialized.get("id")

            if isinstance(raw_id, (list, tuple)) and raw_id:
                node_id = str(raw_id[-1])
            elif raw_id is not None:
                node_id = str(raw_id)
            elif serialized.get("name"):
                node_id = str(serialized["name"])

        self._emit(
            CoreEvents.NODE_START,
            {
                "node_id": node_id,
                "inputs_summary": self._summarize_inputs(inputs),
            },
        )

    def on_node_end(
        self,
        outputs: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.NODE_END,
            {
                "output_type": self._safe_type_summary(outputs),
            },
        )

    def on_node_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "phase": "node",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        model_name = None
        if isinstance(serialized, Mapping):
            model_name = serialized.get("name") or serialized.get("id")

        self._emit(
            CoreEvents.ADAPTER_DEBUG,
            {
                "message": f"LLM Start: {len(prompts or [])} prompt(s)",
                "model": model_name,
            },
        )

    def on_llm_end(
        self,
        response: Any,
        **kwargs: Any,
    ) -> None:
        usage = self._extract_usage(response)

        if usage:
            self._emit(
                "metric_update",
                {
                    "tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                },
            )

    def on_llm_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "phase": "llm",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        tool_name = "unknown"

        if isinstance(serialized, Mapping):
            tool_name = str(serialized.get("name") or serialized.get("id") or "unknown")

        self._emit(
            CoreEvents.TOOL_CALL,
            {
                "tool_name": tool_name,
                "input_hash": crypto.checksum(str(input_str)),
            },
        )

    def on_tool_end(
        self,
        output: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.TOOL_RESULT,
            {
                "output_type": self._safe_type_summary(output),
                "output_hash": crypto.checksum(str(output)),
            },
        )

    def on_tool_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "phase": "tool",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )

    def on_agent_action(
        self,
        action: Any,
        **kwargs: Any,
    ) -> None:
        tool = getattr(action, "tool", None)
        tool_input = getattr(action, "tool_input", None)

        self._emit(
            CoreEvents.ACTION_START,
            {
                "tool_name": str(tool) if tool is not None else None,
                "tool_input_hash": (
                    crypto.checksum(str(tool_input)) if tool_input is not None else None
                ),
            },
        )

    def on_agent_finish(
        self,
        finish: Any,
        **kwargs: Any,
    ) -> None:
        return_values = getattr(finish, "return_values", None)

        self._emit(
            CoreEvents.ACTION_END,
            {
                "return_type": self._safe_type_summary(return_values),
            },
        )


# ---------------------------------------------------------------------------
# Response normalization
# ---------------------------------------------------------------------------


class DualNormalizationHub:
    """
    Canonical adapter response/action normalization.

    Precedence:
        transport failure -> error
        explicit override -> mapped action
        declared schema mapping -> mapped action
        response status/state heuristics -> inferred action
        explicit content -> final_answer
        unknown empty response -> error
    """

    POLLING_KEYWORDS = tuple(k.strip().lower() for k in config.POLLING_KEYWORDS if str(k).strip())
    HITL_KEYWORDS = tuple(k.strip().lower() for k in config.HITL_KEYWORDS if str(k).strip())
    TERMINAL_KEYWORDS = tuple(k.strip().lower() for k in config.TERMINAL_KEYWORDS if str(k).strip())
    ERROR_KEYWORDS = tuple(k.strip().lower() for k in config.ERROR_KEYWORDS if str(k).strip())

    VALID_ACTIONS = frozenset(
        {
            "hitl_pause",
            "final_answer",
            "error",
            "completed",
            "processing",
        }
    )

    STATUS_FIELDS = (
        "status",
        "state",
        "phase",
        "outcome",
        "decision",
        "result",
    )

    @classmethod
    def normalize_text(
        cls,
        text: str,
        *,
        empty_action: str = "error",
    ) -> str:
        """
        Infer an action from free text.

        HITL is checked before polling because values such as
        "waiting for human review" are both polling-like and explicitly
        human-gated.
        """
        if text is None:
            return empty_action

        text_lower = str(text).strip().lower()

        if not text_lower:
            return empty_action

        if any(keyword in text_lower for keyword in cls.HITL_KEYWORDS):
            return "hitl_pause"

        if any(keyword in text_lower for keyword in cls.POLLING_KEYWORDS):
            return "processing"

        if any(keyword in text_lower for keyword in cls.ERROR_KEYWORDS):
            return "error"

        if any(keyword in text_lower for keyword in cls.TERMINAL_KEYWORDS):
            return "final_answer"

        # Free-form content with no explicit state marker is still a terminal
        # response; this path is used primarily by LLM/provider adapters.
        return "final_answer"

    @classmethod
    def _validate_action(cls, action: Any) -> str | None:
        action_str = str(action).strip().lower()
        return action_str if action_str in cls.VALID_ACTIONS else None

    @classmethod
    def _extract_status_value(
        cls,
        response: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        for key in cls.STATUS_FIELDS:
            if key in response:
                value = response.get(key)
                if value is not None:
                    return key, str(value)

        for key, value in response.items():
            key_lower = str(key).lower()
            if any(field in key_lower for field in ("status", "state", "result")):
                if value is not None:
                    return str(key), str(value)

        return None, None

    @classmethod
    def normalize(
        cls,
        response: Mapping[str, Any] | None,
        status_code: int = 200,
        overrides: Mapping[str, str] | None = None,
        schema: Mapping[str, Any] | None = None,
        *,
        default_action: str = "final_answer",
    ) -> str:
        """
        Normalize an adapter JSON response.

        HTTP failures always remain failures. An override cannot convert a
        4xx/5xx transport result into a successful action.
        """
        if response is None:
            response = {}

        if not isinstance(response, Mapping):
            return "error"

        try:
            status_code_int = int(status_code)
        except (TypeError, ValueError):
            status_code_int = 500

        if status_code_int >= 400:
            return "error"

        # 1. Explicit mappings supplied by trusted adapter configuration.
        if overrides:
            for condition, action in overrides.items():
                normalized_action = cls._validate_action(action)
                if normalized_action is None:
                    logger.warning(
                        "Ignoring invalid adapter override action %r for %r.",
                        action,
                        condition,
                    )
                    continue

                for key in cls.STATUS_FIELDS:
                    if key in response:
                        value = response.get(key)
                        if (
                            value is not None
                            and str(value).strip().lower() == str(condition).strip().lower()
                        ):
                            return normalized_action

        # 2. Explicit schema mapping.
        if schema:
            field = str(schema.get("status_field", "status"))
            mapping = schema.get("mapping", {})

            if isinstance(mapping, Mapping) and field in response:
                value = response.get(field)
                if value is not None:
                    mapped = mapping.get(str(value).lower())
                    normalized_action = cls._validate_action(mapped)
                    if normalized_action:
                        emit(
                            CoreEvents.ADAPTER_DEBUG,
                            {
                                "message": (
                                    f"Schema Match: {field}={value!r} -> {normalized_action}"
                                )
                            },
                        )
                        return normalized_action

        # 3. Status/state/outcome heuristic interpretation.
        field, status_value = cls._extract_status_value(response)

        if status_value:
            action = cls.normalize_text(status_value)

            if action != "final_answer":
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "message": (
                            f"Agnostic Mapping: {action} (Field: {field}, Value: {status_value!r})"
                        )
                    },
                )

            return action

        # 4. Explicit content/answer fields indicate a completed textual
        # response rather than an unknown status.
        for key in ("content", "output", "answer", "message", "text"):
            value = response.get(key)
            if value is not None:
                if isinstance(value, str) and not value.strip():
                    continue
                return "final_answer"

        # 5. Empty response is a failure. Non-empty arbitrary JSON remains
        # configurable but defaults to a terminal response for compatibility.
        if response:
            normalized_default = cls._validate_action(default_action)
            if normalized_default:
                return normalized_default

        return "error"


__all__ = [
    "AdapterRetryError",
    "AdapterSessionPool",
    "AESCallbackHandler",
    "BaseAdapter",
    "DualNormalizationHub",
    "SessionManager",
]
