"""
eval_runner/adapters/__init__.py

Authoritative transport adapters for AgentV agent execution.

Supported protocols:
    - http:    JSON-over-HTTP POST
    - sse:     JSON-over-HTTP POST with Server-Sent Events response
    - local:   local subprocess over stdin/stdout
    - socket:  TCP or Unix-domain socket with newline-delimited JSON

Design requirements:
    - deterministic wire contracts
    - explicit endpoint validation
    - bounded execution time and response size
    - lifecycle-safe connection pooling through common.py
    - retry only when invocation replay is explicitly safe
    - structured error propagation
    - validated W3C trace propagation
    - no shell=True
    - no synthetic/mock success responses
    - no silent protocol fallback
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from collections.abc import Mapping
from typing import Any

import aiohttp

from .. import config
from .common import (
    AdapterSessionPool,
    BaseAdapter,
    SessionManager,
    build_request_headers,
    iter_sse_events,
    validate_http_endpoint,
)

DEFAULT_MAX_RESPONSE_BYTES = int(os.getenv("ADAPTER_MAX_RESPONSE_BYTES", str(16 * 1024 * 1024)))
DEFAULT_MAX_REQUEST_BYTES = int(os.getenv("ADAPTER_MAX_REQUEST_BYTES", str(4 * 1024 * 1024)))
DEFAULT_MAX_STDERR_BYTES = int(os.getenv("ADAPTER_MAX_STDERR_BYTES", str(1024 * 1024)))
DEFAULT_SOCKET_MAX_LINE_BYTES = int(
    os.getenv("ADAPTER_MAX_SOCKET_LINE_BYTES", str(16 * 1024 * 1024))
)
DEFAULT_STREAM_READ_CHUNK_BYTES = int(os.getenv("ADAPTER_STREAM_READ_CHUNK_BYTES", str(64 * 1024)))

_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Shared protocol helpers
# ---------------------------------------------------------------------------


def _effective_timeout(kwargs: Mapping[str, Any] | None = None) -> float:
    """Resolve the authoritative per-invocation adapter timeout."""
    if kwargs:
        value = kwargs.get("timeout")
        if value is not None:
            try:
                resolved = float(value)
                if resolved > 0:
                    return resolved
            except (TypeError, ValueError):
                pass

    return float(config.DEFAULT_ADAPTER_TIMEOUT)


def _json_bytes(payload: Any) -> bytes:
    """Serialize a wire payload deterministically."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _ensure_request_size(payload: Any) -> bytes:
    """Serialize and enforce the adapter request-size boundary."""
    body = _json_bytes(payload)

    if len(body) > DEFAULT_MAX_REQUEST_BYTES:
        raise ValueError(
            f"Adapter request exceeds maximum configured size ({DEFAULT_MAX_REQUEST_BYTES} bytes)"
        )

    return body


def _decode_json_object(body: bytes, *, protocol: str) -> dict[str, Any]:
    """Decode one bounded JSON object and reject invalid response shapes."""
    if len(body) > DEFAULT_MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"{protocol} response exceeded maximum size ({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
        )

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{protocol} response was not valid UTF-8") from exc

    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{protocol} response was not valid JSON: {exc}") from exc

    if not isinstance(decoded, dict):
        raise RuntimeError(
            f"{protocol} adapter requires a JSON object response, got {type(decoded).__name__}"
        )

    return decoded


def _build_headers(
    payload: Mapping[str, Any],
    *,
    accept: str,
    content_type: str = "application/json",
) -> dict[str, str]:
    """
    Delegate header construction to common.py.

    Adapter-specific headers are deliberately restricted to protocol semantics.
    """
    headers = dict(build_request_headers(payload))
    headers.setdefault("Content-Type", content_type)
    headers["Accept"] = accept
    return headers


def _retry_attempts(kwargs: Mapping[str, Any]) -> int:
    """
    Agent invocation is a POST and may be non-idempotent.

    Automatic retry is therefore disabled unless the caller explicitly marks
    the invocation replay-safe with an idempotency key.
    """
    requested = kwargs.get("max_attempts")

    try:
        requested_attempts = int(requested) if requested is not None else 1
    except (TypeError, ValueError):
        requested_attempts = 1

    requested_attempts = max(1, requested_attempts)

    idempotency_key = kwargs.get("idempotency_key")
    if isinstance(idempotency_key, str) and idempotency_key.strip():
        return requested_attempts

    return 1


