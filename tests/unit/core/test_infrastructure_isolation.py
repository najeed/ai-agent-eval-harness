import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner.config import RegistryManager
from eval_runner.session import SessionManager


@pytest.mark.asyncio
async def test_workspace_isolation_concurrency(tmp_path):
    """
    Verify that parallel sessions of the same scenario
    use isolated workspace directories.
    """
    scenario = {"id": "test-scenario", "workflow": {"nodes": [{"id": "n1"}]}}

    # Mock RUN_LOG_DIR to use tmp_path
    with patch("eval_runner.config.RUN_LOG_DIR", tmp_path):
        session1 = SessionManager("run-1", scenario)
        session2 = SessionManager("run-2", scenario)

        # Verify paths are unique and based on run_id
        assert "run-1" in str(session1.forensics.target_dir)
        assert "run-2" in str(session2.forensics.target_dir)

        # Check tool sandbox workspace isolation
        # We need to access the sandbox which is created during execute_tasks
        # or we can just check the logic in a standalone sandbox
        from eval_runner.tool_sandbox import ToolSandbox

        sandbox1 = ToolSandbox({**scenario, "run_id": "run-1"})
        sandbox2 = ToolSandbox({**scenario, "run_id": "run-2"})

        assert "run-1" in str(sandbox1.workspace_dir)
        assert "run-2" in str(sandbox2.workspace_dir)
        assert sandbox1.workspace_dir != sandbox2.workspace_dir


@pytest.mark.asyncio
async def test_env_pollution_purge():
    """
    Verify that SessionManager no longer writes to global os.environ.
    """
    scenario = {"id": "test", "workflow": {"nodes": []}}

    # Ensure they aren't set before
    os.environ.pop("AES_RUN_ID", None)
    os.environ.pop("AES_IDENTIFIER", None)

    from unittest.mock import mock_open

    with patch("eval_runner.config.RUN_LOG_DIR", Path(".")):
        with patch("pathlib.Path.mkdir"):
            with patch("builtins.open", mock_open()):
                with patch("eval_runner.plugins.PluginManager.load_plugins"):
                    SessionManager("my-run", scenario)

    assert "AES_RUN_ID" not in os.environ
    assert "AES_IDENTIFIER" not in os.environ


def test_registry_manager_thread_safety():
    """
    Verify that RegistryManager handles concurrent reloads without corruption.
    """

    def worker():
        for _ in range(5):
            RegistryManager.reload()
            RegistryManager.get_resolved_registry()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # If it didn't crash or hang, the lock is doing its job
    assert RegistryManager.get_resolved_registry() is not None
