"""
Shared fixtures for console route tests.

The production auth model is deny-by-default with no implicit localhost trust.
Console tests opt into a deterministic bypass via AGENTV_TEST_AUTH_BYPASS=1
(explicit test-harness seam in auth_manager.require_permission).
"""

import pytest


@pytest.fixture(autouse=True)
def console_auth_bypass(monkeypatch):
    """Opts every console route test into the explicit test-auth bypass seam."""
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    yield


@pytest.fixture(autouse=True)
def reset_console_singletons():
    """
    Resets process-wide singletons after each console test.

    ScenarioCatalog and InProcessExecutionBackend cache instances whose state
    (scenario index, run dispatch wiring) would otherwise leak across tests in
    the same xdist worker, producing order-dependent failures.
    """
    yield
    try:
        from eval_runner.catalog import ScenarioCatalog

        ScenarioCatalog.clear_instance()
    except Exception:  # noqa: BLE001 - teardown must never fail a test
        pass
    try:
        from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

        InProcessExecutionBackend.clear_instance()
    except Exception:  # noqa: BLE001
        pass
