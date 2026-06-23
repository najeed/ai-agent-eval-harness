"""
eval_runner/adapters/__init__.py

Standard adapters for agent communication protocols.
Supports HTTP (default), Local Subprocess, and Socket communication.
Also acts as a package container for ecosystem-specific adapters.
"""

import asyncio
import json
import re
import shlex
from typing import Any, Dict, Optional  # noqa: F401, UP035

import aiohttp

from .. import config

# W3C traceparent standard regex: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
TRACEPARENT_REGEX = re.compile(r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")


async def http_adapter(payload: dict, endpoint: str, **kwargs):
    """Call an agent over HTTP (default)."""
    from .common import SessionManager

    session = await SessionManager.get_session()
    headers = {}
    if payload.get("span_context") and "traceparent" in payload["span_context"]:
        tp = payload["span_context"]["traceparent"]
        if isinstance(tp, str) and TRACEPARENT_REGEX.match(tp):
            headers["traceparent"] = tp

    async with session.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
    ) as response:
        response.raise_for_status()
        return await response.json()


async def local_subprocess_adapter(payload: dict, endpoint: str, **kwargs):
    """
    Call an agent by spawning a local subprocess.
    Sends JSON payload to stdin and reads JSON response from stdout.
    """
    # Secure Remediation (R0.2): Eliminate shell=True/shell=True context
    # shlex.split transforms "python agent.py --arg" into ["python", "agent.py", "--arg"]
    cmd_args = shlex.split(endpoint)
    process = await asyncio.create_subprocess_exec(
        *cmd_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    input_data = json.dumps(payload).encode()
    stdout, stderr = await process.communicate(input=input_data)

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        raise RuntimeError(f"Agent subprocess failed (exit code {process.returncode}): {error_msg}")

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        raise RuntimeError(f"Agent subprocess returned invalid JSON: {stdout.decode()}")  # noqa: B904


async def socket_adapter(payload: dict, endpoint: str, **kwargs):
    """
    Call an agent over a Unix domain socket or TCP socket.
    Format: 'unix:/path/to/socket' or 'tcp:host:port'
    """
    if endpoint.startswith("unix:"):
        path = endpoint.replace("unix:", "")
        reader, writer = await asyncio.open_unix_connection(path)
    elif endpoint.startswith("tcp:"):
        parts = endpoint.replace("tcp:", "").split(":")
        host = parts[0]
        port = int(parts[1])
        reader, writer = await asyncio.open_connection(host, port)
    else:
        raise ValueError(f"Unsupported socket address format: {endpoint}")

    try:
        input_data = json.dumps(payload).encode() + b"\n"
        writer.write(input_data)
        await writer.drain()

        # Read until newline
        response_data = await reader.readline()
        if not response_data:
            return {}
        return json.loads(response_data.decode())
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception as e:
            # Forensic visibility into cleanup failures
            import sys

            sys.stderr.write(f"   [Adapters] Warning: Socket cleanup failure: {e}\n")


async def sse_http_adapter(payload: dict, endpoint: str, **kwargs):
    """
    Call an agent over HTTP with SSE (Server-Sent Events) streaming support.
    Accumulates the stream into a final response.
    """
    from .common import SessionManager

    session = await SessionManager.get_session()
    headers = {"Accept": "text/event-stream"}
    if payload.get("span_context") and "traceparent" in payload["span_context"]:
        tp = payload["span_context"]["traceparent"]
        if isinstance(tp, str) and TRACEPARENT_REGEX.match(tp):
            headers["traceparent"] = tp

    async with session.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
    ) as response:
        response.raise_for_status()

        full_content = ""
        final_json = {}

        async for line in response.content:
            if not line:
                continue
            line_str = line.decode("utf-8").strip()

            if line_str.startswith("data:"):
                data = line_str[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    # Merge logic (AES v1.4 Standard)
                    if isinstance(chunk, dict):
                        final_json.update(chunk)
                        if "content" in chunk:
                            full_content += str(chunk["content"])
                    else:
                        full_content += str(chunk)
                except json.JSONDecodeError:
                    full_content += data

        if not final_json and full_content:
            return {"content": full_content, "status": "completed"}

        if full_content and "content" in final_json:
            final_json["content"] = full_content

        return final_json
