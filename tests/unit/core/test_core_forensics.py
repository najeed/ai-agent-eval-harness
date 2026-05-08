"""
Consolidated Forensics & Trust Test Suite for AgentV Evaluation Harness.
Verifies state diffing, forensic relevance (pruning, blacklists), triage (root cause analysis),
and the Trust Protocol (artifact signing, integrity verification).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner import config
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.forensics import ForensicCollector, ForensicRelevanceEngine, dict_diff, list_diff
from eval_runner.taxonomy import CausalChain, FailureCategory
from eval_runner.triage import Confidence, TriageEngine

# --- 1. State Diffing Mechanics ---


def test_diff_mechanics():
    # List Diff
    assert list_diff([{"id": 1}], [{"id": 1}, {"id": 2}])["__LIST_DIFF__"]["added"] == [{"id": 2}]

    # Dict Diff
    old = {"a": 1, "nested": {"k": "v1"}}
    new = {"a": 2, "nested": {"k": "v2"}, "b": 3}
    res = dict_diff(old, new)
    assert res["a"] == 2
    assert res["nested"]["k"] == "v2"


# --- 2. Forensic Relevance & Collection ---


def test_forensic_relevance(tmp_path):
    # Blacklists & Extensions
    with patch("eval_runner.config.SYSTEM_JUNK_FILES", ["Thumbs.db"]):
        engine = ForensicRelevanceEngine({"extensions": [".log"]})
        assert engine.is_relevant(tmp_path / "Thumbs.db") is False

        audit_log = tmp_path / "audit.log"
        audit_log.write_text("data")
        assert engine.is_relevant(audit_log) is True


def test_forensic_collection(tmp_path):
    collector = ForensicCollector("run-1", tmp_path)
    # Snapshots (uses 'index' parameter)
    collector.snapshot_state({"a": 1}, 1)
    assert 1 in collector._state_snapshots
    # Artifacts
    f = tmp_path / "artifact.log"
    f.write_text("data")
    # Bypass relevance check for raw test
    collector._artifacts.append({"path": f, "alias": "a.log"})
    res = collector.collect()
    assert "a.log" in res


# --- 3. Triage & Weighted Root Cause ---


def test_triage_engine_logic():
    # Connection Error
    history = [
        {"identity": "system_id", "content": {"status": "error", "message": "Connection refused"}}
    ]
    results = [{"task_id": "t1", "metrics": [{"success": False}], "conversation_history": history}]
    TriageEngine.apply_triage(results)
    assert results[0].get("triage_tag") == "INFRA_CONNECTION_FAILED"


def test_causal_chain_ranking():
    """Verifies that the Weighted Evidence Model ranks evidence correctly."""
    chain = CausalChain()
    chain.add(
        FailureCategory.INFRA_TIMEOUT, "Network timeout", turn_index=0, severity="high", rank=5
    )
    chain.add(FailureCategory.LOGIC_STALL, "Agent slow", turn_index=0, severity="low", rank=0)

    history = [{"role": "agent", "content": "stimulus"}]
    result = {"conversation_history": history, "diagnostic_report": {"causal_chain": list(chain)}}
    diagnosis = TriageEngine.identify_root_cause(result)
    assert diagnosis["category"] == FailureCategory.INFRA_TIMEOUT
    assert diagnosis["confidence"] == Confidence.CERTAIN


# --- 4. Trust Protocol (Artifacts & Signing) ---


def test_artifact_trust_integrity(tmp_path, monkeypatch):

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    plugin = ArtifactPlugin()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "f1.txt").write_text("data")

    # Bundle & Sign
    res = plugin.bundle_artifacts(str(work_dir), ["f1.txt"])
    manifest_path = res["manifest_path"]
    assert Path(manifest_path).exists()

    # Verify
    v_res = plugin.verify_integrity(manifest_path)
    assert v_res["is_valid"] is True


# --- 5. Extended Coverage ---


def test_list_diff_advanced():
    # Empty inputs
    assert list_diff([], []) == []

    # Non-dict list
    assert list_diff([1], [2]) == [2]

    # No primary key
    assert list_diff([{"a": 1}], [{"a": 2}]) == [{"a": 2}]

    # Modified row
    old = [{"id": 1, "v": "old"}]
    new = [{"id": 1, "v": "new"}]
    res = list_diff(old, new)
    assert res["__LIST_DIFF__"]["modified"][0]["v"] == "new"

    # Identical state
    assert list_diff([{"id": 1}], [{"id": 1}]) is None


def test_dict_diff_deleted_key():
    # Deleted key
    old = {"a": 1, "b": 2}
    new = {"a": 1}
    res = dict_diff(old, new)
    assert res["b"] == "__DELETED__"


def test_collector_telemetry_failure(tmp_path):
    # resource_telemetry failure
    c = ForensicCollector("r1", tmp_path)
    with patch("psutil.Process", side_effect=Exception("PSUtil missing")):
        res = c.resource_telemetry
        assert res["status"] == "telemetry_unavailable"


def test_collector_init_telemetry_failure(tmp_path):
    # init_telemetry failure
    c = ForensicCollector("r1", tmp_path)
    # Make dir read-only or similar to trigger exception
    with patch("builtins.open", side_effect=OSError("Permission Denied")):
        with patch("eval_runner.forensics.logger.error") as mock_log:
            c.init_telemetry(["h1"])
            mock_log.assert_called()


def test_collector_raw_interaction_failure(tmp_path):
    # register_raw_interaction success/fail
    c = ForensicCollector("r1", tmp_path)
    c.register_raw_interaction({"p": 1}, {"r": 1})
    assert (tmp_path / "forensics" / "adapter_trace.jsonl").exists()

    with patch("builtins.open", side_effect=OSError("Write failed")):
        with patch("eval_runner.forensics.logger.error") as mock_log:
            c.register_raw_interaction({}, {})
            mock_log.assert_called()


def test_forensics_more_relevance(tmp_path):
    engine = ForensicRelevanceEngine()
    # Participation Root
    assert engine.is_relevant(tmp_path / "forensics" / "any.txt") is True
    # Hidden/Manifest
    assert engine.is_relevant(tmp_path / ".hidden") is False
    assert engine.is_relevant(tmp_path / "run_manifest.json") is False


def test_collector_full_suite(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # Success telemetry
    assert "memory_mb" in c.resource_telemetry

    # Register success
    f = tmp_path / "artifact.log"
    f.write_text("data")
    c.register_artifact(f, "a.log")
    assert len(c._artifacts) == 1

    # Archive plugin
    p = tmp_path / "plugin.py"
    p.write_text("print(1)")
    h = c.archive_plugin(p)
    assert h is not None
    assert (tmp_path / "forensics" / "plugins").exists()

    # Snapshot diff
    c.snapshot_state({"a": 1}, 0)
    c.snapshot_state({"a": 2}, 1)
    assert (tmp_path / "forensics" / "state_turn_001_diff.json").exists()

    # Init telemetry success
    c.init_telemetry(["h1", "h2"])
    assert (tmp_path / "forensics" / "telemetry.csv").exists()


def test_dict_diff_list_nested():
    old = {"l": [{"id": 1}]}
    new = {"l": [{"id": 1}, {"id": 2}]}
    res = dict_diff(old, new)
    assert "__LIST_DIFF__" in res["l"]


def test_list_diff_final_edges():
    # Deleted
    old = [{"id": 1}, {"id": 2}]
    new = [{"id": 2}]
    res = list_diff(old, new)
    assert 1 in res["__LIST_DIFF__"]["deleted"]

    # return None
    assert list_diff([{"id": 1}], [{"id": 1}]) is None


def test_snapshot_zero_change(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    c.snapshot_state({"a": 1}, 0)
    # Turn 1 with same state should return early
    c.snapshot_state({"a": 1}, 1)
    assert 1 not in c._state_snapshots


def test_diff_identical_nesting():
    # (dict_diff): nested dicts are identical
    old = {"a": {"b": 1}}
    new = {"a": {"b": 1}}
    assert dict_diff(old, new) == {}

    # (dict_diff): nested lists are identical
    old2 = {"a": [{"id": 1}]}
    new2 = {"a": [{"id": 1}]}
    assert dict_diff(old2, new2) == {}

    # (list_diff): old_map[val] != item but row_diff is empty
    # This happens if they compare != but dict_diff thinks they are equal?
    # Actually, let's try a subclass that fails equality but has same items
    class BadDict(dict):
        def __ne__(self, other):
            return True

    old3 = [{"id": 1, "v": 1}]
    new3 = [BadDict({"id": 1, "v": 1})]
    res = list_diff(old3, new3)
    # If list_diff uses != (line 55), it will enter. Then dict_diff returns {}
    # check 'if row_diff:' will be False.
    assert res is None


def test_relevance_patterns_extended(tmp_path):
    engine = ForensicRelevanceEngine()
    # Blacklist
    assert engine.is_relevant(tmp_path / "pytest-123") is False
    assert engine.is_relevant(tmp_path / "aes_test_jail-abc") is False

    # run_id mismatch in non-dedicated dir
    assert (
        engine.is_relevant(tmp_path / "other_id_file.txt", run_id="r1", is_dedicated_dir=False)
        is False
    )

    # Mandatory patterns
    # Assuming .log is in mandatory_patterns by default in config
    with patch("eval_runner.config.get_forensic_policy") as mock_policy:
        mock_policy.return_value = {
            "extensions": [".txt"],
            "mandatory_patterns": [r".*\.log$"],
            "exclusion_patterns": [],
            "max_artifact_size": 1000,
        }
        engine2 = ForensicRelevanceEngine()
        assert engine2.is_relevant(tmp_path / "important.log") is True


def test_oversized_artifact_and_errors(tmp_path):
    engine = ForensicRelevanceEngine({"max_artifact_size": 10})
    f = tmp_path / "big.txt"
    f.write_text("this is more than 10 bytes")

    # Oversized
    assert engine.is_relevant(f) is False

    # PermissionError
    with patch("pathlib.Path.stat", side_effect=PermissionError()):
        assert engine.is_relevant(f) is False


def test_ledger_depth_limit(tmp_path):
    # Depth limit in non-dedicated dir
    root = tmp_path / "root"
    root.mkdir()
    deep = root / "d1" / "d2" / "d3"
    deep.mkdir(parents=True)
    (deep / "file.txt").write_text("data")

    engine = ForensicRelevanceEngine({"extensions": [".txt"]})
    # run_id mismatching directory name means is_dedicated_dir=False
    ledger = engine.compute_filtered_ledger(root, [], run_id="other")
    # Depth 1 limit -> should not see file in d1/d2/d3
    assert "d1/d2/d3/file.txt" not in ledger


def test_ledger_hash_failure(tmp_path):
    # Hashing failure
    f = tmp_path / "fail.txt"
    f.write_text("data")
    engine = ForensicRelevanceEngine({"extensions": [".txt"]})
    with patch("eval_runner.forensics.compute_file_hash", side_effect=Exception("Hash fail")):
        ledger = engine.compute_filtered_ledger(tmp_path, [])
        assert "fail.txt" not in ledger


def test_collector_registration_edges(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # Non-existent
    c.register_artifact(tmp_path / "missing.txt", "m.txt")
    assert len(c._artifacts) == 0

    # Irrelevant
    f = tmp_path / "irrelevant.exe"
    f.write_text("data")
    with patch("eval_runner.forensics.ForensicRelevanceEngine.is_relevant", return_value=False):
        c.register_artifact(f, "i.exe")
        assert len(c._artifacts) == 0


def test_collector_archive_missing(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # raise FileNotFoundError
    with pytest.raises(FileNotFoundError):
        c.archive_plugin(tmp_path / "nonexistent.py")


def test_collector_collect_empty(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # Empty collect
    assert c.collect() == {}


def test_collector_collect_failure(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    f = tmp_path / "ok.txt"
    f.write_text("data")
    c.register_artifact(f, "ok.txt")

    # Copy failure
    with patch("shutil.copy2", side_effect=Exception("Copy failed")):
        ledger = c.collect()
        assert "ok.txt" not in ledger


def test_relevance_exclusion_patterns(tmp_path):
    engine = ForensicRelevanceEngine({"exclusion_patterns": [r".*\.tmp$"]})
    assert engine.is_relevant(tmp_path / "data.tmp") is False


def test_ledger_exclude_files(tmp_path):
    f1 = tmp_path / "keep.txt"
    f1.write_text("k")
    f2 = tmp_path / "skip.txt"
    f2.write_text("s")

    engine = ForensicRelevanceEngine({"extensions": [".txt"]})
    ledger = engine.compute_filtered_ledger(tmp_path, ["skip.txt"])
    assert "keep.txt" in ledger
    assert "skip.txt" not in ledger


def test_snapshot_failure(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # Mock open to fail
    with patch("builtins.open", side_effect=OSError("Disk Full")):
        with patch("eval_runner.forensics.logger.error") as mock_log:
            c.snapshot_state({"a": 1}, 0)
            mock_log.assert_called()
