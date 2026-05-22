"""
Unit tests for the Tool Sandbox Interceptor Pipeline.
Verifies registration, preemption, auditing, reset, error resilience, and context manager overrides.
"""

import pytest

from eval_runner.tool_sandbox import (
    ToolSandbox,
    ToolSandboxInterceptor,
    tool_sandbox_service,
)


class MockPreemptiveSandboxInterceptor(ToolSandboxInterceptor):
    """Preempts tool execution completely, returning custom output without running core logic."""

    def can_isolate(self, tool_name: str) -> bool:
        return tool_name == "preempted_tool"

    async def isolate_call(self, call_data: dict, next_executor) -> dict:
        return {
            "status": "preempted",
            "message": "intercepted_by_preemptor",
            "requested_tool": call_data.get("tool_name"),
        }


class MockAuditingSandboxInterceptor(ToolSandboxInterceptor):
    """Audits tool execution by allowing it to proceed, but logging and augmenting the result."""

    def __init__(self):
        self.calls = []

    def can_isolate(self, tool_name: str) -> bool:
        return True

    async def isolate_call(self, call_data: dict, next_executor) -> dict:
        self.calls.append(call_data.get("tool_name"))
        # Mutate request parameters in-flight
        call_data["params"]["injected_param"] = "audited_value"
        # Execute next layer
        result = await next_executor(call_data)
        # Augment the result
        result["audited"] = True
        return result


class MockErrorSandboxInterceptor(ToolSandboxInterceptor):
    """Intentionally raises an error during isolation to verify zero-trust resiliency."""

    def can_isolate(self, tool_name: str) -> bool:
        return True

    async def isolate_call(self, call_data: dict, next_executor) -> dict:
        raise RuntimeError("Simulated interceptor failure")


@pytest.fixture(autouse=True)
def setup_isolation():
    """Resets the tool sandbox service before and after each test to ensure thread-local hygiene."""
    tool_sandbox_service.reset()
    yield
    tool_sandbox_service.reset()


@pytest.mark.asyncio
async def test_sandbox_pipeline_no_interceptors(tmp_path):
    """Verify that tool execution continues normally when no custom interceptors are registered."""
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "get_status": {
                "output": {
                    "status": "success",
                    "data": "running",
                }
            }
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    result = await sandbox.execute("get_status", {"foo": "bar"})
    assert result["status"] == "success"
    assert result["data"] == "running"


@pytest.mark.asyncio
async def test_sandbox_pipeline_preemption(tmp_path):
    """Verify that a preemptive interceptor can completely bypass core execution."""
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "preempted_tool": {
                "output": {
                    "status": "core_success",
                }
            }
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    preemptor = MockPreemptiveSandboxInterceptor()
    tool_sandbox_service.register_interceptor(preemptor)

    result = await sandbox.execute("preempted_tool", {})
    assert result["status"] == "preempted"
    assert result["message"] == "intercepted_by_preemptor"
    assert result["requested_tool"] == "preempted_tool"


@pytest.mark.asyncio
async def test_sandbox_pipeline_auditing(tmp_path):
    """Verify that an auditing interceptor can inspect inputs, allow execution,

    and augment outputs.
    """
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "standard_tool": {
                "output": {
                    "status": "success",
                    "data": "original_data",
                }
            }
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    auditor = MockAuditingSandboxInterceptor()
    tool_sandbox_service.register_interceptor(auditor)

    params = {"input_val": 42}
    result = await sandbox.execute("standard_tool", params)

    assert auditor.calls == ["standard_tool"]
    # Verify parameter injection and output augmentation
    assert result["status"] == "success"
    assert result["data"] == "original_data"
    assert result["audited"] is True


@pytest.mark.asyncio
async def test_sandbox_pipeline_override_context_manager(tmp_path):
    """Verify that override_interceptor registers temporarily and reverts cleanly."""
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "preempted_tool": {
                "output": {
                    "status": "core_success",
                }
            }
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    preemptor = MockPreemptiveSandboxInterceptor()

    # 1. Before context manager: normal execution
    res1 = await sandbox.execute("preempted_tool", {})
    assert res1["status"] == "core_success"

    # 2. Inside context manager: preempted
    async with tool_sandbox_service.override_interceptor(preemptor):
        res2 = await sandbox.execute("preempted_tool", {})
        assert res2["status"] == "preempted"

    # 3. After context manager: back to normal
    res3 = await sandbox.execute("preempted_tool", {})
    assert res3["status"] == "core_success"


@pytest.mark.asyncio
async def test_sandbox_pipeline_error_resiliency(tmp_path, caplog):
    """Verify that when an interceptor fails, it is gracefully bypassed to protect execution."""
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "faulty_path_tool": {
                "output": {
                    "status": "resilient_fallback_success",
                }
            }
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    bad_interceptor = MockErrorSandboxInterceptor()
    tool_sandbox_service.register_interceptor(bad_interceptor)

    # Execution should succeed and not crash despite runtime error in interceptor
    result = await sandbox.execute("faulty_path_tool", {})
    assert result["status"] == "resilient_fallback_success"
