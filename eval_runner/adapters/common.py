"""
eval_runner/adapters/common.py

Shared production infrastructure for AgentV adapter implementations.

Responsibilities:
- lifecycle-scoped aiohttp connection pooling
- backwards-compatible SessionManager facade
- bounded retry with exponential backoff, jitter, Retry-After and deadlines
- common HTTP request / JSON / SSE handling
- validated W3C trace propagation
- safe request-header construction
- bounded response decoding
- deterministic adapter response/action normalization
- standardized LangChain/LangGraph telemetry
- JSON-safe serialization helpers
- common adapter execution context

Design principles:
- no synthetic success responses
- no shell execution
- no credential leakage through telemetry
- no unbounded response/body buffering
- cancellation always propagates
- transport failures cannot normalize into success
- adapter lifecycle can be explicitly owned
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar
from urllib.parse import urlparse

import aiohttp

from .. import config
from ..events import CoreEvents, emit
from ..utils import crypto

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_RESPONSE_BYTES = int(os.getenv("ADAPTER_MAX_RESPONSE_BYTES", str(16 * 1024 * 1024)))
DEFAULT_MAX_SSE_EVENT_BYTES = int(os.getenv("ADAPTER_MAX_SSE_EVENT_BYTES", str(4 * 1024 * 1024)))
DEFAULT_MAX_HEADER_VALUE_BYTES = int(os.getenv("ADAPTER_MAX_HEADER_VALUE_BYTES", "16384"))

RETRYABLE_HTTP_STATUS_CODES = frozenset(
    {
        408,
        425,
        429,
        500,
        502,
        503,
        504,
    }
)

TRACEPARENT_PREFIX = "traceparent"

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:

    class BaseCallbackHandler:  # type: ignore[no-redef]
        """
        Import-safe fallback.

        The actual LangChain callback implementation is used whenever
        langchain-core is installed. This fallback exists only so AgentV's
        core adapter package remains importable without optional framework
        dependencies.
        """

        __slots__ = ()


# ---------------------------------------------------------------------------
# Generic serialization / validation helpers
# ---------------------------------------------------------------------------


def is_mapping(value: Any) -> bool:
    """Return True for Mapping-compatible values."""
    return isinstance(value, Mapping)


def coerce_timeout(
    value: Any,
    *,
    default: float | None = None,
    minimum: float = 0.001,
) -> float:
    """Resolve a positive timeout deterministically."""
    fallback = (
        float(default)
        if default is not None
        else float(getattr(config, "DEFAULT_ADAPTER_TIMEOUT", 30.0))
    )

    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return fallback

    if resolved <= 0:
        return fallback

    return max(resolved, minimum)


def json_safe(
    value: Any,
    *,
    max_depth: int = 8,
    _depth: int = 0,
) -> Any:
    """
    Convert arbitrary provider/framework values into bounded JSON-safe values.

    This helper is deliberately conservative. It is intended for telemetry,
    evidence metadata, and normalized responses rather than application logic.
    """
    if _depth >= max_depth:
        return "<max-depth>"

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item, max_depth=max_depth, _depth=_depth + 1)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            json_safe(item, max_depth=max_depth, _depth=_depth + 1) for item in list(value)[:1000]
        ]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return json_safe(
                model_dump(mode="json"),
                max_depth=max_depth,
                _depth=_depth + 1,
            )
        except Exception:
            logger.debug("model_dump serialization failed", exc_info=True)

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        try:
            return json_safe(
                dict_method(),
                max_depth=max_depth,
                _depth=_depth + 1,
            )
        except Exception:
            logger.debug("dict() serialization failed", exc_info=True)

    return str(value)


def canonical_json(
    value: Any,
    *,
    ensure_ascii: bool = False,
) -> str:
    """Serialize JSON deterministically for hashing, transport, or evidence."""
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def serialize_json_bytes(
    value: Any,
    *,
    ensure_ascii: bool = False,
) -> bytes:
    """Serialize JSON into UTF-8 bytes with deterministic separators."""
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def bounded_text(
    value: Any,
    *,
    max_bytes: int = 4096,
) -> str:
    """Convert a value to UTF-8 text bounded by bytes rather than characters."""
    text = str(value)
    encoded = text.encode("utf-8", errors="replace")

    if len(encoded) <= max_bytes:
        return text

    return encoded[:max_bytes].decode("utf-8", errors="replace")


def _safe_header_value(value: Any) -> str | None:
    if not isinstance(value, str):
        value = str(value)

    encoded = value.encode("utf-8", errors="replace")

    if len(encoded) > DEFAULT_MAX_HEADER_VALUE_BYTES:
        encoded = encoded[:DEFAULT_MAX_HEADER_VALUE_BYTES]

    result = encoded.decode("utf-8", errors="replace")

    if "\r" in result or "\n" in result:
        return None

    return result


def validate_http_endpoint(endpoint: Any) -> str:
    """
    Validate an HTTP(S) URL before transport.

    The adapter layer does not perform SSRF policy decisions itself, because
    enterprise deployments may require different allow/deny policies. URL
    syntactic validation is nevertheless mandatory here.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("Adapter endpoint must be a non-empty URL string")

    endpoint = endpoint.strip()

    try:
        parsed = urlparse(endpoint)
    except ValueError as exc:
        raise ValueError("Adapter endpoint is not a valid URL") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported HTTP endpoint scheme: {parsed.scheme!r}")

    if not parsed.netloc:
        raise ValueError("Adapter endpoint must contain a host")

    return endpoint


