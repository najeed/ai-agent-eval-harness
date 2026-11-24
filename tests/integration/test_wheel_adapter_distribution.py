"""Release-only proof that the wheel contains and imports every adapter package."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def _built_wheel(tmp_path_factory) -> Path:
    """Build the distributable wheel once outside the checkout for release packaging tests."""
    if os.getenv("AGENTV_RELEASE_PACKAGING", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("AGENTV_RELEASE_PACKAGING=1 enables artifact validation")

    build_root = tmp_path_factory.mktemp("wheel_build")
    project = Path(__file__).resolve().parents[2]
    source = build_root / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        if (project / name).is_file():
            shutil.copy2(project / name, source / name)
    for name in ("eval_runner", "agentv_runtime", "dataproc_engine", "industries", "spec"):
        shutil.copytree(
            project / name,
            source / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".agentv", "jails"),
        )
    wheels = build_root / "wheels"
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
        timeout=900,
        capture_output=True,
    )
    return next(wheels.glob("agentv_runtime-*.whl"))


@pytest.mark.release_packaging
def test_mutation_package_installs_and_imports_from_wheel(tmp_path: Path, _built_wheel: Path):
    """Keep all build output outside the checkout and prove wheel-owned module imports."""
    if os.getenv("AGENTV_RELEASE_PACKAGING", "").strip() != "1":
        pytest.skip("AGENTV_RELEASE_PACKAGING=1 enables artifact validation")
    environment = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True, timeout=180)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(_built_wheel)],
        check=True,
        timeout=120,
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
            "from eval_runner.loader import get_internal_spec_root, get_scenario_validator",
            "assert get_internal_spec_root().resolve().is_relative_to(root)",
            "assert (get_internal_spec_root() / 'aes/aes.schema.json').is_file()",
            "assert get_scenario_validator().schema['title'] == 'AES Root Schema (v1.4.0)'",
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
def test_wheel_installs_and_discovers_all_adapter_modules(
    tmp_path: Path, _built_wheel: Path
) -> None:
    """Install the built wheel into a clean venv and import every adapter module."""
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        timeout=180,
    )

    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--no-deps", str(_built_wheel)],
        check=True,
        timeout=120,
    )

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    discovery = "\n".join(
        [
            "import sys, importlib, pkgutil",
            "sys.path.append(sys.argv[1])",
            "import eval_runner.adapters as adapters",
            "modules = pkgutil.walk_packages(adapters.__path__, adapters.__name__ + '.')",
            "modules = sorted(module.name for module in modules)",
            "assert modules, 'wheel contains no adapter modules'",
            "for module in modules: importlib.import_module(module)",
            "print('\\n'.join(modules))",
        ]
    )
    completed = subprocess.run(
        [str(venv_python), "-c", discovery, sysconfig.get_paths()["purelib"]],
        cwd=venv_dir,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert "eval_runner.adapters.openapi" in completed.stdout
    assert "eval_runner.adapters.openai" in completed.stdout
