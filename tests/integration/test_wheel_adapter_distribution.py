"""Release-only proof that the wheel contains and imports every adapter package."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.release_packaging
def test_wheel_installs_and_discovers_all_adapter_modules(tmp_path: Path) -> None:
    """Build the wheel, install it into a clean venv, and import every adapter module."""
    if os.getenv("AGENTV_RELEASE_PACKAGING", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("AGENTV_RELEASE_PACKAGING=1 is required for wheel release validation.")

    project_root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheel"
    venv_dir = tmp_path / "venv"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=project_root,
        check=True,
        timeout=180,
    )
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        timeout=60,
    )

    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next(wheel_dir.glob("agentv-*.whl"))
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", str(wheel)],
        check=True,
        timeout=300,
    )

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    discovery = "\n".join(
        [
            "import importlib",
            "import pkgutil",
            "import eval_runner.adapters as adapters",
            "modules = pkgutil.walk_packages(adapters.__path__, adapters.__name__ + '.')",
            "modules = sorted(module.name for module in modules)",
            "assert modules, 'wheel contains no adapter modules'",
            "for module in modules: importlib.import_module(module)",
            "print('\\n'.join(modules))",
        ]
    )
    completed = subprocess.run(
        [str(venv_python), "-c", discovery],
        cwd=venv_dir,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert "eval_runner.adapters.openapi" in completed.stdout
    assert "eval_runner.adapters.openai" in completed.stdout
