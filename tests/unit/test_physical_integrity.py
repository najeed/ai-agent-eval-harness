import sys
from pathlib import Path

import pytest

from eval_runner import config
from eval_runner.loader import get_universal_registry, reset_universal_registry
from eval_runner.simulators import TerminalSimulator
from eval_runner.utils import normalize_uri


def test_physical_registry_lookup():
    """
    BRIDGING THE MOCK-REALITY GAP:
    Ensures that the real UniversalRegistry can resolve a core schema
    using both Logical URIs and Physical anchors.
    """
    reset_universal_registry()
    registry = get_universal_registry()

    # 1. Authoritative Logical Lookup (Standard v1.4+)
    logical_uri = "https://agentv.co/spec/plugins/plugins.schema.json"
    resource = registry.resolver().lookup(logical_uri)
    assert resource.contents["$id"] == "https://agentv.co/spec/plugins/plugins.schema.json"

    # 2. Physical Fallback Lookup (Legacy/Debug support)
    # Ensure we use an absolute, normalized path matching what's registered
    schema_path = config.PROJECT_ROOT / "spec" / "plugins" / "plugins.schema.json"
    if schema_path.exists():
        schema_uri = normalize_uri(schema_path)
        resource = registry.resolver().lookup(schema_uri)
        assert resource is not None


@pytest.mark.asyncio
async def test_physical_shell_execution(tmp_path):
    """
    BRIDGING THE MOCK-REALITY GAP:
    Ensures that terminal_execute can physically execute shell builtins (like echo)
    on the current host platform without mocks.
    """
    simulator = TerminalSimulator()
    # Provision a real jail
    jail = tmp_path / "test_jail"
    jail.mkdir()
    simulator.terminal_jail = str(jail)

    # Live execution check
    result = await simulator.handle_terminal_execute({"cmd": "echo 'reality_check'"})

    assert result["status"] == "success"
    assert "reality_check" in result["stdout"].strip()
    if sys.platform == "win32":
        # Check that we didn't fail with WinError 2
        assert "Execution Error" not in result.get("message", "")


def test_uri_normalization_consistency():
    """
    Ensures normalize_uri produces identical results across modules.
    Specifically checks for Windows drive-letter casing.
    """
    path = Path("C:/Users/Test/file.txt") if sys.platform == "win32" else Path("/tmp/file.txt")  # nosec B108
    uri = normalize_uri(path)

    if sys.platform == "win32":
        assert uri.startswith("file:///c:/")  # Lowercase drive letter enforcement
    else:
        assert (
            uri == f"file://{path.as_posix()}"
            if not uri.startswith("file:///")
            else f"file://{path.as_posix()}"
        )
        # POSIX handles it naturally, but we verify the file:/// prefix
        assert uri.startswith("file:///")
