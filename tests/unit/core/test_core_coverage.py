import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner import analyzer, failure_corpus, loader, utils

# --- utils.py Coverage ---


def test_normalize_industry_cases():
    assert utils.normalize_industry("  FINTECH  ") == "finance"
    assert utils.normalize_industry("Unknown Industry") == "unknown_industry"
    assert utils.normalize_industry("") == "generic"
    assert utils.normalize_industry(None) == "generic"


def test_is_path_safe_logic(tmp_path):
    # Zone A: Project Root (Always allowed)
    assert utils.is_path_safe(tmp_path / "file.txt", tmp_path) is True
    assert utils.is_path_safe(".", tmp_path) is True

    # Zone B (Temp) - Allow if relative and not jailed
    base = tmp_path / "project"
    base.mkdir()
    import tempfile

    temp_dir = Path(tempfile.gettempdir())
    relative_to_temp = os.path.relpath(temp_dir / "secret.txt", base)
    with patch.dict(os.environ, {"AEH_STRICT_JAIL": "0"}):
        # Even if it's in a temp dir, relative paths are NOT allowed to escape the base
        assert utils.is_path_safe(relative_to_temp, base) is False
        # Absolute path in temp dir IS allowed (dynamic vault/teardown)
        assert utils.is_path_safe(temp_dir / "secret.txt", base) is True

    # Jailed branch (Trigger lines 74-76)
    with patch.dict(os.environ, {"AEH_STRICT_JAIL": "1"}):
        assert utils.is_path_safe(relative_to_temp, base) is False


def test_is_path_safe_resolution_error(tmp_path):
    from pathlib import Path as RealPath

    class MockPath(RealPath):
        def resolve(self, *args, **kwargs):
            if "fail" in str(self):
                raise Exception("Resolution failure")
            return super().resolve(*args, **kwargs)

    with patch("eval_runner.utils.Path", side_effect=MockPath):
        assert utils.is_path_safe("fail_path", tmp_path) is False


def test_get_canonical_path_logic():
    assert utils.get_canonical_path("") == ""
    assert utils.get_canonical_path("C:\\TEMP") == "c:/temp"


@pytest.mark.asyncio
async def test_safe_run_async_logic():
    async def sample_coro():
        return "success"

    # 1. With existing loop (Threaded branch)
    result = utils.safe_run_async(sample_coro())
    assert result == "success"

    # 2. Without existing loop (Standard run branch)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as exe:
        fut = exe.submit(utils.safe_run_async, sample_coro())
        assert fut.result() == "success"


def test_rmtree_resilient_error_handling(tmp_path):
    path = tmp_path / "unfixable"
    path.mkdir()

    # Manual trigger of handle_errors to ensure coverage across all OS platforms
    with patch("shutil.rmtree") as mock_rm:
        with patch("sys.stderr.write") as mock_err:
            from eval_runner.utils import rmtree_resilient

            rmtree_resilient(path)
            # Extract the internal handle_errors function from the call
            _, kwargs = mock_rm.call_args
            onerror = kwargs.get("onerror")

            # Simulate a chmod failure inside the handler
            with patch("os.chmod", side_effect=Exception("chmod fail")):
                onerror(os.chmod, str(path), None)

            output = "".join(call[0][0] for call in mock_err.call_args_list)
            assert "Failed to force R/W bits" in output or "chmod fail" in output


def test_rmtree_resilient_rename_retry(tmp_path):
    # Trigger line 150-153 (rename retry)
    path = tmp_path / "todelete"
    path.mkdir()

    # shutil.rmtree fails twice then succeeds
    with patch("shutil.rmtree", side_effect=[PermissionError, PermissionError, None]):
        with patch("time.sleep"):
            utils.rmtree_resilient(path, retries=2)


def test_generate_id():
    uid = utils.generate_id("test")
    assert uid.startswith("test-")
    assert len(uid.split("-")) == 3


