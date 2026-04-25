import pytest
from aiohttp import web

from eval_runner.session import SessionManager


async def mock_sse_agent_endpoint(request):
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
    await response.prepare(request)

    # Simulate a tool call and then a final answer
    await response.write(b'data: {"action": "completed", "content": "Task done via SSE"}\n\n')
    await response.write(b"data: [DONE]\n\n")
    return response


@pytest.mark.asyncio
async def test_sse_session_flow(aiohttp_server):
    app = web.Application()
    app.router.add_post("/agent", mock_sse_agent_endpoint)
    server = await aiohttp_server(app)
    endpoint = f"http://{server.host}:{server.port}/agent"

    scenario = {
        "id": "test_sse_scenario",
        "max_turns": 2,
        "workflow": {
            "nodes": [
                {
                    "id": "node1",
                    "task_description": "Do something",
                    "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                }
            ]
        },
        "metadata": {"agent": {"protocol": "sse", "endpoint": endpoint}},
    }

    session = SessionManager(run_id="test_run_sse", scenario=scenario)
    results = await session.execute_tasks(attempt_number=1)

    assert len(results) > 0
    node_res = results[0]
    assert node_res["status"] == "success"
    # Verify sse was recorded in protocol sequence
    assert "sse" in str(node_res.get("protocol_sequence", []))
