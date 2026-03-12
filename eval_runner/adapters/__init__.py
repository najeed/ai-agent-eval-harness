
"""
eval_runner/adapters/__init__.py

Standard adapters for agent communication protocols.
Supports HTTP (default), Local Subprocess, and Socket communication.
Also acts as a package container for ecosystem-specific adapters.
"""

import json
import asyncio
import subprocess
import sys
from typing import Dict, Any, Optional
from .. import config

async def http_adapter(payload: dict, url: str):
    """Call an agent over HTTP (default)."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT)
        ) as response:
            response.raise_for_status()
            return await response.json()

async def local_subprocess_adapter(payload: dict, command: str):
    """
    Call an agent by spawning a local subprocess.
    Sends JSON payload to stdin and reads JSON response from stdout.
    """
    process = await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    input_data = json.dumps(payload).encode()
    stdout, stderr = await process.communicate(input=input_data)

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        raise RuntimeError(f"Agent subprocess failed (exit code {process.returncode}): {error_msg}")

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        raise RuntimeError(f"Agent subprocess returned invalid JSON: {stdout.decode()}")

async def socket_adapter(payload: dict, address: str):
    """
    Call an agent over a Unix domain socket or TCP socket.
    Format: 'unix:/path/to/socket' or 'tcp:host:port'
    """
    if address.startswith("unix:"):
        path = address.replace("unix:", "")
        reader, writer = await asyncio.open_unix_connection(path)
    elif address.startswith("tcp:"):
        parts = address.replace("tcp:", "").split(":")
        host = parts[0]
        port = int(parts[1])
        reader, writer = await asyncio.open_connection(host, port)
    else:
        raise ValueError(f"Unsupported socket address format: {address}")

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
        except Exception:
            pass

