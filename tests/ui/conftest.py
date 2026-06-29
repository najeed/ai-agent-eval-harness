import os
import subprocess
import sys
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

    # Find a free port dynamically to prevent collisions
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = str(s.getsockname()[1])

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "dashboard/app.py",
        "--server.port",
        port,
        "--server.headless",
        "true",
    ]

    process = subprocess.Popen(cmd, env=env)

    # Robust Polling Loop
    import requests

    start_time = time.time()
    started = False
    while time.time() - start_time < 45:  # Increased to 45s for slower CI environments
        try:
            response = requests.get(f"http://localhost:{port}", timeout=5)
            if response.status_code == 200:
                started = True
                break
        except requests.RequestException:
            pass
        time.sleep(1)

    if not started:
        process.terminate()
        pytest.fail(f"Streamlit dashboard failed to start on port {port} within 45 seconds.")

    yield f"http://localhost:{port}"

    process.terminate()
    process.wait()