def traceparent_from_payload(
    payload: Mapping[str, Any] | None,
) -> str | None:
    """Extract a valid W3C traceparent without accepting arbitrary strings."""
    if not isinstance(payload, Mapping):
        return None

    span_context = payload.get("span_context")

    if not isinstance(span_context, Mapping):
        return None

    value = span_context.get("traceparent")

    if not isinstance(value, str):
        return None

    value = value.strip()

    parts = value.split("-")
    if len(parts) != 4:
        return None

    version, trace_id, span_id, flags = parts

    if len(version) != 2 or len(trace_id) != 32 or len(span_id) != 16:
        return None

    if len(flags) != 2:
        return None

    try:
        int(version, 16)
        int(trace_id, 16)
        int(span_id, 16)
        int(flags, 16)
    except ValueError:
        return None

    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None

    return value


def build_request_headers(
    payload: Mapping[str, Any] | None = None,
    *,
    headers: Mapping[str, Any] | None = None,
    accept: str | None = None,
    content_type: str | None = None,
) -> dict[str, str]:
    """
    Build common adapter headers.

    Caller-provided headers are accepted only as strings and are sanitized for
    CR/LF injection. W3C trace propagation is added independently.
    """
    result: dict[str, str] = {}

    traceparent = traceparent_from_payload(payload)
    if traceparent:
        result[TRACEPARENT_PREFIX] = traceparent

    if isinstance(headers, Mapping):
        for key, raw_value in headers.items():
            if not isinstance(key, str) or not key.strip():
                continue

            safe_value = _safe_header_value(raw_value)
            if safe_value is None:
                continue

            result[key.strip()] = safe_value

    if content_type:
        safe_content_type = _safe_header_value(content_type)
        if safe_content_type:
            result["Content-Type"] = safe_content_type

    if accept:
        safe_accept = _safe_header_value(accept)
        if safe_accept:
            result["Accept"] = safe_accept

    return result


def redact_mapping(
    value: Any,
    *,
    sensitive_keys: set[str] | None = None,
    max_depth: int = 8,
    _depth: int = 0,
) -> Any:
    """
    Redact credentials and common secrets for evidence/telemetry.

    This intentionally operates on copies and never mutates caller data.
    """
    keys = sensitive_keys or {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "client_secret",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "x-api-key",
        "anthropic_api_key",
        "openai_api_key",
        "gemini_api_key",
        "xai_api_key",
        "credentials",
    }

    if _depth >= max_depth:
        return "<max-depth>"

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for key, item in value.items():
            normalized_key = str(key).strip().lower()

            if normalized_key in keys or any(
                token in normalized_key
                for token in (
                    "api_key",
                    "apikey",
                    "secret",
                    "password",
                    "access_token",
                    "refresh_token",
                )
            ):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_mapping(
                    item,
                    sensitive_keys=keys,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                )

        return result

    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            redact_mapping(
                item,
                sensitive_keys=keys,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
            for item in list(value)[:1000]
        ]

    return value


# ---------------------------------------------------------------------------
# HTTP response helpers
# ---------------------------------------------------------------------------


