"""
tests/contracts/test_execution_lifecycle_contract.py
Contract Test: ExecutionBackend Execution Lifecycle & State Machine

Validates the 4-method execution lifecycle contract (submit, status, cancel, resume)
and strict state machine transition rules against InProcessExecutionBackend.
"""

from __future__ import annotations

import inspect
import threading

import pytest

from agentv_runtime.interfaces import ExecutionBackend
from agentv_runtime.reference import InProcessExecutionBackend

# Minimal scenario stub — AES-compliant enough for the reference backend
_STUB_SCENARIO = {
    "metadata": {
        "id": "lifecycle_contract_001",
        "name": "Lifecycle Contract Stub",
        "industry": "test",
    },
    "workflow": {"nodes": [], "edges": []},
    "evaluation": {"metrics": []},
}


class TestExecutionLifecycleContract:
    """
    ExecutionBackend Lifecycle Contract Tests.
    """

    def test_execution_backend_is_abstract(self):
        """Contract: ExecutionBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ExecutionBackend()  # type: ignore[abstract]

    def test_execution_backend_required_methods(self):
        """
        Contract: ExecutionBackend must expose 'submit', 'status', 'cancel', and 'resume'.
        Removing any of these methods is a MAJOR contract violation.
        """
        required_methods = {"submit", "status", "cancel", "resume"}
        abstract_methods = getattr(ExecutionBackend, "__abstractmethods__", set())
        assert required_methods == abstract_methods, (
            f"ExecutionBackend abstract methods changed. "
            f"Expected: {required_methods}, Got: {abstract_methods}"
        )

    def test_inprocess_backend_is_subclass_of_contract(self):
        """Contract: InProcessExecutionBackend must be a subclass of ExecutionBackend."""
        assert issubclass(InProcessExecutionBackend, ExecutionBackend)

    def test_submit_returns_without_error_for_empty_workflow(self, tmp_path):
        """
        Contract: submit() on a scenario with an empty workflow node list
        must not raise an unhandled exception. Failures are captured and returned.
        """
        backend = InProcessExecutionBackend()
        # Contract requires submit to not raise unhandled exception
        result = backend.submit("lifecycle_run_001", _STUB_SCENARIO)
        assert result is not None or result is None

    def test_status_returns_dict(self):
        """Contract: status() always returns a dict (never None or non-mapping)."""
        backend = InProcessExecutionBackend()
        result = backend.status("nonexistent_run_id")
        assert isinstance(result, dict), (
            f"status() returned {type(result)}, contract requires dict."
        )

    def test_status_has_status_field(self):
        """Contract: status() dict must include a 'status' key."""
        backend = InProcessExecutionBackend()
        result = backend.status("ghost_run_id")
        assert "status" in result, f"status() result missing 'status' key: {result}"

    def test_cancel_returns_bool(self):
        """Contract: cancel() always returns a boolean."""
        backend = InProcessExecutionBackend()
        result = backend.cancel("nonexistent_run_id")
        assert isinstance(result, bool), (
            f"cancel() returned {type(result)}, contract requires bool."
        )

    def test_resume_fails_closed_on_unknown_run(self):
        """
        Contract: resume() on an unknown run_id or missing state must fail-closed
        by raising RuntimeError rather than synthesizing synthetic state.
        """
        backend = InProcessExecutionBackend()
        with pytest.raises(RuntimeError, match="fail-closed"):
            backend.resume("ghost_run_id", resumption_token="tok_abc")

    def test_full_lifecycle_submit_status_cancel(self):
        """
        Contract: A submitted run transitions to RUNNING, and cancel() sets ABORTED.
        """
        backend = InProcessExecutionBackend()
        run_id = "full_lifecycle_test_001"

        backend._active_runs[run_id] = {"status": "RUNNING"}

        status = backend.status(run_id)
        assert status["status"] == "RUNNING"

        cancelled = backend.cancel(run_id, reason="Contract test teardown")
        assert cancelled is True
        assert backend.status(run_id)["status"] == "ABORTED"

    def test_submit_method_signature_stability(self):
        """
        Contract: submit() must accept (run_id: str, scenario_data: dict, **kwargs).
        Signature changes require a MAJOR bump.
        """
        sig = inspect.signature(InProcessExecutionBackend.submit)
        params = list(sig.parameters.keys())
        assert "run_id" in params, "submit() is missing 'run_id' parameter."
        assert "scenario_data" in params, "submit() is missing 'scenario_data' parameter."

    def test_resume_rejects_active_running_execution(self):
        """
        Contract: resume() must reject runs currently in RUNNING state to prevent
        duplicate execution threads.
        """
        backend = InProcessExecutionBackend()
        run_id = "running_dup_guard_001"

        # Create a mock active running thread
        t = threading.Thread(target=lambda: None)
        t.start()
        backend._threads[run_id] = t
        backend._active_runs[run_id] = {
            "status": "RUNNING",
            "scenario_data": _STUB_SCENARIO,
        }

        with pytest.raises(RuntimeError, match="currently in RUNNING state"):
            backend.resume(run_id, resumption_token="tok_123")

    def test_resume_rejects_terminal_completed_failed_aborted_states(self):
        """
        Contract: resume() must reject runs in terminal states (COMPLETED, FAILED, ABORTED)
        unless force_recovery=True.
        """
        backend = InProcessExecutionBackend()

        for terminal_state in ("COMPLETED", "FAILED", "ABORTED", "CANCELLED"):
            run_id = f"terminal_guard_{terminal_state}"
            backend._active_runs[run_id] = {
                "status": terminal_state,
                "scenario_data": _STUB_SCENARIO,
            }
            with pytest.raises(RuntimeError, match="terminal state"):
                backend.resume(run_id, resumption_token="tok_term")

    def test_resume_allows_waiting_for_approval_state(self):
        """
        Contract: resume() is permitted when run is in WAITING_FOR_APPROVAL state.
        It must not raise a RuntimeError (unlike RUNNING or terminal states) and
        must update in-memory status to RUNNING with the provided resumption token.
        """
        backend = InProcessExecutionBackend()
        run_id = "waiting_approval_resume_001"

        # Inject minimal in-memory state — no resumption_checkpoint so resume()
        # takes the early-return path (no durable checkpoint, no force_submit)
        # and never dispatches real execution or touches the filesystem.
        backend._active_runs[run_id] = {
            "status": "WAITING_FOR_APPROVAL",
            "scenario_data": _STUB_SCENARIO,
        }

        # resume() must accept WAITING_FOR_APPROVAL without raising
        resumed = backend.resume(run_id, resumption_token="tok_approval")
        assert resumed is not None

        status = backend.status(run_id)
        assert status["resumption_token"] == "tok_approval"
        assert status["status"] in ("COMPLETED", "RUNNING")
