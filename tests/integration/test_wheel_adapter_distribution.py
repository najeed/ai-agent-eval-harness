"""Release-only proof that the wheel contains and imports every adapter package."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest


@pytest.mark.release_packaging
def test_mutation_package_installs_and_imports_from_wheel(tmp_path):
    """Keep all build output outside the checkout and prove wheel-owned module imports."""
    if os.getenv("AGENTV_RELEASE_PACKAGING") != "1":
        pytest.skip("AGENTV_RELEASE_PACKAGING=1 enables artifact validation")
    project = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        if (project / name).is_file():
            shutil.copy2(project / name, source / name)
    for name in ("eval_runner", "agentv_runtime", "dataproc_engine", "industries"):
        shutil.copytree(
            project / name,
            source / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".agentv", "jails"),
        )
    wheels = tmp_path / "wheels"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheels),
            str(source),
        ],
        check=True,
        timeout=600,
        capture_output=True,
    )
    environment = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, timeout=90)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next(wheels.glob("*.whl"))
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        check=True,
        timeout=90,
        capture_output=True,
    )
    # Reuse already validated third-party dependencies, after the clean venv's
    # own site-packages; every first-party module must come from the wheel.
    discovery = "\n".join(
        [
            "import sys, importlib, pkgutil, pathlib",
            "sys.path.append(sys.argv[1])",
            "import eval_runner.mutations as mutations",
            "root = pathlib.Path(sys.prefix).resolve()",
            "modules = list(pkgutil.walk_packages(mutations.__path__, mutations.__name__ + '.'))",
            "assert len(modules) >= 10",
            "for item in modules:",
            "    module = importlib.import_module(item.name)",
            "    location = pathlib.Path(module.__file__).resolve()",
            "    assert location.is_relative_to(root), str(location)",
            "assert importlib.util.find_spec('eval_runner.mutator') is None",
            "print(len(modules), 'wheel-owned mutation modules imported')",
        ]
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [str(python), "-c", discovery, sysconfig.get_paths()["purelib"]],
        cwd=environment,
        env=env,
        check=True,
        timeout=90,
        capture_output=True,
        text=True,
    )
    assert "wheel-owned mutation modules imported" in completed.stdout


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
        # Source distributions can take several minutes to build on slower CI
        # workers; this check validates wheel contents, not build throughput.
        timeout=600,
    )
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        timeout=60,
    )

    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next(wheel_dir.glob("agentv_runtime-*.whl"))
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
