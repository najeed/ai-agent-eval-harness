import pytest
import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock, ANY
from eval_runner.session import SessionManager
from eval_runner.exporter import HFExporter
from eval_runner.reporting_plugin import ReportingPlugin
from eval_runner.context import EvaluationContext
from eval_runner.engine import AgentAdapterRegistry


@pytest.mark.asyncio
async def test_hitl_interactive_input():
    """Verifies that SessionManager correctly handles HITL interactive input."""
    scenario = {
        "scenario_id": "test_hitl",
        "workflow": {
            "nodes": [{"id": "task1", "task_description": "Do something"}],
            "edges": []
        },
    }

    # Mock agent response with hitl_pause
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {
            "action": "hitl_pause",
            "prompt": "Custom HITL Prompt",
        }

        # Mock input()
        with patch("builtins.input", return_value="Approved by test") as mock_input, patch(
            "sys.stdin.isatty", return_value=True
        ), patch.dict(
            os.environ, {"CI": ""}
        ):  # Ensure not in CI mode

            session = SessionManager(scenario)
            session.max_turns = 1

            results = await session.execute_tasks(1)

            # Verify input was called
            mock_input.assert_called()

            # Verify history contains human response
            history = results[0]["conversation_history"]
            human_msg = next(m for m in history if m["role"] == "human")
            assert human_msg["content"] == "Approved by test"


@pytest.mark.asyncio
async def test_hitl_ci_auto_resume():
    """Verifies that SessionManager auto-resumes in CI mode."""
    scenario = {
        "scenario_id": "test_hitl_ci", 
        "workflow": {
            "nodes": [{"id": "task1", "task_description": "test"}],
            "edges": []
        }
    }

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock) as mock_call, \
         patch.dict(os.environ, {"CI": "true"}):

        mock_call.return_value = {"action": "hitl_pause"}
        session = SessionManager(scenario)
        session.max_turns = 1
        # Mocking sys.stdin.isatty to False since it's CI
        with patch("sys.stdin.isatty", return_value=False):
            results = await session.execute_tasks(1)

        history = results[0]["conversation_history"]
        human_msg = next(m for m in history if m["role"] == "human")
        assert "Auto-approved" in human_msg["content"]


def test_exporter_hf_push(tmp_path, monkeypatch):
    """Verifies HFExporter.push_to_hf calls the SDK correctly (mocked)."""
    # Setup working directory and real temporary file
    monkeypatch.chdir(tmp_path)
    dummy_file = tmp_path / "dummy.json"
    dummy_file.write_text("{}", encoding="utf-8")
    
    with patch("huggingface_hub.HfApi") as MockApi:
        mock_api_instance = MockApi.return_value

        HFExporter.push_to_hf("dummy.json", "user/repo")

        # Verify specific calls (dataset and README)
        mock_api_instance.upload_file.assert_any_call(
            path_or_fileobj="dummy.json",
            path_in_repo="dummy.json",
            repo_id="user/repo",
            repo_type="dataset",
        )
        mock_api_instance.upload_file.assert_any_call(
            path_or_fileobj=ANY,
            path_in_repo="README.md",
            repo_id="user/repo",
            repo_type="dataset",
        )


@pytest.mark.asyncio
async def test_reporting_plugin_notifications():
    """Verifies ReportingPlugin dispatches notifications via aiohttp."""
    plugin = ReportingPlugin()
    context = EvaluationContext(
        scenario_id="test_notif",
        scenario_data={},
        metadata={"webhook_url": "http://fake-webhook"},
    )
    results = [[{"metrics": [{"success": True}]}]]  # K-attempt results are list of lists

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        await plugin.dispatch_notifications(context, results)

        mock_post.assert_called()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://fake-webhook"
        assert "Success Rate*: 1/1" in kwargs["json"]["text"]


@pytest.mark.asyncio
async def test_adapter_guards():
    """Verifies that adapters handle missing frameworks gracefully."""
    from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
    from eval_runner.adapters.crewai import CrewAIAdapterPlugin

    lg_plugin = LangGraphAdapterPlugin()
    crew_plugin = CrewAIAdapterPlugin()

    # Force import error for these tests by manipulating sys.modules
    # Note: We must also patch the adapter modules to trigger the ImportError in the execute method
    with patch.dict("sys.modules", {
        "langgraph": None,
        "crewai": None,
    }):
        lg_res = await lg_plugin.execute_langgraph_node({"node_id": "test"})
        assert lg_res["status"] == "error"
        assert "not installed" in lg_res["message"]

        crew_res = await crew_plugin.execute_crewai_task({"task_id": "test"})
        assert crew_res["status"] == "error"
        assert "not installed" in crew_res["message"]
