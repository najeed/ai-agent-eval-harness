import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.publication_suite.conductor import Conductor, run_worker


@pytest.fixture
def mock_args(tmp_path):
    args = MagicMock()
    args.path = str(tmp_path / "scenarios")
    args.agent_name = "test-agent"
    args.protocol = "http"
    args.agent = "http://localhost"
    args.runs = 2
    args.parallel = 1
    args.pilot = False
    args.seed = 42

    (tmp_path / "scenarios").mkdir(exist_ok=True)
    return args


def test_conductor_init(mock_args):
    conductor = Conductor(mock_args)
    assert conductor.args == mock_args
    assert conductor.base_dir.exists()
    assert "batch_" in conductor.base_dir.name


def test_conductor_get_scenario_subset(mock_args, tmp_path):
    scenario_dir = Path(mock_args.path)
    for i in range(15):
        (scenario_dir / f"scen_{i}.json").write_text("{}")

    conductor = Conductor(mock_args)

    # Standard mode
    scenarios = conductor._get_scenario_subset()
    assert len(scenarios) == 15

    # Pilot mode
    mock_args.pilot = True
    scenarios = conductor._get_scenario_subset()
    assert len(scenarios) == 10


def test_conductor_run_serial(mock_args, tmp_path):
    mock_args.pilot = True  # Forces serial
    scenario_dir = Path(mock_args.path)
    (scenario_dir / "scen_1.json").write_text("{}")

    conductor = Conductor(mock_args)

    with patch("eval_runner.publication_suite.conductor.run_worker") as mock_worker:
        mock_worker.return_value = {"success": True, "run_id": "run_0"}
        manifest_path = conductor.run()
        assert manifest_path.exists()
        with open(manifest_path) as f:
            manifest = json.load(f)
            assert manifest["agent_name"] == "test-agent"
            assert len(manifest["runs"]) == 5  # 5 runs per scenario in pilot mode


def test_conductor_run_parallel(mock_args, tmp_path):
    mock_args.pilot = False
    mock_args.parallel = 2
    scenario_dir = Path(mock_args.path)
    (scenario_dir / "scen_1.json").write_text("{}")

    conductor = Conductor(mock_args)

    # Mock Pool
    mock_pool_instance = MagicMock()
    mock_pool_instance.imap_unordered.return_value = [{"success": True, "run_id": "run_0"}]
    mock_pool_instance.__enter__.return_value = mock_pool_instance

    with patch("multiprocessing.Pool", return_value=mock_pool_instance):
        manifest_path = conductor.run()
        assert manifest_path.exists()


def test_run_worker_success(tmp_path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    scenario_path = tmp_path / "scen.json"
    scenario_path.write_text("{}")

    task = (scenario_path, "agent", "http", "url", 42, output_dir, "run_0")

    # Mock subprocess.run to succeed and create a log file
    def mock_run(cmd, env, capture_output, text):
        log_dir = Path(env["RUN_LOG_DIR"])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "log.jsonl").write_text('{"event": "test"}')
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = run_worker(task)
        assert result["success"] is True
        assert result["run_id"] == "run_0"
        assert Path(result["log_path"]).exists()


def test_run_worker_no_log(tmp_path):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    scenario_path = tmp_path / "scen.json"
    scenario_path.write_text("{}")

    task = (scenario_path, "agent", "http", "url", 42, output_dir, "run_0")

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        result = run_worker(task)
        assert result["success"] is False
        assert "No log file generated" in result["error"]


def test_run_worker_exception(tmp_path):
    task = (Path("scen.json"), "agent", "http", "url", 42, tmp_path, "run_0")
    with patch("subprocess.run", side_effect=Exception("Crash")):
        result = run_worker(task)
        assert result["success"] is False
        assert "Crash" in result["error"]