async def read_response_bytes(
    response: aiohttp.ClientResponse,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> bytes:
    """
    Read a bounded HTTP response body.

    The response is not allowed to consume unbounded memory.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be > 0")

    body = bytearray()

    async for chunk in response.content.iter_chunked(64 * 1024):
        if not chunk:
            continue

        body.extend(chunk)

        if len(body) > max_bytes:
            raise RuntimeError(f"HTTP response exceeded maximum size ({max_bytes} bytes)")

    return bytes(body)


async def read_response_text(
    response: aiohttp.ClientResponse,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> str:
    """Read a bounded UTF-8 HTTP response body."""
    body = await read_response_bytes(response, max_bytes=max_bytes)
    return body.decode("utf-8", errors="replace")


async def read_response_json(
    response: aiohttp.ClientResponse,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allow_empty: bool = False,
) -> Any:
    """Read and decode a bounded JSON HTTP response."""
    body = await read_response_bytes(response, max_bytes=max_bytes)

    if not body:
        if allow_empty:
            return None
        raise RuntimeError("HTTP response body was empty")

    try:
        return json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError("HTTP response was not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HTTP response was not valid JSON: {exc}") from exc


def build_http_error(
    response: aiohttp.ClientResponse,
    *,
    message: str | None = None,
) -> aiohttp.ClientResponseError:
    """Create a stable aiohttp HTTP exception while preserving headers."""
    return aiohttp.ClientResponseError(
        request_info=response.request_info,
        history=response.history,
        status=response.status,
        message=message or response.reason or "HTTP request failed",
        headers=response.headers,
    )


def retry_after_seconds(
    response_or_exception: aiohttp.ClientResponse | BaseException,
) -> float | None:
    """
    Resolve Retry-After as either delay-seconds or RFC HTTP-date.
    """
    headers = getattr(response_or_exception, "headers", None)

    if not headers:
        return None

    raw = headers.get("Retry-After")
    if raw is None:
        return None

    raw = str(raw).strip()

    if not raw:
        return None

    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass

    try:
        retry_dt = parsedate_to_datetime(raw)

        if retry_dt.tzinfo is None:
            retry_dt = retry_dt.replace(tzinfo=UTC)

        return max(
            0.0,
            (retry_dt - datetime.now(UTC)).total_seconds(),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def is_retryable_http_status(status_code: int) -> bool:
    try:
        return int(status_code) in RETRYABLE_HTTP_STATUS_CODES
    except (TypeError, ValueError):
        return False


async def request_json(
    pool: AdapterSessionPool,
    *,
    method: str,
    url: str,
    payload: Any = None,
    headers: Mapping[str, Any] | None = None,
    timeout: float | aiohttp.ClientTimeout | None = None,
    cookies: Mapping[str, Any] | None = None,
    retry_codes: set[int] | frozenset[int] | None = None,
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    deadline: float | None = None,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    expected_statuses: set[int] | frozenset[int] | None = None,
) -> tuple[Any, int, dict[str, str]]:
    """
    Common bounded JSON HTTP request.

    This function intentionally does not normalize business/application states.
    It only handles transport, response decoding, and retry semantics.
    """
    adapter = BaseAdapter(name="http")

    async def _call() -> tuple[Any, int, dict[str, str]]:
        request_kwargs: dict[str, Any] = {
            "headers": {str(key): str(value) for key, value in (headers or {}).items()},
            "cookies": (
                {str(key): str(value) for key, value in cookies.items()}
                if isinstance(cookies, Mapping)
                else None
            ),
            "timeout": (
                timeout
                if isinstance(timeout, aiohttp.ClientTimeout)
                else aiohttp.ClientTimeout(total=coerce_timeout(timeout))
            ),
        }

        if payload is not None:
            request_kwargs["json"] = payload

        async with pool.session_request(
            method,
            validate_http_endpoint(url),
            **request_kwargs,
        ) as response:
            response_headers = dict(response.headers)

            body = await read_response_bytes(
                response,
                max_bytes=max_response_bytes,
            )

            try:
                decoded = json.loads(body.decode("utf-8")) if body else None
            except UnicodeDecodeError as exc:
                raise RuntimeError("HTTP JSON response was not valid UTF-8") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError("HTTP response was not valid JSON") from exc

            allowed = expected_statuses

            if allowed is not None:
                ok = response.status in allowed
            else:
                ok = 200 <= response.status < 300

            if not ok:
                detail = bounded_text(
                    decoded
                    if decoded is not None
                    else body.decode(
                        "utf-8",
                        errors="replace",
                    ),
                    max_bytes=4096,
                )

                raise build_http_error(
                    response,
                    message=detail,
                )

            return decoded, response.status, response_headers

    return await adapter.call_with_retry(
        _call,
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        retry_codes=retry_codes,
        deadline=deadline,
    )


async def iter_sse_events(
    content: AsyncIterator[bytes],
    *,
    max_event_bytes: int = DEFAULT_MAX_SSE_EVENT_BYTES,
) -> AsyncIterator[dict[str, str]]:
    """
    Standards-tolerant Server-Sent Events parser.

    Supports:
    - event:
    - data:
    - id:
    - retry:
    - comments
    - multiline data
    - blank-line dispatch
    """
    event_name = "message"
    event_id = ""
    retry = ""
    data_lines: list[str] = []
    event_bytes = 0

    async for raw_chunk in content:
        if not raw_chunk:
            continue

        text_chunk = raw_chunk.decode("utf-8", errors="replace")

        for raw_line in text_chunk.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")

            if line == "":
                if data_lines:
                    data = "\n".join(data_lines)

                    yield {
                        "event": event_name,
                        "id": event_id,
                        "retry": retry,
                        "data": data,
                    }

                event_name = "message"
                event_id = ""
                retry = ""
                data_lines = []
                event_bytes = 0
                continue

            if line.startswith(":"):
                continue

            event_bytes += len(line.encode("utf-8", errors="replace"))

            if event_bytes > max_event_bytes:
                raise RuntimeError(f"SSE event exceeded maximum size ({max_event_bytes} bytes)")

            field, separator, value = line.partition(":")

            if separator and value.startswith(" "):
                value = value[1:]

            if field == "event":
                event_name = value
            elif field == "id":
                event_id = value
            elif field == "retry":
                retry = value
            elif field == "data":
                data_lines.append(value)

    if data_lines:
        yield {
            "event": event_name,
            "id": event_id,
            "retry": retry,
            "data": "\n".join(data_lines),
        }


# ---------------------------------------------------------------------------
# Adapter execution context
# ---------------------------------------------------------------------------


class AdapterExecutionContext:
    """
    Lifecycle-scoped execution context shared by adapters.

    The context separates AgentV runtime metadata from the actual agent wire
    payload. Adapters may consume provider/framework configuration without
    forcing arbitrary transport adapters to receive internal runtime fields.
    """

    __slots__ = (
        "pool",
        "payload",
        "metadata",
        "span_context",
        "timeout",
    )

    def __init__(
        self,
        *,
        pool: AdapterSessionPool,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        span_context: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.pool = pool
        self.payload = dict(payload or {})
        self.metadata = dict(metadata or {})
        self.span_context = dict(span_context) if isinstance(span_context, Mapping) else None
        self.timeout = coerce_timeout(timeout)

    @property
    def request_headers(self) -> dict[str, str]:
        """Resolve caller-supplied headers plus validated trace propagation."""
        headers = self.payload.get("headers")
        if not isinstance(headers, Mapping):
            headers = self.metadata.get("headers")

        return build_request_headers(
            self.payload,
            headers=headers if isinstance(headers, Mapping) else None,
        )

    def provider_config(
        self,
        provider: str,
    ) -> dict[str, Any]:
        """Resolve provider-scoped configuration without mutating payload."""
        result: dict[str, Any] = {}

        provider_value = self.metadata.get(provider)

        if isinstance(provider_value, Mapping):
            result.update(provider_value)

        for key, value in self.payload.items():
            if key != "metadata":
                result[key] = value

        return result


# ---------------------------------------------------------------------------
# Lifecycle-safe aiohttp pooling
# ---------------------------------------------------------------------------


class AdapterSessionPool:
    """
    Lifecycle-scoped aiohttp connection pool.

    A runtime/session/worker owns one pool and closes it explicitly.

    aiohttp ClientSession instances are event-loop affine. If an adapter is
    reused across event loops, the old session is discarded and recreated.
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

        if isinstance(timeout, aiohttp.ClientTimeout):
            self._timeout = timeout
        else:
            self._timeout = aiohttp.ClientTimeout(total=coerce_timeout(timeout))

        self._connection_limit = max(1, int(connection_limit))
        self._dns_cache_ttl = max(0, int(dns_cache_ttl))
        self._keepalive_timeout = max(
            0.0,
            float(keepalive_timeout),
        )
        self._trust_env = bool(trust_env)
        self._headers = dict(headers or {})

    @staticmethod
    def _current_loop() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    @staticmethod
    def _session_loop(
        session: aiohttp.ClientSession | None,
    ) -> asyncio.AbstractEventLoop | None:
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

    async def _close_session(
        self,
        session: aiohttp.ClientSession | None,
    ) -> None:
        if session is None or session.closed:
            return

        try:
            await session.close()
        except Exception:
            logger.debug(
                "Adapter session close failed",
                exc_info=True,
            )

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

    def session_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ):
        """
        Return an aiohttp request context manager.

        The session is resolved lazily inside the async context manager so the
        lifecycle remains loop-safe.
        """
        return _AdapterRequestContext(
            pool=self,
            method=method,
            url=url,
            kwargs=kwargs,
        )

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """
        Compatibility request method.

        Prefer `async with pool.session_request(...)`.
        """
        session = await self.get_session()
        return await session.request(
            method,
            url,
            **kwargs,
        )

    async def close(self) -> None:
        async with self._lock:
            session = self._session
            self._session = None

            if session is not None:
                await self._close_session(session)

    @property
    def session(self) -> aiohttp.ClientSession | None:
        return self._session