def test_deep_diff_comprehensive():
    assert utils.deep_diff(1, 1.0) == []
    diff = utils.deep_diff(1, "1")
    assert any("types differ" in d for d in diff)
    d1 = {"a": 1, "b": 2}
    d2 = {"a": 1, "c": 3}
    diff = utils.deep_diff(d1, d2)
    assert any("b: key missing" in d for d in diff)
    assert any("c: key extra" in d for d in diff)
    diff = utils.deep_diff([1, 2], [1, 2, 3])
    assert any("lengths differ" in d for d in diff)
    d1 = {"nested": {"list": [1, {"x": 1}]}}
    d2 = {"nested": {"list": [1, {"x": 2}]}}
    diff = utils.deep_diff(d1, d2)
    assert any("nested.list[1].x: values differ" in d for d in diff)


# --- loader.py Coverage ---


def test_loader_load_csv_jsonl(tmp_path):
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("id,val\n1,a\n2,b", encoding="utf-8")
    assert len(loader.load_dataset(csv_file)) == 2

    jsonl_file = tmp_path / "test.jsonl"
    jsonl_file.write_text(
        json.dumps({"id": "j1"}) + "\n" + json.dumps({"id": "j2"}), encoding="utf-8"
    )
    assert len(loader.load_dataset(jsonl_file)) == 2


def test_loader_load_dataset_jsonl_error(tmp_path):
    jsonl_file = tmp_path / "bad.jsonl"
    jsonl_file.write_text("invalid json", encoding="utf-8")
    with patch("builtins.print"):
        assert loader.load_dataset(jsonl_file) == []


def test_loader_load_dataset_directory(tmp_path):
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir()
    s1 = scenario_dir / "s1.json"
    s1_data = {
        "metadata": {"id": "s1", "name": "S1", "compliance_level": "Standard"},
        "aes_version": 1.4,
        "workflow": {"nodes": [], "edges": []},
    }
    s1.write_text(json.dumps(s1_data), encoding="utf-8")
    assert len(loader.load_dataset(scenario_dir)) == 1


def test_loader_load_single_scenario(tmp_path):
    scenario_file = tmp_path / "single.json"
    data = {
        "metadata": {"id": "single", "name": "Single", "compliance_level": "Gold"},
        "aes_version": 1.4,
        "workflow": {"nodes": [], "edges": []},
    }
    scenario_file.write_text(json.dumps(data), encoding="utf-8")
    assert len(loader.load_dataset(scenario_file, format_type=".json")) == 1


def test_loader_load_scenario_dataset_resolve(tmp_path):
    scenario_file = tmp_path / "scen.json"
    data = {
        "metadata": {"id": "scen", "name": "Scen", "compliance_level": "Standard"},
        "aes_version": 1.4,
        "workflow": {"nodes": [], "edges": []},
        "dataset": {"path": "./data.csv"},
    }
    scenario_file.write_text(json.dumps(data), encoding="utf-8")
    res = loader.load_scenario(str(scenario_file))
    assert Path(res["dataset"]["path"]).is_absolute()


def test_loader_normalize_identity_fallback(tmp_path):
    scenario_file = tmp_path / "fallback.json"
    data = {
        "metadata": {"name": "Test", "compliance_level": "Standard"},
        "aes_version": 1.4,
        "workflow": {"nodes": [], "edges": []},
    }
    with (
        patch("jsonschema.validators.validator_for"),
        patch("eval_runner.loader.get_universal_registry"),
        patch("eval_runner.loader._get_schema"),
        patch("jsonschema.validators.Draft7Validator.validate"),
    ):
        scenario_file.write_text(json.dumps(data), encoding="utf-8")
        res = loader.load_scenario(str(scenario_file))
        assert res["id"] == "fallback"


def test_loader_load_dataset_benchmark_uri():
    with patch("eval_runner.benchmarks.gaia.GAIABenchmark.load", return_value=[{"id": "GAIA-1"}]):
        assert len(loader.load_dataset("gaia://2023")) == 1


