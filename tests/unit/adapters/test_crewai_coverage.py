"""Current CrewAI adapter native binding and fail-closed contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from eval_runner.adapters import crewai
from eval_runner.adapters.crewai import CrewAIAdapterPlugin


def test_crewai_registers_current_protocols() -> None:
    adapter = CrewAIAdapterPlugin()
    registry = MagicMock()

    adapter.on_discover_adapters(registry)

    registry.register.assert_any_call("crewai", adapter.execute_crewai_task)
    registry.register.assert_any_call("crewai:v1", adapter.execute_crewai_task)


@pytest.mark.asyncio
async def test_crewai_rejects_simulation_mode() -> None:
    result = await CrewAIAdapterPlugin().execute_crewai_task(
        {"task_id": "test-task", "metadata": {"execution_mode": "simulation"}}
    )

    assert result["status"] == "error"
    assert "synthetic execution mode" in result["message"]


@pytest.mark.asyncio
async def test_crewai_missing_sdk_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = CrewAIAdapterPlugin()

    def missing_crewai(name: str) -> object:
        assert name == "crewai"
        raise ImportError("CrewAI unavailable")

    monkeypatch.setattr(crewai.importlib, "import_module", missing_crewai)
    result = await adapter.execute_crewai_task({"task_id": "test-task"})

    assert result["status"] == "error"
    assert "CrewAI SDK unavailable" in result["message"]


@pytest.mark.asyncio
async def test_crewai_executes_native_akickoff(monkeypatch: pytest.MonkeyPatch) -> None:
    class NativeCrew:
        def __init__(self) -> None:
            self.akickoff = AsyncMock(return_value=SimpleNamespace(raw="CERTIFIED"))

    crew = NativeCrew()
    crewai_module = SimpleNamespace(Crew=NativeCrew, __version__="1.15.22")
    monkeypatch.setattr(crewai.importlib, "import_module", lambda name: crewai_module)

    result = await CrewAIAdapterPlugin().execute_crewai_task(
        {"task_id": "test-task", "metadata": {"crew": crew}, "inputs": {"message": "hello"}}
    )

    assert result["status"] == "success", result
    assert result["output"] == "CERTIFIED"
    crew.akickoff.assert_awaited_once_with(inputs={"message": "hello"})


@pytest.mark.asyncio
async def test_crewai_allows_synchronous_kickoff_without_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyncOnlyCrew:
        def kickoff(self, inputs: dict[str, str]) -> SimpleNamespace:
            return SimpleNamespace(raw=inputs["message"])

    crew = SyncOnlyCrew()
    crewai_module = SimpleNamespace(Crew=SyncOnlyCrew, __version__="1.15.22")
    monkeypatch.setattr(crewai.importlib, "import_module", lambda name: crewai_module)

    result = await CrewAIAdapterPlugin().execute_crewai_task(
        {"task_id": "test-task", "metadata": {"crew": crew}, "inputs": {"message": "hello"}}
    )

    assert result["status"] == "success", result
    assert result["output"] == "hello"


@pytest.mark.asyncio
async def test_crewai_executes_kickoff_async_when_native_async_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyAsyncCrew:
        def __init__(self) -> None:
            self.kickoff_async = AsyncMock(return_value=SimpleNamespace(raw="CERTIFIED"))

    crew = LegacyAsyncCrew()
    crewai_module = SimpleNamespace(Crew=LegacyAsyncCrew, __version__="1.15.22")
    monkeypatch.setattr(crewai.importlib, "import_module", lambda name: crewai_module)

    result = await CrewAIAdapterPlugin().execute_crewai_task(
        {"task_id": "test-task", "metadata": {"crew": crew}, "inputs": {"message": "hello"}}
    )

    assert result["status"] == "success", result
    crew.kickoff_async.assert_awaited_once_with(inputs={"message": "hello"})


def test_crewai_certification_requires_native_akickoff() -> None:
    class LegacyCrew:
        async def kickoff_async(self, *, inputs: dict[str, object]) -> object:
            return inputs

    with pytest.raises(RuntimeError, match="certification requires native"):
        CrewAIAdapterPlugin._select_execution_method(
            LegacyCrew(), timeout=None, require_native_async=True
        )