def _with_idempotency_header(
    headers: Mapping[str, str],
    *,
    idempotency_key: Any,
) -> dict[str, str]:
    """Add an explicit replay-safety marker when supplied by the caller."""
    result = dict(headers)

    if isinstance(idempotency_key, str) and idempotency_key.strip():
        result.setdefault("Idempotency-Key", idempotency_key.strip())

    return result


async def _raise_for_http_failure(
    response: aiohttp.ClientResponse,
    *,
    protocol: str,
) -> None:
    """Raise a structured HTTP error without converting failure into success."""
    if response.status < 400:
        return

    body = await response.read()
    detail = body[:4096].decode("utf-8", errors="replace").strip()

    raise aiohttp.ClientResponseError(
        request_info=response.request_info,
        history=response.history,
        status=response.status,
        message=detail or response.reason or f"{protocol} request failed",
        headers=response.headers,
    )


async def _request_json_once(
    session: aiohttp.ClientSession,
    *,
    payload: Mapping[str, Any],
    endpoint: str,
    timeout: float,
    headers: Mapping[str, str],
    protocol: str,
) -> dict[str, Any]:
    """Execute one bounded JSON POST without transport retries."""
    _ensure_request_size(payload)

    async with session.post(
        endpoint,
        json=payload,
        headers=dict(headers),
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as response:
        await _raise_for_http_failure(response, protocol=protocol)
        body = await response.read()

    return _decode_json_object(body, protocol=protocol)


async def _execute_with_retry(
    *,
    adapter_name: str,
    operation,
    max_attempts: int,
) -> Any:
    """
    Use the common retry implementation while preserving POST idempotency
    semantics at the protocol layer.
    """
    adapter = BaseAdapter(adapter_name)

    return await adapter.call_with_retry(
        operation,
        max_attempts=max_attempts,
        retry_codes=set(_RETRYABLE_HTTP_STATUS),
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


async def http_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over HTTP.

    Contract:
        POST <endpoint>
        Content-Type: application/json
        Body: exact agent wire payload
        Response: JSON object
    """
    resolved_endpoint = endpoint or config.AGENT_API_URL

    if not resolved_endpoint:
        raise ValueError("HTTP adapter requires an endpoint")

    validate_http_endpoint(resolved_endpoint)

    timeout = _effective_timeout(kwargs)

    headers = _build_headers(
        payload,
        accept="application/json",
    )
    headers = _with_idempotency_header(
        headers,
        idempotency_key=kwargs.get("idempotency_key"),
    )

    max_attempts = _retry_attempts(kwargs)

    pool = kwargs.get("session_pool")
    if not isinstance(pool, AdapterSessionPool):
        pool = None

    async def operation() -> dict[str, Any]:
        session = (
            await pool.get_session() if pool is not None else await SessionManager.get_session()
        )

        return await _request_json_once(
            session,
            payload=payload,
            endpoint=resolved_endpoint,
            timeout=timeout,
            headers=headers,
            protocol="HTTP",
        )

    return await _execute_with_retry(
        adapter_name="http",
        operation=operation,
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# Local subprocess
# ---------------------------------------------------------------------------


def _resolve_local_endpoint(endpoint: str | None) -> str:
    """Resolve the subprocess command from endpoint or environment."""
    value = endpoint or os.getenv("AGENT_LOCAL_CMD")

    if not value or not value.strip():
        raise ValueError("Local adapter requires an agent command via endpoint or AGENT_LOCAL_CMD")

    return value.strip()


def _resolve_local_command(endpoint: str | None) -> list[str]:
    """Parse a subprocess command without invoking a shell."""
    command = _resolve_local_endpoint(endpoint)
    args = shlex.split(command, posix=(os.name != "nt"))

    if not args:
        raise ValueError("Local adapter command resolved to an empty argument list")

    if args[0].lower().endswith(".py"):
        args.insert(0, sys.executable)

    return args


async def _read_process_stream_bounded(
    stream: asyncio.StreamReader,
    *,
    limit: int,
) -> bytes:
    """Read a subprocess stream without permitting unbounded buffering."""
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await stream.read(DEFAULT_STREAM_READ_CHUNK_BYTES)

        if not chunk:
            break

        total += len(chunk)

        if total > limit:
            raise RuntimeError(f"Subprocess stream exceeded maximum size ({limit} bytes)")

        chunks.append(chunk)

    return b"".join(chunks)


async def _run_local_process(
    *,
    command: list[str],
    payload: Mapping[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Run a local process with bounded stdout/stderr and deterministic teardown."""
    request_body = _ensure_request_size(payload)

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_task = asyncio.create_task(
        _read_process_stream_bounded(
            process.stdout,
            limit=DEFAULT_MAX_RESPONSE_BYTES,
        )
    )
    stderr_task = asyncio.create_task(
        _read_process_stream_bounded(
            process.stderr,
            limit=DEFAULT_MAX_STDERR_BYTES,
        )
    )

    try:
        process.stdin.write(request_body)
        await process.stdin.drain()
        process.stdin.close()

        await asyncio.wait_for(
            process.wait(),
            timeout=timeout,
        )

        stdout, stderr = await asyncio.gather(
            stdout_task,
            stderr_task,
        )

    except asyncio.CancelledError:
        stdout_task.cancel()
        stderr_task.cancel()

        try:
            process.kill()
        except ProcessLookupError:
            pass

        await process.wait()
        await asyncio.gather(
            stdout_task,
            stderr_task,
            return_exceptions=True,
        )
        raise

    except TimeoutError as exc:
        stdout_task.cancel()
        stderr_task.cancel()

        try:
            process.kill()
        except ProcessLookupError:
            pass

        await process.wait()
        await asyncio.gather(
            stdout_task,
            stderr_task,
            return_exceptions=True,
        )

        raise TimeoutError(f"Local subprocess timed out after {timeout:.1f}s") from exc

    except Exception:
        stdout_task.cancel()
        stderr_task.cancel()

        try:
            process.kill()
        except ProcessLookupError:
            pass

        await process.wait()
        await asyncio.gather(
            stdout_task,
            stderr_task,
            return_exceptions=True,
        )
        raise

    if process.returncode != 0:
        error_text = stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise RuntimeError(
            f"Agent subprocess failed with exit code {process.returncode}"
            + (f": {error_text}" if error_text else "")
        )

    return _decode_json_object(
        stdout,
        protocol="local subprocess",
    )


async def local_subprocess_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent as a local subprocess.

    Wire contract:
        stdin  -> one JSON object
        stdout -> one JSON object
    """
    command = _resolve_local_command(endpoint)
    timeout = _effective_timeout(kwargs)

    return await _run_local_process(
        command=command,
        payload=payload,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Socket
# ---------------------------------------------------------------------------


def _resolve_socket_endpoint(endpoint: str | None) -> str:
    """Resolve socket address from endpoint or environment."""
    value = endpoint or os.getenv("AGENT_SOCKET_ADDR")

    if not value or not value.strip():
        raise ValueError("Socket adapter requires an address via endpoint or AGENT_SOCKET_ADDR")

    return value.strip()


def _parse_socket_address(
    endpoint: str,
) -> tuple[str, str | tuple[str, int]]:
    """
    Parse:

        unix:/path/to/socket
        tcp:host:port
        host:port
        [ipv6]:port
        tcp:[ipv6]:port
    """
    if endpoint.startswith("unix:"):
        path = endpoint[len("unix:") :].strip()

        if not path:
            raise ValueError("Unix socket path cannot be empty")

        return "unix", path

    value = endpoint[len("tcp:") :] if endpoint.startswith("tcp:") else endpoint

    if value.startswith("["):
        closing = value.find("]")

        if closing < 0:
            raise ValueError(f"Invalid IPv6 socket address: {endpoint}")

        host = value[1:closing]
        remainder = value[closing + 1 :]

        if not remainder.startswith(":"):
            raise ValueError(f"Invalid socket address: {endpoint}")

        port_text = remainder[1:]

    else:
        if ":" not in value:
            raise ValueError("TCP socket endpoint must use host:port or tcp:host:port")

        host, port_text = value.rsplit(":", 1)

    host = host.strip()

    if not host:
        raise ValueError("Socket host cannot be empty")

    try:
        port = int(port_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid socket port in endpoint: {endpoint}") from exc

    if not 1 <= port <= 65535:
        raise ValueError(f"Socket port out of range: {port}")

    return "tcp", (host, port)


async def _read_socket_json(
    reader: asyncio.StreamReader,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Read one bounded newline-delimited JSON object."""
    try:
        line = await asyncio.wait_for(
            reader.readline(),
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise TimeoutError("Socket adapter timed out waiting for agent response") from exc

    if not line:
        raise RuntimeError("Socket agent closed the connection without a response")

    if len(line) > DEFAULT_SOCKET_MAX_LINE_BYTES:
        raise RuntimeError(
            f"Socket response exceeded maximum size ({DEFAULT_SOCKET_MAX_LINE_BYTES} bytes)"
        )

    return _decode_json_object(
        line.rstrip(b"\r\n"),
        protocol="socket",
    )


async def socket_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over TCP or Unix-domain socket.

    Wire contract:
        request  = one UTF-8 JSON object + newline
        response = one UTF-8 JSON object + newline
    """
    resolved = _resolve_socket_endpoint(endpoint)
    socket_type, address = _parse_socket_address(resolved)
    timeout = _effective_timeout(kwargs)

    request = _ensure_request_size(payload) + b"\n"

    if len(request) > DEFAULT_SOCKET_MAX_LINE_BYTES:
        raise ValueError(
            "Socket request exceeds maximum configured size "
            f"({DEFAULT_SOCKET_MAX_LINE_BYTES} bytes)"
        )

    if socket_type == "unix":
        assert isinstance(address, str)

        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(
                address,
                limit=DEFAULT_SOCKET_MAX_LINE_BYTES,
            ),
            timeout=timeout,
        )

    else:
        assert isinstance(address, tuple)
        host, port = address

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host,
                port,
                limit=DEFAULT_SOCKET_MAX_LINE_BYTES,
            ),
            timeout=timeout,
        )

    try:
        writer.write(request)

        await asyncio.wait_for(
            writer.drain(),
            timeout=timeout,
        )

        return await _read_socket_json(
            reader,
            timeout=timeout,
        )

    except asyncio.CancelledError:
        raise

    except TimeoutError as exc:
        raise TimeoutError(f"Socket adapter timed out after {timeout:.1f}s") from exc

    finally:
        writer.close()

        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


async def _consume_sse(
    content: aiohttp.StreamReader,
    *,
    timeout: float,
) -> dict[str, Any]:
    """
    Consume an SSE stream without reconnecting.

    Agent invocation is not assumed to be replay-safe, so reconnecting an
    interrupted stream could execute the remote workflow more than once.
    """
    final: dict[str, Any] = {}
    content_chunks: list[str] = []
    tool_calls: list[Any] = []
    events: list[dict[str, Any]] = []

    terminal_event_seen = False
    last_event_id: str | None = None
    total_event_bytes = 0

    async for event in iter_sse_events(
        content,
        timeout=timeout,
    ):
        if not isinstance(event, Mapping):
            continue

        raw_data = event.get("data")
        event_data = str(raw_data) if raw_data is not None else ""

        total_event_bytes += len(event_data.encode("utf-8"))

        if total_event_bytes > DEFAULT_MAX_RESPONSE_BYTES:
            raise RuntimeError(
                f"SSE response exceeded maximum size ({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
            )

        if event.get("id"):
            last_event_id = str(event["id"])

        event_name = str(event.get("event") or "message")

        if event_data == "[DONE]":
            terminal_event_seen = True
            break

        if not event_data:
            continue

        event_record = {
            "event": event_name,
            "id": event.get("id"),
            "data": event_data,
        }
        events.append(event_record)

        try:
            decoded = json.loads(event_data)
        except json.JSONDecodeError:
            content_chunks.append(event_data)
            continue

        if not isinstance(decoded, Mapping):
            content_chunks.append(str(decoded))
            continue

        for key, value in decoded.items():
            if key in {"content", "text", "answer"}:
                if value is not None:
                    content_chunks.append(str(value))
                continue

            if key in {"tool_calls", "calls"}:
                if isinstance(value, list):
                    tool_calls.extend(value)
                else:
                    tool_calls.append(value)
                continue

            if key == "delta" and isinstance(value, Mapping):
                delta_content = value.get("content")
                if delta_content is not None:
                    content_chunks.append(str(delta_content))

                delta_text = value.get("text")
                if delta_text is not None:
                    content_chunks.append(str(delta_text))

                delta_tools = value.get("tool_calls")
                if isinstance(delta_tools, list):
                    tool_calls.extend(delta_tools)

                for delta_key, delta_value in value.items():
                    if delta_key not in {"content", "text", "tool_calls"}:
                        final.setdefault("delta", {})
                        if isinstance(final["delta"], dict):
                            final["delta"][delta_key] = delta_value
                continue

            final[key] = value

    if content_chunks:
        final["content"] = "".join(content_chunks)

    if tool_calls:
        final["tool_calls"] = tool_calls

    if last_event_id is not None:
        metadata = final.get("metadata")

        if not isinstance(metadata, dict):
            metadata = {}

        metadata["last_event_id"] = last_event_id
        final["metadata"] = metadata

    if events:
        metadata = final.get("metadata")

        if not isinstance(metadata, dict):
            metadata = {}

        metadata["event_count"] = len(events)
        final["metadata"] = metadata

    if not final:
        raise RuntimeError("SSE agent returned no usable events")

    if "status" not in final:
        final["status"] = "completed" if terminal_event_seen else "success"

    return final


async def sse_http_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over HTTP and require a Server-Sent Events response.

    A JSON response from an SSE endpoint is treated as a protocol violation,
    rather than silently accepted as a different protocol.
    """
    resolved_endpoint = endpoint or config.AGENT_API_URL

    if not resolved_endpoint:
        raise ValueError("SSE adapter requires an endpoint")

    validate_http_endpoint(resolved_endpoint)

    timeout = _effective_timeout(kwargs)

    headers = _build_headers(
        payload,
        accept="text/event-stream",
    )
    headers["Cache-Control"] = "no-cache"
    headers["Connection"] = "keep-alive"

    headers = _with_idempotency_header(
        headers,
        idempotency_key=kwargs.get("idempotency_key"),
    )

    max_attempts = _retry_attempts(kwargs)

    pool = kwargs.get("session_pool")
    if not isinstance(pool, AdapterSessionPool):
        pool = None

    async def operation() -> dict[str, Any]:
        session = (
            await pool.get_session() if pool is not None else await SessionManager.get_session()
        )

        async with session.post(
            resolved_endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            await _raise_for_http_failure(
                response,
                protocol="SSE",
            )

            content_type = response.headers.get(
                "Content-Type",
                "",
            ).lower()

            if "text/event-stream" not in content_type:
                body = await response.read()
                preview = body[:4096].decode(
                    "utf-8",
                    errors="replace",
                )

                raise RuntimeError(
                    "SSE endpoint returned an invalid Content-Type "
                    f"{content_type!r}; expected text/event-stream"
                    + (f". Body: {preview}" if preview else "")
                )

            return await _consume_sse(
                response.content,
                timeout=timeout,
            )

    return await _execute_with_retry(
        adapter_name="sse",
        operation=operation,
        max_attempts=max_attempts,
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def close_adapter_sessions() -> None:
    """
    Close the backwards-compatible shared adapter pool.

    Explicitly injected AdapterSessionPool instances remain owned by their
    caller and must be closed by that lifecycle owner.
    """
    await SessionManager.close_all()


__all__ = [
    "AdapterSessionPool",
    "BaseAdapter",
    "SessionManager",
    "close_adapter_sessions",
    "http_adapter",
    "sse_http_adapter",
    "local_subprocess_adapter",
    "socket_adapter",
]
