import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.handlers.evaluation import handle_evaluate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,expected_ids", [(1, ["campaign"]), (2, ["campaign-0001", "campaign-0002"])]
)
async def test_batch_limit_attempts_seed_unique_run_ids_and_output(tmp_path, limit, expected_ids):
    output = tmp_path / "results.json"
    args = SimpleNamespace(
        path="scenarios",
        format="json",
        seed=17,
        attempts=3,
        limit=limit,
        run_id="campaign",
        output=str(output),
        agent="http://localhost:8000/execute_task",
        protocol="http",
        agent_name="test",
        plugin=[],
        execution_mode="live",
    )
    scenarios = [{"metadata": {"id": f"scenario-{i}"}} for i in range(3)]
    execute = AsyncMock(return_value=[{"passed": True}, {"passed": False}, {"passed": True}])
    with (
        patch("eval_runner.loader.load_dataset", return_value=scenarios),
        patch("eval_runner.engine.run_evaluation", execute),
        patch(
            "eval_runner.runtime_services.resolve_plugin_registry",
            return_value=MagicMock(provenance_map={}),
        ),
        patch("eval_runner.handlers.evaluation.load_plugins_from_args"),
        patch("eval_runner.adapters.common.SessionManager.close_all", new_callable=AsyncMock),
    ):
        assert await handle_evaluate(args) == 0
    assert execute.await_count == limit
    assert [call.kwargs["run_id"] for call in execute.await_args_list] == expected_ids
    for call in execute.await_args_list:
        assert call.kwargs["attempts"] == 3  # Runner derives attempt seeds and Pass@K together.
        assert call.kwargs["seed"] == 17
        assert call.args[0]["execution_mode"] == "live"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert [row["run_id"] for row in saved["results"]] == expected_ids
    assert all(len(row["results"]) == 3 for row in saved["results"])
    assert all("execution_mode" not in source for source in scenarios)


@pytest.mark.asyncio
async def test_batch_refuses_nonpositive_limit_before_execution():
    args = SimpleNamespace(path="scenarios", format="json", plugin=[], limit=0)
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "scenario"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as execute,
        patch(
            "eval_runner.runtime_services.resolve_plugin_registry",
            return_value=MagicMock(provenance_map={}),
        ),
        patch("eval_runner.handlers.evaluation.load_plugins_from_args"),
    ):
        assert await handle_evaluate(args) == 1
        execute.assert_not_awaited()