class _AdapterRequestContext:
    """Async context manager that resolves a lifecycle-owned ClientSession."""

    __slots__ = (
        "_pool",
        "_method",
        "_url",
        "_kwargs",
        "_context",
        "_response",
    )

    def __init__(
        self,
        *,
        pool: AdapterSessionPool,
        method: str,
        url: str,
        kwargs: dict[str, Any],
    ) -> None:
        self._pool = pool
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._context = None
        self._response = None

    async def __aenter__(self) -> aiohttp.ClientResponse:
        session = await self._pool.get_session()

        self._context = session.request(
            self._method,
            self._url,
            **self._kwargs,
        )

        self._response = await self._context.__aenter__()
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self._context is None:
            return False

        return await self._context.__aexit__(
            exc_type,
            exc,
            tb,
        )


# ---------------------------------------------------------------------------
# Backwards-compatible session facade
# ---------------------------------------------------------------------------


class SessionManager:
    """
    Compatibility facade around a process-local default AdapterSessionPool.

    New execution paths should inject AdapterSessionPool directly.
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
        Reset the compatibility facade.

        Call close_all() first when the caller owns an active lifecycle.
        """
        cls._pool = AdapterSessionPool()
        cls._session = None

    @classmethod
    def pool(cls) -> AdapterSessionPool:
        return cls._pool


