"""
A3: Invalid execution_mode is a run-level failure — no silent SIMULATED fallback.

SessionManager must refuse to construct when the scenario declares an unknown
execution truth mode. Simulation may never masquerade as live verification.
"""

import pytest

from eval_runner.execution_ir import ExecutionMode
from eval_runner.session import SessionManager


@pytest.fixture
def base_scenario():
    return {
        "aes_version": 1.4,
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "task",
                    "success_criteria": [{"metric": "task_completion", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }


def _all_valid_modes():
    return [m.value for m in ExecutionMode]


def test_invalid_execution_mode_raises(tmp_path, base_scenario):
    base_scenario["execution_mode"] = "warp_drive"
    with pytest.raises(ValueError, match="Invalid execution_mode 'warp_drive'"):
        SessionManager("run-bad-mode", base_scenario, log_root=tmp_path)


def test_invalid_execution_mode_never_defaults_to_simulated(tmp_path, base_scenario):
    base_scenario["metadata"] = {"execution_mode": "SIMULATION_PLZ"}
    with pytest.raises(ValueError) as excinfo:
        SessionManager("run-bad-mode-2", base_scenario, log_root=tmp_path)
    # The error must not silently downgrade: SIMULATED appears only in the
    # valid-modes enumeration, never as a taken fallback.
    assert "fail-closed" in str(excinfo.value)


@pytest.mark.parametrize("mode", _all_valid_modes())
def test_valid_execution_modes_construct(tmp_path, base_scenario, mode):
    base_scenario["execution_mode"] = mode
    session = SessionManager(f"run-ok-{mode}", base_scenario, log_root=tmp_path)
    assert session.execution_mode == ExecutionMode(mode)
    assert session.metadata["execution_mode"] == mode


def test_missing_execution_mode_defaults_to_simulated(tmp_path, base_scenario):
    session = SessionManager("run-default", base_scenario, log_root=tmp_path)
    assert session.execution_mode == ExecutionMode.SIMULATED
