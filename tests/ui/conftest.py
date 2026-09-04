"""
tests/ui/conftest.py

Streamlit dashboard fixture for Playwright UI tests.

Design notes
------------
``pytest-xdist`` with ``--dist loadfile`` (configured in pyproject.toml)
assigns every test from a given source file to the **same** worker.
Because there is exactly one UI test file, exactly one worker will ever
instantiate ``dashboard_server`` per run — there is no cross-worker
contention.  The fixture therefore starts the server unconditionally and
tears it down after the session without any coordination file/lock logic.

The ``worker_id`` fixture is declared as a local fallback so the conftest
works in plain ``pytest`` runs (no ``-n`` flag) where pytest-xdist does
not inject ``worker_id`` automatically.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# worker_id fallback (only registered when pytest-xdist is absent)
# ---------------------------------------------------------------------------

try:
    import xdist  # noqa: F401 — xdist is present; it provides worker_id itself
except ImportError:

    @pytest.fixture(scope="session")
    def worker_id() -> str:  # type: ignore[misc]
        """Fallback for non-xdist runs."""
        return "master"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Ask the OS for a free port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_http(url: str, timeout: float = 60.0) -> bool:
    """Poll *url* until HTTP 200 or *timeout* seconds elapse."""
    import requests

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=5).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def dashboard_server(tmp_path_factory):
    """
    Start the Streamlit dashboard in a subprocess and yield its base URL.

    Works correctly under pytest-xdist: because ``--dist loadfile`` keeps all
    tests from ``tests/ui/`` on a single worker, this fixture is instantiated
    exactly once per run.  No cross-worker coordination is needed.
    """
    workspace_root = Path(__file__).parent.parent.parent.absolute()
    app_path = workspace_root / "dashboard" / "app.py"
    if not app_path.exists():
        pytest.skip("Streamlit dashboard app (dashboard/app.py) is not present in repository")

    try:
        import streamlit  # noqa: F401
    except ImportError:
        pytest.skip("Streamlit is not installed in the current environment")

    mock_dir = workspace_root / "tests" / "data" / "mock_trajectories"
    mock_dir.mkdir(parents=True, exist_ok=True)

    port = _find_free_port()

    env = os.environ.copy()
    env["TRAJECTORY_DIR"] = str(mock_dir)
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]

    # Capture stderr to a file so failures produce actionable diagnostics.
    stderr_log: Path = tmp_path_factory.getbasetemp() / "streamlit_stderr.log"
    stderr_fh = stderr_log.open("w")

    process = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(workspace_root),
        stdout=subprocess.DEVNULL,
        stderr=stderr_fh,
    )

    url = f"http://localhost:{port}"

    if not _wait_for_http(url, timeout=60.0):
        stderr_fh.flush()
        stderr_fh.close()
        process.terminate()
        process.wait()
        stderr_contents = stderr_log.read_text(errors="replace")
        pytest.fail(
            f"Streamlit dashboard failed to start on port {port} within 60 s.\n"
            f"--- stderr ({stderr_log}) ---\n{stderr_contents}"
        )

    yield url

    process.terminate()
    process.wait()
    stderr_fh.close()