# ---------------------------------------------------------------------------
# Retry infrastructure
# ---------------------------------------------------------------------------


class AdapterRetryError(RuntimeError):
    """Raised when retry execution exceeds an explicit adapter deadline."""


class BaseAdapter:
    """
    Shared adapter resilience implementation.

    Retry behavior:
    - transient HTTP statuses
    - connection failures
    - timeouts
    - exponential backoff with full jitter
    - Retry-After support
    - explicit retry deadline
    - cancellation propagation
    """

    DEFAULT_RETRY_CODES = RETRYABLE_HTTP_STATUS_CODES

    def __init__(
        self,
        name: str,
        *,
        session_pool: AdapterSessionPool | None = None,
    ) -> None:
        if not str(name).strip():
            raise ValueError("Adapter name must be non-empty.")

        self.name = str(name)
        self.session_pool = session_pool

        self.max_retries = max(
            0,
            int(
                getattr(
                    config,
                    "ADAPTER_MAX_RETRIES",
                    2,
                )
            ),
        )

        self.retry_delay = max(
            0.0,
            float(
                getattr(
                    config,
                    "ADAPTER_RETRY_DELAY",
                    0.25,
                )
            ),
        )

        self.max_retry_delay = max(
            self.retry_delay,
            float(
                getattr(
                    config,
                    "ADAPTER_MAX_RETRY_DELAY",
                    30.0,
                )
            ),
        )

    def get_pool(self) -> AdapterSessionPool:
        """
        Return the explicitly injected pool or the compatibility facade pool.
        """
        return self.session_pool or SessionManager.pool()

    async def get_session(self) -> aiohttp.ClientSession:
        """Resolve the adapter's lifecycle-owned HTTP session."""
        return await self.get_pool().get_session()

    def provider_retry_attempts(
        self,
        payload: Mapping[str, Any],
        *,
        stream: bool = False,
    ) -> int:
        """Return a replay-safe attempt count for provider generation calls.

        Generation POSTs can have side effects even when a transport error is
        reported to the caller.  They are therefore single-attempt unless the
        caller explicitly marks the request replay-safe with an idempotency
        key or ``retry_idempotent``.  Streams are never replayed because a
        partial stream may already have been observed.
        """
        if stream:
            return 1

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        replay_safe = bool(
            payload.get("retry_idempotent")
            or metadata.get("retry_idempotent")
            or payload.get("idempotency_key")
            or metadata.get("idempotency_key")
        )
        return self.max_retries + 1 if replay_safe else 1

    @staticmethod
    def _retry_after_seconds(
        exc: aiohttp.ClientResponseError,
    ) -> float | None:
        return retry_after_seconds(exc)

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
                aiohttp.ServerDisconnectedError,
            ),
        )

    def _backoff_seconds(
        self,
        retry_number: int,
        *,
        base_delay: float,
        max_delay: float,
    ) -> float:
        cap = min(
            max_delay,
            base_delay * (2 ** max(0, retry_number - 1)),
        )

        if cap <= 0:
            return 0.0

        return random.SystemRandom().uniform(
            0.0,
            cap,
        )

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
        Execute an async operation with bounded retries.

        deadline is a total retry-window in seconds rather than a per-attempt
        timeout. Per-request network timeouts remain the responsibility of the
        HTTP client/request itself.
        """
        total_attempts = self.max_retries + 1 if max_attempts is None else int(max_attempts)

        if total_attempts <= 0:
            raise ValueError("max_attempts must be >= 1.")

        initial_delay = self.retry_delay if base_delay is None else max(0.0, float(base_delay))

        retry_max_delay = max(
            initial_delay,
            self.max_retry_delay if max_delay is None else float(max_delay),
        )

        effective_retry_codes = (
            set(self.DEFAULT_RETRY_CODES)
            if retry_codes is None
            else {int(code) for code in retry_codes}
        )

        started = time.monotonic()

        for attempt in range(
            1,
            total_attempts + 1,
        ):
            try:
                return await func(
                    *args,
                    **kwargs,
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                if attempt >= total_attempts:
                    raise

                if not self._is_retryable_exception(
                    exc,
                    effective_retry_codes,
                ):
                    raise

                elapsed = time.monotonic() - started

                remaining = None

                if deadline is not None:
                    deadline_seconds = float(deadline)
                    remaining = deadline_seconds - elapsed

                    if remaining <= 0:
                        raise AdapterRetryError(
                            f"Adapter '{self.name}' retry deadline exceeded "
                            f"after {attempt} attempt(s)."
                        ) from exc

                retry_after = None

                if (
                    respect_retry_after
                    and isinstance(
                        exc,
                        aiohttp.ClientResponseError,
                    )
                    and exc.status in effective_retry_codes
                ):
                    retry_after = self._retry_after_seconds(exc)

                delay = (
                    retry_after
                    if retry_after is not None
                    else self._backoff_seconds(
                        attempt,
                        base_delay=initial_delay,
                        max_delay=retry_max_delay,
                    )
                )

                if remaining is not None:
                    delay = min(
                        delay,
                        max(0.0, remaining),
                    )

                logger.warning(
                    "[Adapter:%s] transient failure on attempt %d/%d: %s; retrying in %.3fs",
                    self.name,
                    attempt,
                    total_attempts,
                    self._format_exception(exc),
                    delay,
                )

                if delay > 0:
                    await asyncio.sleep(delay)

        raise AssertionError("Unreachable retry state.")

    @staticmethod
    def _format_exception(
        exc: BaseException,
    ) -> str:
        if isinstance(
            exc,
            aiohttp.ClientResponseError,
        ):
            return f"HTTP {exc.status}: {exc.message or type(exc).__name__}"

        return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# LangChain / LangGraph telemetry
# ---------------------------------------------------------------------------


class AESCallbackHandler(BaseCallbackHandler):
    """
    Standardized LangChain/LangGraph telemetry bridge.

    Emits hashes/type summaries instead of raw prompts or state wherever
    possible, minimizing telemetry data-exfiltration risk.
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

    def _emit(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        payload.setdefault(
            "adapter",
            self.adapter_name,
        )
        payload.setdefault(
            "id",
            self.identifier,
        )

        if self.span_context is None:
            emit(
                event_name,
                payload,
            )
        else:
            emit(
                event_name,
                payload,
                span_context=self.span_context,
            )

    @staticmethod
    def _safe_type_summary(
        value: Any,
    ) -> str:
        if value is None:
            return "NoneType"

        return type(value).__name__

    @classmethod
    def _state_hash_and_summary(
        cls,
        inputs: Any,
    ) -> tuple[str | None, Any]:
        try:
            canonical = canonical_json(
                inputs,
                ensure_ascii=False,
            )

            return (
                crypto.checksum(canonical),
                cls._summarize_inputs(inputs),
            )
        except Exception:
            logger.debug(
                "State hashing failed",
                exc_info=True,
            )
            return (
                None,
                {"error": "serialization_failed"},
            )

    @classmethod
    def _summarize_inputs(
        cls,
        inputs: Any,
    ) -> Any:
        if isinstance(inputs, Mapping):
            return {str(key): cls._safe_type_summary(value) for key, value in inputs.items()}

        if isinstance(inputs, (list, tuple)):
            return {
                "container": type(inputs).__name__,
                "length": len(inputs),
                "item_types": [cls._safe_type_summary(value) for value in list(inputs)[:20]],
            }

        return cls._safe_type_summary(inputs)

    @staticmethod
    def _extract_usage(
        response: Any,
    ) -> dict[str, int]:
        candidates: list[Mapping[str, Any]] = []

        llm_output = getattr(
            response,
            "llm_output",
            None,
        )

        if isinstance(llm_output, Mapping):
            token_usage = llm_output.get("token_usage")

            if isinstance(token_usage, Mapping):
                candidates.append(token_usage)

            candidates.append(llm_output)

        response_metadata = getattr(
            response,
            "response_metadata",
            None,
        )

        if isinstance(response_metadata, Mapping):
            usage = response_metadata.get("usage")

            if isinstance(usage, Mapping):
                candidates.append(usage)

            candidates.append(response_metadata)

        usage_metadata = getattr(
            response,
            "usage_metadata",
            None,
        )

        if isinstance(
            usage_metadata,
            Mapping,
        ):
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

                    if isinstance(
                        value,
                        (int, float),
                    ):
                        normalized[target] = int(value)
                        break

                if target in normalized:
                    break

        if "total_tokens" not in normalized:
            prompt = normalized.get(
                "prompt_tokens",
                0,
            )
            completion = normalized.get(
                "completion_tokens",
                0,
            )

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
                "chain_name": (
                    serialized.get("name")
                    if isinstance(
                        serialized,
                        Mapping,
                    )
                    else None
                ),
            },
        )

    def on_chain_end(
        self,
        outputs: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.CHAIN_END,
            {"output_type": self._safe_type_summary(outputs)},
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

        if isinstance(
            serialized,
            Mapping,
        ):
            raw_id = serialized.get("id")

            if (
                isinstance(
                    raw_id,
                    (list, tuple),
                )
                and raw_id
            ):
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
            {"output_type": self._safe_type_summary(outputs)},
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

        if isinstance(
            serialized,
            Mapping,
        ):
            model_name = serialized.get("name") or serialized.get("id")

        self._emit(
            CoreEvents.ADAPTER_DEBUG,
            {
                "message": (f"LLM Start: {len(prompts or [])} prompt(s)"),
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

        if isinstance(
            serialized,
            Mapping,
        ):
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
        tool = getattr(
            action,
            "tool",
            None,
        )
        tool_input = getattr(
            action,
            "tool_input",
            None,
        )

        self._emit(
            CoreEvents.ACTION_START,
            {
                "tool_name": (str(tool) if tool is not None else None),
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
        return_values = getattr(
            finish,
            "return_values",
            None,
        )

        self._emit(
            CoreEvents.ACTION_END,
            {"return_type": self._safe_type_summary(return_values)},
        )


# ---------------------------------------------------------------------------
# Common output/action normalization
# ---------------------------------------------------------------------------


class DualNormalizationHub:
    """
    Canonical adapter response/action normalization.

    Precedence:
        transport failure
        explicit override
        declared schema mapping
        response status/state heuristics
        explicit content
        configured default
        empty response -> error
    """

    POLLING_KEYWORDS = tuple(
        str(k).strip().lower()
        for k in getattr(
            config,
            "POLLING_KEYWORDS",
            (),
        )
        if str(k).strip()
    )

    HITL_KEYWORDS = tuple(
        str(k).strip().lower()
        for k in getattr(
            config,
            "HITL_KEYWORDS",
            (),
        )
        if str(k).strip()
    )

    TERMINAL_KEYWORDS = tuple(
        str(k).strip().lower()
        for k in getattr(
            config,
            "TERMINAL_KEYWORDS",
            (),
        )
        if str(k).strip()
    )

    ERROR_KEYWORDS = tuple(
        str(k).strip().lower()
        for k in getattr(
            config,
            "ERROR_KEYWORDS",
            (),
        )
        if str(k).strip()
    )

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

        return "final_answer"

    @classmethod
    def validate_action(
        cls,
        action: Any,
    ) -> str | None:
        if action is None:
            return None

        action_str = str(action).strip().lower()

        if action_str in cls.VALID_ACTIONS:
            return action_str

        return None

    _validate_action = validate_action

    @classmethod
    def extract_status_value(
        cls,
        response: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        for key in cls.STATUS_FIELDS:
            if key not in response:
                continue

            value = response.get(key)

            if value is not None:
                return (
                    key,
                    str(value),
                )

        for key, value in response.items():
            key_lower = str(key).lower()

            if any(
                field in key_lower
                for field in (
                    "status",
                    "state",
                    "result",
                )
            ):
                if value is not None:
                    return (
                        str(key),
                        str(value),
                    )

        return None, None

    _extract_status_value = extract_status_value

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
        if response is None:
            response = {}

        if not isinstance(
            response,
            Mapping,
        ):
            return "error"

        try:
            status_code_int = int(status_code)
        except (TypeError, ValueError):
            status_code_int = 500

        if status_code_int >= 400:
            return "error"

        if overrides:
            for condition, action in overrides.items():
                normalized_action = cls.validate_action(action)

                if normalized_action is None:
                    logger.warning(
                        "Ignoring invalid adapter override action %r for %r.",
                        action,
                        condition,
                    )
                    continue

                normalized_condition = str(condition).strip().lower()

                for key in cls.STATUS_FIELDS:
                    if key not in response:
                        continue

                    value = response.get(key)

                    if value is not None and str(value).strip().lower() == normalized_condition:
                        return normalized_action

        if schema:
            field = str(
                schema.get(
                    "status_field",
                    "status",
                )
            )
            mapping = schema.get(
                "mapping",
                {},
            )

            if (
                isinstance(
                    mapping,
                    Mapping,
                )
                and field in response
            ):
                value = response.get(field)

                if value is not None:
                    mapped = mapping.get(str(value).lower())
                    normalized_action = cls.validate_action(mapped)

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

        field, status_value = cls.extract_status_value(response)

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

        for key in (
            "content",
            "output",
            "answer",
            "message",
            "text",
        ):
            value = response.get(key)

            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            return "final_answer"

        if response:
            normalized_default = cls.validate_action(default_action)

            if normalized_default:
                return normalized_default

        return "error"


__all__ = [
    "AdapterExecutionContext",
    "AdapterRetryError",
    "AdapterSessionPool",
    "AESCallbackHandler",
    "BaseAdapter",
    "DualNormalizationHub",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_MAX_SSE_EVENT_BYTES",
    "RETRYABLE_HTTP_STATUS_CODES",
    "SessionManager",
    "build_http_error",
    "build_request_headers",
    "bounded_text",
    "canonical_json",
    "coerce_timeout",
    "is_mapping",
    "is_retryable_http_status",
    "iter_sse_events",
    "json_safe",
    "read_response_bytes",
    "read_response_json",
    "read_response_text",
    "redact_mapping",
    "request_json",
    "retry_after_seconds",
    "serialize_json_bytes",
    "traceparent_from_payload",
    "validate_http_endpoint",
]
