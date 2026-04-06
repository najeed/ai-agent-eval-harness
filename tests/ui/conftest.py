import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def dashboard_server():
    """
    Starts the Streamlit dashboard in a separate process for UI testing.
    Points it to the mock trajectories directory.
    """
    mock_dir = Path("tests/data/mock_trajectories").absolute()
    mock_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TRAJECTORY_DIR"] = str(mock_dir)

    # Start streamlit on a non-standard port for testing
    port = "8505"
    cmd = [
        "streamlit",
        "run",
        "dashboard/app.py",
        "--server.port",
        port,
        "--server.headless",
        "true",
    ]

    process = subprocess.Popen(cmd, env=env)

    # Robust Polling Loop (Industrial v2.1 Hardening)
    import requests

    start_time = time.time()
    while time.time() - start_time < 30:
        try:
            response = requests.get(f"http://localhost:{port}")
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)

    yield f"http://localhost:{port}"

    process.terminate()
    process.wait()
