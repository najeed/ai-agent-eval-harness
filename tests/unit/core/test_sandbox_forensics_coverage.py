import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.forensics import ForensicCollector, ForensicRelevanceEngine, dict_diff, list_diff
from eval_runner.tool_sandbox import ResourceRegistry, SharedStateRegistry, ToolSandbox

# --- forensics.py gaps ---


def test_list_diff_edge_cases():
    """Missing lines 30, 54, 68: empty old, added item, identical state."""
    # Empty old
    assert list_diff([], [{"id": 1}]) == [{"id": 1}]
    # Added item
    old = [{"id": 1}]
    new = [{"id": 1}, {"id": 2}]
    res = list_diff(old, new)
    assert len(res["__LIST_DIFF__"]["added"]) == 1
    # Identical state (returns None)
    assert list_diff([{"id": 1}], [{"id": 1}]) is None


def test_dict_diff_edge_cases():
    """Missing lines 83, 91-93, 100: dict_diff missing/list cases."""
    old = {"a": 1, "list": [1]}
    new = {"a": 1, "b": 2, "list": [2]}  # b added, list modified
    res = dict_diff(old, new)
    assert res["b"] == 2
    assert res["list"] == [2]

    # Deleted
    res2 = dict_diff({"a": 1}, {})
    assert res2["a"] == "__DELETED__"


def test_relevance_engine_returns():
    """Missing lines 135, 143, 148, 161, 168: is_relevant early returns."""
    engine = ForensicRelevanceEngine({"mandatory_patterns": [r"important.*"]})
    # Tier 1
    assert engine.is_relevant(Path("forensics/audit.log")) is True
    # Global safety (.name)
    assert engine.is_relevant(Path(".hidden")) is False
    # Blacklist (pytest-)
    assert engine.is_relevant(Path("pytest-output.txt")) is False
    # Tier 2
    assert engine.is_relevant(Path("important_file.txt")) is True
    # Tier 3 (wrong extension)
    assert engine.is_relevant(Path("file.exe")) is False


def test_relevance_engine_depth_pruning():
    """Missing lines 201-204: compute_filtered_ledger depth pruning."""
    engine = ForensicRelevanceEngine()
    tmp_dir = Path("tmp_ledger_test").absolute()
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(exist_ok=True)
    (tmp_dir / "file.txt").write_text("data")
    (tmp_dir / "sub").mkdir(exist_ok=True)
    (tmp_dir / "sub" / "deep.txt").write_text("data")

    # Depth 1 limit means it allowed sub/ (depth 1)
    # Let's add a deeper file to verify pruning
    (tmp_dir / "sub" / "deep").mkdir(exist_ok=True)
    (tmp_dir / "sub" / "deep" / "too_deep.txt").write_text("data")

    ledger = engine.compute_filtered_ledger(tmp_dir, [], run_id=None)
    assert "file.txt" in ledger
    assert "sub/deep.txt" in ledger
    assert "sub/deep/too_deep.txt" not in ledger

    shutil.rmtree(tmp_dir)


def test_collector_success_paths():
    """Missing lines 240-249, 260-273, 336, 345-369: collector success paths."""
    tmp_root = Path("tmp_collector_test").absolute()
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(exist_ok=True)
    logs_dir = tmp_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    collector = ForensicCollector("test-run", logs_dir)

    # register_artifact success
    f1 = tmp_root / "art.txt"
    f1.write_text("content")
    collector.register_artifact(f1, "art.txt")
    assert len(collector._artifacts) == 1

    # archive_plugin success
    p1 = tmp_root / "my_plugin.py"
    p1.write_text("print(1)")
    p_hash = collector.archive_plugin(p1)
    assert p_hash is not None

    # register_raw_interaction success
    collector.register_raw_interaction({"q": 1}, {"a": 1})

    # collect success
    ledger = collector.collect()
    assert "art.txt" in ledger
    assert any("my_plugin" in k for k in ledger)

    shutil.rmtree(tmp_root)


