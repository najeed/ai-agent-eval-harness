import sys
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.events import CoreEvents


@pytest.mark.asyncio
async def test_crewai_on_discover_adapters():
    adapter = CrewAIAdapterPlugin()
    registry = MagicMock()
    adapter.on_discover_adapters(registry)
    registry.register.assert_any_call("crewai", adapter.execute_crewai_task)
    registry.register.assert_any_call("crewai:v1", adapter.execute_crewai_task)


@pytest.mark.asyncio
async def test_crewai_sdk_missing():
    adapter = CrewAIAdapterPlugin()
    payload = {"task_id": "test_task"}

    orig_import = __import__

    with patch("eval_runner.adapters.crewai.emit") as mock_emit:
        # Simulate crewai not installed
        def mock_import(name, *args, **kwargs):
            if name == "crewai":
                raise ImportError("SDK not installed")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await adapter.execute_crewai_task(payload)
            assert result["status"] == "error"
            assert "SDK not installed" in result["message"]
            mock_emit.assert_any_call(CoreEvents.ERROR, {"message": ANY})


@pytest.mark.asyncio
async def test_crewai_simulation_mode():
    adapter = CrewAIAdapterPlugin()
    payload = {"task_id": "test_task"}  # No crew_path

    mock_crewai = MagicMock()
    mock_crewai.__version__ = "0.1.0"

    with (
        patch.dict(sys.modules, {"crewai": mock_crewai}),
        patch("eval_runner.adapters.crewai.emit") as mock_emit,
    ):
        result = await adapter.execute_crewai_task(payload)

        assert result["status"] == "success"
        assert result["metadata"]["mode"] == "simulated"
        mock_emit.assert_any_call(CoreEvents.CHAIN_START, ANY)


@pytest.mark.asyncio
async def test_crewai_direct_object_kickoff_sync():
    adapter = CrewAIAdapterPlugin()
    payload = {"task_id": "test_task", "metadata": {"crew_path": "mock_module:mock_crew"}}

    class MockCrew:
        def kickoff(self, inputs=None):
            return "Sync Success"

    mock_crewai = MagicMock()
    mock_crewai.Crew = MockCrew

    mock_crew = MockCrew()

    mock_module = MagicMock()
    mock_module.mock_crew = mock_crew

    with (
        patch.dict(sys.modules, {"crewai": mock_crewai}),
        patch("importlib.import_module", return_value=mock_module),
        patch("eval_runner.adapters.crewai.emit"),
    ):
        result = await adapter.execute_crewai_task(payload)

        assert result["status"] == "success"
        assert result["output"] == "Sync Success"


@pytest.mark.asyncio
async def test_crewai_factory_kickoff_async():
    adapter = CrewAIAdapterPlugin()
    payload = {"task_id": "test_task", "metadata": {"crew_path": "mock_module:crew_factory"}}

    class MockCrew:
        pass

    mock_crewai = MagicMock()
    mock_crewai.Crew = MockCrew

    mock_crew = MagicMock()  # Use MagicMock for the instance returned by factory
    mock_crew.kickoff_async = AsyncMock(return_value="Async Success")

    def crew_factory():
        return mock_crew

    mock_module = MagicMock()
    mock_module.crew_factory = crew_factory

    with (
        patch.dict(sys.modules, {"crewai": mock_crewai}),
        patch("importlib.import_module", return_value=mock_module),
        patch("eval_runner.adapters.crewai.emit"),
    ):
        result = await adapter.execute_crewai_task(payload)

        assert result["status"] == "success"
        assert result["output"] == "Async Success"
        mock_crew.kickoff_async.assert_called_once()


@pytest.mark.asyncio
async def test_crewai_simulation_sdk_missing():
    adapter = CrewAIAdapterPlugin()

    def mock_import(name, *args, **kwargs):
        if name == "crewai":
            raise ImportError("CrewAI SDK not installed")
        return MagicMock()

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError, match="CrewAI SDK not installed"):
            await adapter._execute_simulation("test_task")


@pytest.mark.asyncio
async def test_crewai_attribute_error_handling():
    adapter = CrewAIAdapterPlugin()
    payload = {"task_id": "test_task", "metadata": {"crew_path": "mock_module:missing_attr"}}

    mock_module = MagicMock(spec=[])  # No attributes allowed

    with (
        patch.dict(sys.modules, {"crewai": MagicMock()}),
        patch("importlib.import_module", return_value=mock_module),
        patch("eval_runner.adapters.crewai.emit", create=True),
    ):
        result = await adapter.execute_crewai_task(payload)
        assert result["status"] == "error"
        assert "CrewAI execution failed" in result["message"]


@pytest.mark.asyncio
async def test_crewai_value_error_handling():
    adapter = CrewAIAdapterPlugin()
    payload = {
        "task_id": "test_task",
        "metadata": {"crew_path": "bad_path"},  # Missing colon
    }

    with (
        patch.dict(sys.modules, {"crewai": MagicMock()}),
        patch("eval_runner.adapters.crewai.emit") as mock_emit,
    ):
        result = await adapter.execute_crewai_task(payload)
        assert result["status"] == "error"
        assert "CrewAI execution failed" in result["message"]
        mock_emit.assert_any_call(CoreEvents.ERROR, {"message": ANY})
