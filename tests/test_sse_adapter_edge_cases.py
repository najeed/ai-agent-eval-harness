import pytest
from aiohttp import web

from eval_runner.adapters import sse_http_adapter


@pytest.mark.asyncio
async def test_sse_http_adapter_malformed_json(aiohttp_server):
    async def mock_malformed_sse(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"content": "Valid"}\n\n')
        await response.write(b"data: {invalid_json}\n\n")
        await response.write(b'data: {"content": " recovered"}\n\n')
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application()
    app.router.add_post("/agent", mock_malformed_sse)
    server = await aiohttp_server(app)

    url = f"http://{server.host}:{server.port}/agent"
    result = await sse_http_adapter({}, url)

    # It should accumulate the raw string for malformed JSON and continue
    assert "Valid" in result["content"]
    assert "{invalid_json}" in result["content"]
    assert "recovered" in result["content"]


@pytest.mark.asyncio
async def test_sse_http_adapter_empty_stream(aiohttp_server):
    async def mock_empty_sse(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application()
    app.router.add_post("/agent", mock_empty_sse)
    server = await aiohttp_server(app)

    url = f"http://{server.host}:{server.port}/agent"
    result = await sse_http_adapter({}, url)

    assert result == {}


@pytest.mark.asyncio
async def test_sse_http_adapter_no_done_signal(aiohttp_server):
    async def mock_no_done_sse(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"content": "Finished but no DONE"}\n\n')
        return response

    app = web.Application()
    app.router.add_post("/agent", mock_no_done_sse)
    server = await aiohttp_server(app)

    url = f"http://{server.host}:{server.port}/agent"
    # Should finish when connection closes
    result = await sse_http_adapter({}, url)

    assert result["content"] == "Finished but no DONE"
