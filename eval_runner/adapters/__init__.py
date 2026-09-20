"""
eval_runner/adapters/__init__.py

Authoritative transport adapters for AgentV agent execution.

Supported protocols:
    - http:  JSON-over-HTTP POST
    - sse:   JSON-over-HTTP POST with Server-Sent Events response
    - local: local subprocess over stdin/stdout
    - socket: TCP or Unix-domain socket with newline-delimited JSON

Design requirements:
    - deterministic wire contracts
    - explicit endpoint validation
    - bounded execution time
    - structured error propagation
    - safe tracing propagation
    - no shell=True
    - no synthetic/mock success responses
    - bounded response sizes
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sys
from collections.abc import AsyncIterator, Mapping
from typing import Any

import aiohttp

from .. import config

# W3C Trace Context traceparent:
# version-trace-id-span-id-flags
TRACEPARENT_REGEX = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")

DEFAULT_MAX_RESPONSE_BYTES = int(os.getenv("ADAPTER_MAX_RESPONSE_BYTES", "16777216"))
DEFAULT_SOCKET_MAX_LINE_BYTES = int(os.getenv("ADAPTER_MAX_SOCKET_LINE_BYTES", "16777216"))

_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _effective_timeout(kwargs: Mapping[str, Any] | None = None) -> float:
    """Resolve the authoritative adapter timeout."""
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


def _trace_headers(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return validated W3C trace propagation headers."""
    headers: dict[str, str] = {}

    span_context = payload.get("span_context")
    if isinstance(span_context, Mapping):
        traceparent = span_context.get("traceparent")
        if isinstance(traceparent, str) and TRACEPARENT_REGEX.fullmatch(traceparent):
            headers["traceparent"] = traceparent

    return headers


def _request_headers(
    payload: Mapping[str, Any],
    *,
    accept: str | None = None,
) -> dict[str, str]:
    """
    Build transport headers.

    `headers` is intentionally opt-in and passed only when supplied by the
    caller. Trace propagation is always independently validated.
    """
    headers = _trace_headers(payload)

    configured_headers = payload.get("headers")
    if isinstance(configured_headers, Mapping):
        for key, value in configured_headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            headers[key] = value

    if accept:
        headers["Accept"] = accept

    return headers


def _decode_json_bytes(body: bytes, *, protocol: str) -> dict[str, Any]:
    """Decode a bounded JSON object and enforce the adapter response contract."""
    if len(body) > DEFAULT_MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"{protocol} response exceeded maximum size ({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
        )

    try:
        decoded = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{protocol} response was not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{protocol} response was not valid JSON: {exc}") from exc

    if not isinstance(decoded, dict):
        raise RuntimeError(
            f"{protocol} adapter requires a JSON object response, got {type(decoded).__name__}"
        )

    return decoded


