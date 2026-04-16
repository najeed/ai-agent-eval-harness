import json

import pytest

from eval_runner.forensics import ForensicCollector, ForensicRelevanceEngine


def test_forensics_junk_files(tmp_path, monkeypatch):
    import eval_runner.config as config

    monkeypatch.setattr(config, "SYSTEM_JUNK_FILES", ["Thumbs.db"])
    engine = ForensicRelevanceEngine()

    # line 65
    assert engine.is_relevant(tmp_path / "Thumbs.db") is False


def test_forensics_industrial_blacklist(tmp_path):
    engine = ForensicRelevanceEngine()
    # line 73
    assert engine.is_relevant(tmp_path / "pytest-1234") is False


def test_forensics_exclusion_patterns(tmp_path):
    engine = ForensicRelevanceEngine({"exclusion_patterns": [r"mock_.*"]})
    # line 76
    assert engine.is_relevant(tmp_path / "mock_test.json") is False


def test_forensics_run_prefix(tmp_path):
    engine = ForensicRelevanceEngine()
    # line 81-82
    assert (
        engine.is_relevant(tmp_path / "other_run123.json", run_id="myrun", is_dedicated_dir=False)
        is False
    )


def test_forensics_size_exception(tmp_path, monkeypatch):
    engine = ForensicRelevanceEngine({"extensions": [".txt"]})
    test_file = tmp_path / "test.txt"

    class MockStat:
        @property
        def st_size(self):
            raise PermissionError()

    def mock_stat(self):
        return MockStat()

    # Python pathlib stat mock
    import pathlib

    with monkeypatch.context() as m:
        # 103-104 FileNotFoundError or PermissionError
        m.setattr(pathlib.Path, "stat", mock_stat)
        assert engine.is_relevant(test_file) is False


def test_forensics_compute_ledger_prune(tmp_path):
    # 128-129 depth pruning
    engine = ForensicRelevanceEngine()
    d1 = tmp_path / "d1"
    d2 = d1 / "d2"
    d2.mkdir(parents=True)
    f = d2 / "nested.txt"
    f.write_text("test")
    # depth > max_depth (1 for non dedicated dir)
    res = engine.compute_filtered_ledger(tmp_path, [], run_id="run123")
    # should not contain nested.txt
    assert len(res) == 0


def test_forensics_compute_ledger_hash_fail(tmp_path, monkeypatch):
    # 140-141 hashing exception
    engine = ForensicRelevanceEngine({"mandatory_patterns": [r".*test.*"]})
    f = tmp_path / "test1.txt"
    f.write_text("data")

    def raise_err(*args):
        raise ValueError("Hash Failed")

    with monkeypatch.context() as m:
        m.setattr("eval_runner.forensics.compute_file_hash", raise_err)
        # We make it dedicated dir so it includes all
        res = engine.compute_filtered_ledger(tmp_path, [], run_id=tmp_path.name)
        assert "test1.txt" not in res


def test_collector_register_missing_path(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # 161 path not exists
    c.register_artifact(tmp_path / "missing", "alias")
    assert len(c._artifacts) == 0


def test_collector_register_irrelevant_path(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    junk = tmp_path / "pytest-abc"
    junk.write_text("data")
    # 166-170
    c.register_artifact(junk, "alias")
    assert len(c._artifacts) == 0


def test_collector_archive_missing_path(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # 182
    with pytest.raises(FileNotFoundError):
        c.archive_plugin(tmp_path / "missing.py")


def test_collector_snapshot_exception(tmp_path, monkeypatch):
    c = ForensicCollector("r1", tmp_path)

    # 204-213 Exception during json dump
    def raise_err(*args, **kwargs):
        raise TypeError("Not serializable")

    with monkeypatch.context() as m:
        m.setattr(json, "dump", raise_err)
        c.snapshot_state({"obj": lambda x: x}, 1)
        assert 1 not in c._state_snapshots


def test_collector_collect_early_return(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    # 221
    assert c.collect() == {}


def test_collector_collect_same_dest(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    val = tmp_path / "forensics" / "test.txt"
    val.parent.mkdir(parents=True)
    val.write_text("data")
    # Bypass register relevance check for test
    c._artifacts.append({"path": val, "alias": "test.txt"})
    # dest will be identical to src (234)
    res = c.collect()
    assert "test.txt" in res


def test_collector_collect_exceptions(tmp_path, monkeypatch):
    c = ForensicCollector("r1", tmp_path)
    val = tmp_path / "test.txt"
    val.write_text("data")
    c._artifacts.append({"path": val, "alias": "test.txt"})

    # Simulate copy fail 236-237
    def mock_copy(*args):
        raise OSError("Copy failed")

    with monkeypatch.context() as m:
        import shutil

        m.setattr(shutil, "copy2", mock_copy)
        res = c.collect()
        assert "test.txt" not in res


def test_forensics_junk_extensions(tmp_path, monkeypatch):
    import eval_runner.config as config

    monkeypatch.setattr(config, "SYSTEM_JUNK_EXTENSIONS", [".tmp"])
    engine = ForensicRelevanceEngine()
    assert engine.is_relevant(tmp_path / "test.tmp") is False


def test_forensics_size_cap_exceed(tmp_path):
    engine = ForensicRelevanceEngine({"extensions": [".txt"], "max_artifact_size": 2})
    f = tmp_path / "test.txt"
    f.write_text("abc")
    assert engine.is_relevant(f) is False


def test_forensics_size_cap_pass(tmp_path):
    engine = ForensicRelevanceEngine({"extensions": [".txt"], "max_artifact_size": 100})
    f = tmp_path / "test.txt"
    f.write_text("abc")
    assert engine.is_relevant(f) is True


def test_forensics_compute_ledger_exclude(tmp_path):
    engine = ForensicRelevanceEngine()
    f = tmp_path / "forensics" / "test.txt"
    f.parent.mkdir()
    f.write_text("a")
    res = engine.compute_filtered_ledger(tmp_path, ["test.txt"])
    assert "test.txt" not in res


def test_collector_snapshot_success(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    c.snapshot_state({"a": 1}, 5)
    assert 5 in c._state_snapshots


def test_collector_collect_with_snapshots(tmp_path):
    c = ForensicCollector("r1", tmp_path)
    c.snapshot_state({"a": 1}, 10)
    res = c.collect()
    assert len(res) == 1
