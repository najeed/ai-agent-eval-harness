import pytest

from eval_runner.simulators import (
    BaseJailProvider,
    BaseSimulator,
    SimulatorMiddleware,
    TerminalSimulator,
)
from eval_runner.triage import TriageContext, TriageEngine, TriageReport


# 1. Test Simulator Middleware
class DummyMiddleware(SimulatorMiddleware):
    def __init__(self):
        self.called = False
        self.post_called = False

    async def process_action(self, simulator, action, params, next_call):
        self.called = True
        res = await next_call()
        self.post_called = True
        res["middleware_injected"] = "success"
        return res


class ErrorMiddleware(SimulatorMiddleware):
    async def process_action(self, simulator, action, params, next_call):
        raise ValueError("Simulated middleware error")


class DummySimulator(BaseSimulator):
    def __init__(self, *args, **kwargs):
        super().__init__({"value": 0}, *args, **kwargs)

    async def handle_dummy_action(self, params):
        return {"status": "success", "original": "value"}


@pytest.mark.asyncio
async def test_simulator_middleware():
    sim = DummySimulator()
    mw = DummyMiddleware()
    sim.register_middleware(mw)

    res = await sim.execute("dummy_action", {})
    assert mw.called
    assert mw.post_called
    assert res["status"] == "success"
    assert res["middleware_injected"] == "success"


@pytest.mark.asyncio
async def test_simulator_middleware_error_isolation():
    sim = DummySimulator()
    sim.register_middleware(ErrorMiddleware())

    # ErrorMiddleware raises error, but BaseSimulator execute should isolate it and continue
    res = await sim.execute("dummy_action", {})
    assert res["status"] == "success"
    assert res["original"] == "value"


# 2. Test Jail Provider Interface & Custom Teardown Hook
class DummyJailProvider(BaseJailProvider):
    def __init__(self):
        self.cmd_run = None
        self.cleanup_run_id = None

    async def execute_command(self, cmd, cwd, env, timeout):
        self.cmd_run = cmd
        return {
            "status": "success",
            "stdout": "dummy_output",
            "stderr": "",
            "returncode": 0,
            "cwd": cwd,
        }

    async def cleanup(self, run_id):
        self.cleanup_run_id = run_id


@pytest.mark.asyncio
async def test_terminal_simulator_jail_provider():
    sim = TerminalSimulator()
    provider = DummyJailProvider()
    sim.set_jail_provider(provider)
    sim.terminal_jail = "dummy_jail_path"  # Set to pass initial safety check

    res = await sim.handle_terminal_execute({"cmd": "echo 123"})
    assert provider.cmd_run == "echo 123"
    assert res["status"] == "success"
    assert res["stdout"] == "dummy_output"

    await sim.cleanup()
    assert provider.cleanup_run_id == "default_run"


# 3. Test Triage and Pluggable Classifiers
def test_triage_custom_classifier():
    def custom_classifier(context: TriageContext) -> TriageReport | None:
        if "test_trigger" in context.task_result.get("error_msg", ""):
            return TriageReport(
                category="CUSTOM_ERROR",
                explanation="Detected test_trigger in error message",
                index=3,
                confidence=0.99,
                suggestion="Check the test_trigger logic",
            )
        return None

    TriageEngine.register_classifier(custom_classifier)

    task_result = {
        "conversation_history": [{"role": "agent", "content": "hello"}],
        "error_msg": "something failed with test_trigger",
    }

    category = TriageEngine.categorize_failure(task_result)
    assert category == "CUSTOM_ERROR"
    assert task_result["diagnostic_report"]["root_cause"] == "CUSTOM_ERROR"
    assert (
        task_result["diagnostic_report"]["explanation"] == "Detected test_trigger in error message"
    )
    assert task_result["diagnostic_report"]["index"] == 3
    assert task_result["diagnostic_report"]["confidence"] == 0.99
    assert task_result["diagnostic_report"]["suggestion"] == "Check the test_trigger logic"

    # Reset/clean classifier registry after test
    TriageEngine._classifiers.remove(custom_classifier)


# 4. Test ShimResultProxy
def test_shim_result_proxy():
    from eval_runner.simulators import ShimResultProxy

    raw_result = {"status": "success", "message": "Executed successfully", "custom_key": "data"}
    metadata = {"signing_key": "sec_key"}
    proxy = ShimResultProxy(raw_result, metadata=metadata)

    # All raw result keys are transparently accessible (backward-compatible dict view)
    assert proxy["status"] == "success"
    assert proxy["message"] == "Executed successfully"
    assert proxy["custom_key"] == "data"  # simulator-specific keys pass through

    # Secure metadata is NOT accessible via standard dict traversal
    assert "signing_key" not in proxy

    # Secure metadata is retrievable via the explicit side-channel only
    assert proxy.get_secure_metadata() == metadata


# 5. Test Deterministic Quiescence & Timeout Guard
class DummyQuiesceSimulator(BaseSimulator):
    def __init__(self, hang=False, raise_err=False, *args, **kwargs):
        super().__init__({}, *args, **kwargs)
        self.hang = hang
        self.raise_err = raise_err
        self.quiesced = False

    async def handle_dummy_quiesce_action(self, params):
        return {"status": "success"}

    async def quiesce(self):
        if self.raise_err:
            raise ValueError("Simulated quiesce crash")
        if self.hang:
            import asyncio

            await asyncio.sleep(10.0)
        self.quiesced = True


@pytest.mark.asyncio
async def test_quiesce_timeout_guard():
    from eval_runner.tool_sandbox import ToolSandbox

    # Non-hanging simulator should quiesce successfully
    sim_ok = DummyQuiesceSimulator(hang=False)
    scenario = {
        "tools": {},
        "id": "test_scenario",
        "initial_state": {},
        "agent_topology": {},
        "enabled_shims": ["dummy_quiesce"],
    }
    sandbox = ToolSandbox(scenario)
    sandbox._simulator_cache = {"dummy_quiesce": sim_ok}

    # Executes tool and triggers quiesce
    res = await sandbox.execute("dummy_quiesce_action", {})
    assert sim_ok.quiesced
    assert res["status"] == "success"

    # Hanging simulator should timeout gracefully at 5s, yielding without blocking
    sim_hang = DummyQuiesceSimulator(hang=True)
    sandbox._simulator_cache = {"dummy_quiesce": sim_hang}

    import time

    start = time.time()
    # Executing should time out after 5.0 seconds
    res_hang = await sandbox.execute("dummy_quiesce_action", {})
    end = time.time()
    assert (end - start) < 6.0  # Assert it timed out around 5s and didn't hang for 10s
    assert not sim_hang.quiesced
    assert res_hang["status"] == "success"

    # Crashing quiesce simulator should log an error and yield without raising
    sim_fail = DummyQuiesceSimulator(raise_err=True)
    sandbox._simulator_cache = {"dummy_quiesce": sim_fail}
    res_fail = await sandbox.execute("dummy_quiesce_action", {})
    assert not sim_fail.quiesced
    assert res_fail["status"] == "success"


# 6. Test BaseWitness Abstract Class
def test_base_witness():
    from eval_runner.triage import BaseWitness, VerificationResult

    class DummyWitness(BaseWitness):
        async def verify(self, context):
            return VerificationResult(
                verified=True, explanation="Everything checks out", metadata={"fs_status": "clean"}
            )

    witness = DummyWitness()
    import asyncio

    context = TriageContext(conversation_history=[])
    res = asyncio.run(witness.verify(context))
    assert res.verified
    assert res.explanation == "Everything checks out"
    assert res.metadata["fs_status"] == "clean"
    assert res.to_dict()["verified"] is True
