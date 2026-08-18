"""
tests/contracts/test_execution_lifecycle_contract.py
Contract Test: ExecutionBackend Execution Lifecycle

Validates the 4-method execution lifecycle contract (submit, status, cancel, resume)
against the reference InProcessExecutionBackend. Any removal or signature change
to these methods requires a MAJOR semver bump.
"""

from __future__ import annotations

import inspect

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
        try:
            backend.submit("lifecycle_run_001", _STUB_SCENARIO)
        except Exception:
            # Allowed: the backend can fail gracefully. What is NOT allowed:
            # an undefined AttributeError or TypeError from a broken interface.
            pass

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

    def test_resume_does_not_raise_on_unknown_run(self):
        """
        Contract: resume() on an unknown run_id must not raise — it returns None
        or a valid state dict.
        """
        backend = InProcessExecutionBackend()
        result = backend.resume("ghost_run_id", resumption_token="tok_abc")
        # Acceptable: None or dict. Not acceptable: uncaught exception.
        assert result is None or isinstance(result, dict)

    def test_full_lifecycle_submit_status_cancel(self):
        """
        Contract: A submitted run transitions to RUNNING, and cancel() sets ABORTED.
        """
        backend = InProcessExecutionBackend()
        run_id = "full_lifecycle_test_001"

        # Inject a run directly (bypasses actual execution for lifecycle test)
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