def _retry_after_seconds(response: aiohttp.ClientResponse) -> float | None:
    """Resolve Retry-After when supplied by the remote service."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None

    return max(0.0, value)


async def _close_response_safely(response: aiohttp.ClientResponse) -> None:
    """Release an aiohttp response without masking the original failure."""
    try:
        response.release()
    except Exception:
        pass


async def _post_json_with_retry(
    payload: dict[str, Any],
    endpoint: str,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    accept: str = "application/json",
    max_attempts: int | None = None,
) -> tuple[int, Mapping[str, str], bytes]:
    """
    Execute an idempotency-aware bounded POST.

    Retries are limited to transient transport/status failures. The caller
    controls whether a request is safe to retry through `max_attempts`.
    """
    if not endpoint or not isinstance(endpoint, str):
        raise ValueError("Adapter endpoint must be a non-empty URL string")

    attempts = max(1, int(max_attempts or config.ADAPTER_MAX_RETRIES))
    retry_delay = max(0.0, float(config.ADAPTER_RETRY_DELAY))

    request_headers = dict(headers or {})
    request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", accept)

    session = await _get_session()
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        response: aiohttp.ClientResponse | None = None
        try:
            response = await session.post(
                endpoint,
                json=payload,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )

            if response.status < 400:
                body = await response.read()
                return response.status, dict(response.headers), body

            if response.status not in _RETRYABLE_HTTP_STATUS or attempt >= attempts:
                body = await response.read()
                detail = body[:4096].decode("utf-8", errors="replace")
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=detail or response.reason or "HTTP request failed",
                    headers=response.headers,
                )

            retry_after = _retry_after_seconds(response)
            await _close_response_safely(response)

            delay = retry_after
            if delay is None:
                delay = retry_delay * (2 ** (attempt - 1))

            if delay > 0:
                await asyncio.sleep(delay)

        except asyncio.CancelledError:
            if response is not None:
                await _close_response_safely(response)
            raise
        except aiohttp.ClientResponseError:
            if response is not None:
                await _close_response_safely(response)
            raise
        except (TimeoutError, aiohttp.ClientConnectionError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise

            delay = retry_delay * (2 ** (attempt - 1))
            if delay > 0:
                await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Adapter HTTP execution terminated without a response")


async def _get_session() -> aiohttp.ClientSession:
    """Resolve the shared connection pool lazily."""
    from .common import SessionManager

    return await SessionManager.get_session()


def _resolve_local_endpoint(endpoint: str | None) -> str:
    """Resolve local subprocess command from explicit endpoint or environment."""
    value = endpoint or os.getenv("AGENT_LOCAL_CMD")
    if not value or not value.strip():
        raise ValueError("Local adapter requires an agent command via endpoint or AGENT_LOCAL_CMD")
    return value.strip()


def _resolve_socket_endpoint(endpoint: str | None) -> str:
    """Resolve socket address from explicit endpoint or environment."""
    value = endpoint or os.getenv("AGENT_SOCKET_ADDR")
    if not value or not value.strip():
        raise ValueError("Socket adapter requires an address via endpoint or AGENT_SOCKET_ADDR")
    return value.strip()


def _parse_socket_address(endpoint: str) -> tuple[str, str | tuple[str, int]]:
    """
    Parse:
        unix:/path/to/socket
        tcp:host:port
        host:port
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
    """Read one bounded newline-delimited JSON response."""
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    except TimeoutError as exc:
        raise TimeoutError("Socket adapter timed out waiting for agent response") from exc

    if not line:
        raise RuntimeError("Socket agent closed the connection without a response")

    if len(line) > DEFAULT_SOCKET_MAX_LINE_BYTES:
        raise RuntimeError(
            f"Socket response exceeded maximum size ({DEFAULT_SOCKET_MAX_LINE_BYTES} bytes)"
        )

    return _decode_json_bytes(line.rstrip(b"\r\n"), protocol="socket")


async def http_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over HTTP.

    Wire contract:
        POST endpoint
        Content-Type: application/json
        Body: exact evaluation payload produced by the dispatcher
    """
    if not endpoint:
        endpoint = config.AGENT_API_URL

    if not endpoint:
        raise ValueError("HTTP adapter requires an endpoint")

    timeout = _effective_timeout(kwargs)
    headers = _request_headers(payload, accept="application/json")

    _status, _headers, body = await _post_json_with_retry(
        payload,
        endpoint,
        timeout=timeout,
        headers=headers,
        accept="application/json",
        max_attempts=kwargs.get("max_attempts"),
    )
    return _decode_json_bytes(body, protocol="HTTP")


async def local_subprocess_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent as a local subprocess.

    The command is parsed without invoking a shell. JSON is written to stdin;
    exactly one JSON object is expected on stdout.
    """
    command = _resolve_local_endpoint(endpoint)
    cmd_args = shlex.split(command, posix=(os.name != "nt"))

    if not cmd_args:
        raise ValueError("Local adapter command resolved to an empty argument list")

    # Convenience: executing a .py file directly uses the current interpreter.
    if cmd_args[0].lower().endswith(".py"):
        cmd_args.insert(0, sys.executable)

    timeout = _effective_timeout(kwargs)

    process = await asyncio.create_subprocess_exec(
        *cmd_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    input_data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=input_data),
            timeout=timeout,
        )
    except TimeoutError as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise TimeoutError(f"Local subprocess timed out after {timeout:.1f}s") from exc

    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Agent subprocess failed with exit code {process.returncode}"
            + (f": {error_text}" if error_text else "")
        )

    if len(stdout) > DEFAULT_MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"Local subprocess response exceeded maximum size ({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
        )

    return _decode_json_bytes(stdout, protocol="local subprocess")