def test_loader_load_dataset_invalid_uri():
    with patch("builtins.print") as mock_print:
        assert loader.load_dataset("unknown://protocol") == []
        mock_print.assert_any_call("      [Loader] Warning: Unknown benchmark scheme 'unknown'")


def test_loader_load_scenario_invalid_workflow(tmp_path):
    scenario_file = tmp_path / "invalid_workflow.json"
    scenario_file.write_text(
        json.dumps(
            {
                "id": "test",
                "metadata": {"id": "test", "compliance_level": "Standard", "name": "T"},
                "aes_version": 1.4,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Scenario missing required 'workflow' block"):
        loader.load_scenario(str(scenario_file))
    scenario_file.write_text(
        json.dumps(
            {
                "id": "test",
                "metadata": {"id": "test", "compliance_level": "Standard", "name": "T"},
                "aes_version": 1.4,
                "workflow": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid 'workflow' block structure"):
        loader.load_scenario(str(scenario_file))


def test_loader_load_scenario_unsupported_version(tmp_path):
    scenario_file = tmp_path / "old_version.json"
    scenario_file.write_text(
        json.dumps(
            {
                "id": "test",
                "metadata": {"id": "test", "compliance_level": "Standard", "name": "T"},
                "aes_version": 0.1,
                "workflow": {"nodes": [], "edges": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported AES version"):
        loader.load_scenario(str(scenario_file))


# --- analyzer.py Coverage ---


@pytest.mark.asyncio
async def test_analyzer_comprehensive():
    await analyzer.analyze_repo("http://github.com/telecom-agent")
    await analyzer.analyze_repo("http://github.com/finance-agent")
    results = await analyzer.analyze_repo("http://github.com/unknown")
    assert results[0]["metadata"]["pattern"] == "AgentExecutor(...)"


# --- failure_corpus.py Coverage ---


def test_failure_corpus_no_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    with patch("builtins.print") as mock_print:
        failure_corpus.search("test")
        mock_print.assert_any_call(
            "ℹ️  No master log found at runs/run.jsonl. Try running an evaluation first."
        )


def test_failure_corpus_comprehensive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    master_log = runs_dir / "run.jsonl"
    events = [
        {
            "event": "tool_call",
            "status": "error",
            "triage_tag": "API_FAILURE",
            "run_id": "r1",
            "timestamp": "1",
        },
        "",  # Empty line (Trigger line 33)
        {"event": "agent_response", "content": "hello world", "run_id": "r2", "timestamp": "2"},
        "invalid json line",
    ]
    for i in range(11):  # Trigger pagination (line 66)
        events.append(
            {
                "event": "tool_call",
                "status": "error",
                "triage_tag": "LIMIT",
                "run_id": f"L{i}",
                "timestamp": "3",
            }
        )

    with open(master_log, "w", encoding="utf-8") as f:
        for e in events:
            f.write((json.dumps(e) if isinstance(e, dict) else e) + "\n")

    with patch("builtins.print") as mock_print:
        failure_corpus.search("api failure")
        mock_print.assert_any_call("✅ Found 1 matching failure events:")
        failure_corpus.search(r"hello.*world")
        mock_print.assert_any_call("✅ Found 1 matching failure events:")
        failure_corpus.search("limit")
        all_calls = "".join(str(c) for c in mock_print.call_args_list)
        assert "more" in all_calls
        failure_corpus.search("nothing")
        mock_print.assert_any_call("❌ No matching failures found for 'nothing'.")
        failure_corpus.search(r"[")  # Invalid regex
        mock_print.assert_any_call("❌ No matching failures found for '['.")


def test_failure_corpus_error_handling():
    with (
        patch("eval_runner.failure_corpus.Path.exists", return_value=True),
        patch("builtins.open", side_effect=Exception("Read error")),
        patch("builtins.print") as mock_print,
    ):
        failure_corpus.search("test")
        mock_print.assert_any_call("❌ Error searching corpus: Read error")
