import asyncio
import json

import pytest
from aiohttp import web

from eval_runner.adapters import sse_http_adapter


async def mock_sse_agent(request):
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={"Content-Type": "text/event-stream"},
    )
    await response.prepare(request)

    chunks = [
        {"content": "Hello", "status": "processing"},
        {"content": " world", "status": "processing"},
        {"content": "!", "status": "completed"},
        "[DONE]",
    ]

    for chunk in chunks:
        if chunk == "[DONE]":
            await response.write(b"data: [DONE]\n\n")
        else:
            data = json.dumps(chunk)
            await response.write(f"data: {data}\n\n".encode())
        await asyncio.sleep(0.01)

    return response


@pytest.fixture
async def sse_server(aiohttp_server):
    app = web.Application()
    app.router.add_post("/agent", mock_sse_agent)
    return await aiohttp_server(app)


@pytest.mark.asyncio
async def test_sse_http_adapter(sse_server):
    url = f"http://{sse_server.host}:{sse_server.port}/agent"
    payload = {"task": "test"}

    result = await sse_http_adapter(payload, url)

    assert result["content"] == "Hello world!"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_sse_http_adapter_raw_data(aiohttp_server):
    async def mock_raw_sse(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b"data: Part 1\n\n")
        await response.write(b"data: Part 2\n\n")
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application()
    app.router.add_post("/agent", mock_raw_sse)
    server = await aiohttp_server(app)

    url = f"http://{server.host}:{server.port}/agent"
    result = await sse_http_adapter({}, url)

    assert result["content"] == "Part 1Part 2"
    assert result["status"] == "completed"
