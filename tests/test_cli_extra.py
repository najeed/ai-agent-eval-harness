import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import json
from pathlib import Path
from eval_runner import cli


@pytest.fixture
def mock_args():
    args = MagicMock()
    args.scenario = "test_scenario.json"
    args.path = "test_dir"
    args.attempts = 1
    args.protocol = "mock"
    args.agent = "null"
    args.limit = 10
    args.output_dir = "out"
    args.run_log_dir = "logs"
    args.per_run_logs = False
    args.master_log = False
    args.agent_cmd = ""
    args.agent_socket = ""
    args.input = "in.txt"
    args.model = "llama3"
    args.output = ""
    args.industry = ""
    args.seed = 42
    return args


# --- handle_aes_validate ---
def test_handle_aes_validate_dir(mock_args, tmp_path, monkeypatch):
    """Test 'aes validate' command with real isolated directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenario.aes.yaml").write_text("scenario_id: test", encoding="utf-8")
    mock_args.path = str(tmp_path)
    
    with patch("builtins.open"), \
         patch("json.loads", return_value={"type": "object"}), \
         patch("yaml.safe_load", return_value={"scenario_id": "test"}), \
         patch("jsonschema.validate"):
         
        cli.handle_aes_validate(mock_args)


# --- handle_replay ---
def test_handle_replay_success(mock_args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trace_file = tmp_path / "some_trace.jsonl"
    trace_file.write_text("{}", encoding="utf-8")
    
    mock_args.path = str(trace_file)
    with patch("eval_runner.cli.load_events") as mock_load:
         
        mock_load.return_value = [
            {"event": "run_start", "run_id": "1", "scenario": "s1"},
            {"event": "prompt", "role": "user", "content": "hi"},
            {"event": "agent_response", "step": 1, "content": "hello"},
            {"event": "tool_call", "tool": "search", "arguments": {}},
            {"event": "tool_result", "tool": "search", "result": "found"},
            {"event": "evaluation", "metric": "acc", "value": 1.0},
            {"event": "run_end", "status": "success"},
            {"event": "unknown"}
        ]
        cli.handle_replay(mock_args)


# --- run_scenario ---
@pytest.mark.asyncio
async def test_run_scenario_success(mock_args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scen.json").write_text("{}", encoding="utf-8")
    mock_args.scenario = "scen.json"
    with patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_engine:
         
        mock_engine.return_value = []
        await cli.run_scenario(mock_args)
        mock_engine.assert_called_once()


# --- run_evaluate ---
@pytest.mark.asyncio
async def test_run_evaluate_success(mock_args, tmp_path, monkeypatch):
    # Set proper string paths
    monkeypatch.chdir(tmp_path)
    mock_args.path = str(tmp_path)
    mock_args.run_log_dir = str(tmp_path / "logs")
    mock_args.attempts = 2
    
    (tmp_path / "t1.json").write_text("{}", encoding="utf-8")
    
    with patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "t1", "title": "T1"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval, \
         patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0):
        with patch("builtins.open", MagicMock()) as mock_open:
            # Avoid issue with nested mocks by just using a single mock
            pass
             
            mock_eval.return_value = [
                {"metrics": [{"success": True}], "conversation_history": [{"role": "agent", "content": {"summary": "done"}}]}
            ]
            
            await cli.run_evaluate(mock_args)


# --- handle_auto_translate ---
@pytest.mark.asyncio
async def test_handle_auto_translate_success(mock_args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "in.txt").write_text("text")
    mock_args.input = "in.txt"
    with patch("eval_runner.auto_translate.extract_text", return_value="test text"), \
         patch("eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock) as mock_trans, \
         patch("eval_runner.auto_translate.save_scenario") as mock_save:
         
        mock_trans.return_value = {"scenario_id": "auto"}
        await cli.handle_auto_translate(mock_args)
        mock_save.assert_called_once()

# --- handle_calibrate ---
def test_handle_calibrate_success(mock_args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "t1.jsonl").write_text(json.dumps({"event": "evaluation", "metric": "m1", "value": 0.5}))
    mock_args.path = str(trace_dir)
    
    with patch("eval_runner.cli.load_events", return_value=[{"event": "evaluation", "metric": "m1", "value": 0.5}]):
        cli.handle_calibrate(mock_args)

def test_handle_calibrate_plot(mock_args, tmp_path, monkeypatch):
    mock_args.plot = True
    monkeypatch.chdir(tmp_path)
    trace_file = tmp_path / "t1.jsonl"
    trace_file.write_text(json.dumps({"event": "evaluation", "metric": "xyz", "value": 1}))
    mock_args.path = str(trace_file)
    
    mock_plt = MagicMock()
    with patch("eval_runner.cli.load_events", return_value=[{"event": "evaluation", "metric": "xyz", "value": 1}]), \
         patch.dict("sys.modules", {"matplotlib": MagicMock(), "matplotlib.pyplot": mock_plt}):
        cli.handle_calibrate(mock_args)

