"""
tests/ui/conftest.py

Shared fixtures for Playwright UI tests.

The ``worker_id`` fixture is declared as a local fallback so the conftest
works in plain ``pytest`` runs (no ``-n`` flag) where pytest-xdist does
not inject ``worker_id`` automatically.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def browser_ui_build_dir(tmp_path_factory):
    """Use an explicit release artifact or build current sources in session temp."""
    repository = Path(__file__).resolve().parents[2]
    configured = os.getenv("AGENTV_BROWSER_UI_BUILD_DIR")
    if configured:
        directory = Path(configured)
        if not directory.is_absolute():
            directory = repository / directory
        if not (directory / "index.html").is_file():
            pytest.fail(f"Configured browser UI build is missing index.html: {directory}")
        return directory

    console = repository / "ui" / "visual-console"
    node = shutil.which("node")
    vite = console / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        message = (
            "Browser acceptance needs Node and installed Visual Console dependencies (npm ci)."
        )
        if os.getenv("AGENTV_REQUIRE_BROWSER_ACCEPTANCE") == "1":
            pytest.fail(message)
        pytest.skip(message)

    build_root = tmp_path_factory.mktemp("browser-ui-build")
    directory = build_root / "dist"
    config_file = build_root / "vite.config.mjs"
    config_file.write_text(
        "import base from " + json.dumps((console / "vite.config.ts").as_posix()) + ";\n"
        "export default {...base, cacheDir: "
        + json.dumps((build_root / "cache").as_posix())
        + ", build: {...base.build, outDir: "
        + json.dumps(directory.as_posix())
        + "}};\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [node, str(vite), "build", "--config", str(config_file), "--configLoader", "runner"],
            cwd=console,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=float(os.getenv("AGENTV_ACCEPTANCE_TIMEOUT", "180")),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.fail(f"Unable to build current Visual Console sources: {error}")
    if completed.returncode != 0 or not (directory / "index.html").is_file():
        pytest.fail(
            "Visual Console production build failed:\n"
            + (completed.stdout + completed.stderr)[-8000:]
        )
    return directory


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