async def socket_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over TCP or Unix-domain socket.

    Wire contract:
        one UTF-8 JSON object followed by '\\n'
        one UTF-8 JSON object returned followed by '\\n'
    """
    resolved = _resolve_socket_endpoint(endpoint)
    socket_type, address = _parse_socket_address(resolved)
    timeout = _effective_timeout(kwargs)

    if socket_type == "unix":
        assert isinstance(address, str)
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(address),
            timeout=timeout,
        )
    else:
        assert isinstance(address, tuple)
        host, port = address
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )

    try:
        request = (
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )

        if len(request) > DEFAULT_MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Socket request exceeds maximum configured size "
                f"({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
            )

        writer.write(request)
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        return await _read_socket_json(reader, timeout=timeout)

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


async def _iter_sse_events(
    content: aiohttp.StreamReader,
    *,
    timeout: float,
) -> AsyncIterator[dict[str, Any]]:
    """
    Parse an SSE stream according to the SSE line/event model.

    Event payloads are yielded as:
        {
            "event": str,
            "id": str | None,
            "retry": int | None,
            "data": str,
        }
    """
    event_name = "message"
    event_id: str | None = None
    retry: int | None = None
    data_lines: list[str] = []
    buffered_bytes = 0

    async def _yield_event() -> dict[str, Any] | None:
        nonlocal event_name, event_id, retry, data_lines

        if not data_lines:
            event_name = "message"
            event_id = None
            retry = None
            return None

        event = {
            "event": event_name,
            "id": event_id,
            "retry": retry,
            "data": "\n".join(data_lines),
        }

        event_name = "message"
        event_id = None
        retry = None
        data_lines = []
        return event

    while True:
        try:
            raw_line = await asyncio.wait_for(content.readline(), timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"SSE adapter timed out after {timeout:.1f}s") from exc

        if not raw_line:
            event = await _yield_event()
            if event is not None:
                yield event
            return

        buffered_bytes += len(raw_line)
        if buffered_bytes > DEFAULT_MAX_RESPONSE_BYTES:
            raise RuntimeError(
                f"SSE response exceeded maximum size ({DEFAULT_MAX_RESPONSE_BYTES} bytes)"
            )

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if line == "":
            event = await _yield_event()
            if event is not None:
                yield event
            continue

        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]

        if field == "event":
            event_name = value or "message"
        elif field == "id":
            event_id = value
        elif field == "retry":
            try:
                parsed_retry = int(value)
                if parsed_retry >= 0:
                    retry = parsed_retry
            except ValueError:
                pass
        elif field == "data":
            data_lines.append(value)


async def sse_http_adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute an agent over HTTP and consume a Server-Sent Events response.

    No automatic reconnect is performed because agent invocation is generally
    not idempotent; reconnecting could execute the target action twice.
    """
    if not endpoint:
        endpoint = config.AGENT_API_URL

    if not endpoint:
        raise ValueError("SSE adapter requires an endpoint")

    timeout = _effective_timeout(kwargs)
    headers = _request_headers(
        payload,
        accept="text/event-stream",
    )
    headers.setdefault("Cache-Control", "no-cache")

    session = await _get_session()

    async with session.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as response:
        if response.status >= 400:
            body = await response.read()
            detail = body[:4096].decode("utf-8", errors="replace")
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=detail or response.reason or "SSE request failed",
                headers=response.headers,
            )

        content_type = response.headers.get("Content-Type", "").lower()
        if "text/event-stream" not in content_type:
            body = await response.read()
            return _decode_json_bytes(body, protocol="SSE")

        accumulated_content: list[str] = []
        final_json: dict[str, Any] = {}
        terminal_event_seen = False
        last_event_id: str | None = None

        async for event in _iter_sse_events(response.content, timeout=timeout):
            event_data = event["data"]
            last_event_id = event.get("id") or last_event_id

            if event_data == "[DONE]":
                terminal_event_seen = True
                break

            if not event_data:
                continue

            try:
                decoded = json.loads(event_data)
            except json.JSONDecodeError:
                accumulated_content.append(event_data)
                continue

            if isinstance(decoded, dict):
                # Preserve all structured terminal/provider fields.
                for key, value in decoded.items():
                    if key == "content":
                        accumulated_content.append(str(value))
                    elif key == "delta" and isinstance(value, Mapping):
                        delta_content = value.get("content")
                        if delta_content is not None:
                            accumulated_content.append(str(delta_content))
                        else:
                            final_json[key] = value
                    else:
                        final_json[key] = value
            else:
                accumulated_content.append(str(decoded))

        if accumulated_content:
            final_json["content"] = "".join(accumulated_content)

        if last_event_id is not None:
            final_json.setdefault("metadata", {})
            if isinstance(final_json["metadata"], dict):
                final_json["metadata"]["last_event_id"] = last_event_id

        if not final_json:
            raise RuntimeError("SSE agent returned no usable events")

        final_json.setdefault("status", "completed" if terminal_event_seen else "success")
        return final_json


__all__ = [
    "http_adapter",
    "sse_http_adapter",
    "local_subprocess_adapter",
    "socket_adapter",
]