def test_collector_snapshot_exception():
    """Missing lines 304-305: snapshot_state exception."""
    collector = ForensicCollector("run", Path("logs"))
    with patch("builtins.open", side_effect=Exception("Write Error")):
        collector.snapshot_state({"a": 1}, 0)  # Log error


# --- tool_sandbox.py gaps ---


def test_resource_registry_full():
    """Missing lines 35-39: registry file/dir cleanup."""
    registry = ResourceRegistry()
    tmp = Path("tmp_reg").absolute()
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(exist_ok=True)
    f = tmp / "f.txt"
    f.write_text("x")
    d = tmp / "sub"
    d.mkdir(exist_ok=True)

    registry.register(f)
    registry.register(d)
    registry.cleanup()

    assert not f.exists()
    assert not d.exists()
    if tmp.exists():
        shutil.rmtree(tmp)


def test_shared_state_wildcard():
    """Missing line 115: pattern.endswith(':*')."""
    registry = SharedStateRegistry({"a": {"reads": ["ns:*"]}})
    assert registry.read("a", "ns:key") is None  # Allowed but empty
    assert registry.read("a", "other:key") is None  # Denied


@pytest.mark.asyncio
async def test_sandbox_lifecycle_coverage():
    """Missing lines 166, 189-207, 220-226, 238-246, 257-262, 386, 403-420, 528-533."""
    scenario = {
        "id": "test_id",
        "run_id": "test-run",
        "enabled_shims": ["git"],
        "metadata": {"cleanup_workspace": True},
    }

    # Mock event bus
    bus = MagicMock()

    # Mock Forensics
    forensics = MagicMock()
    forensics.register_artifact = MagicMock()
    forensics.snapshot_state = MagicMock()

    sandbox = ToolSandbox(scenario, event_bus=bus, forensics=forensics)

    # Line 166: terminal_jail with run_id
    assert "test-run" in str(sandbox.terminal_jail)

    await sandbox.setup()
    # Line 220-226: setup forensic baseline
    forensics.snapshot_state.assert_called()

    # Line 238-246: register_artifact
    sandbox.register_artifact("dummy.txt")
    forensics.register_artifact.assert_called()

    # Line 189-207 / 403-420: get_full_state aggregation
    state = await sandbox.get_full_state()
    assert "world" in state
    assert "shims" in state or "git" in state  # Depending on iteration

    # Shim error in snapshot
    with patch.object(sandbox, "get_active_simulators") as mock_sims:
        bad_sim = AsyncMock()
        bad_sim.get_snapshot.side_effect = Exception("Snap Fail")
        mock_sims.return_value = {"bad": bad_sim}
        await sandbox.get_full_state()
        # Should log warning and continue

    # Line 386: event_bus.emit
    from unittest.mock import ANY

    await sandbox.execute("unknown", {})
    bus.emit.assert_called_with("world_state_change", ANY)

    # Line 257-262: simulator cleanup
    await sandbox.teardown()


@pytest.mark.asyncio
async def test_sandbox_discovery_success_and_fail():
    """Missing lines 528-533, 533-535."""
    scenario = {"enabled_shims": ["git", "unknown"]}
    sandbox = ToolSandbox(scenario)

    with patch("eval_runner.simulators.GitSimulator", return_value=MagicMock()):
        sims = sandbox.get_active_simulators()
        assert "git" in sims

    # Unknown type coverage (line 533)
    with patch("eval_runner.config.RegistryManager.get_resolved_registry") as mock_reg:
        mock_reg.return_value = {"shims": {"x": {"type": "unknown_type"}}}
        sandbox2 = ToolSandbox({"enabled_shims": ["x"]})
        sims2 = sandbox2.get_active_simulators()
        assert "x" not in sims2


def test_sandbox_relevant_shims_non_dict():
    """Missing lines 449-450: non-dict expected_outcome."""
    scenario = {"workflow": {"nodes": [{"expected_outcome": "not-a-dict"}]}}
    sandbox = ToolSandbox(scenario)
    assert sandbox._get_scenario_relevant_shims() == set()
