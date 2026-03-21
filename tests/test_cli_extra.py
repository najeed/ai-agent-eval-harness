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
def test_handle_aes_validate_dir(mock_args, tmp_path):
    mock_args.path = str(tmp_path)
    with patch("eval_runner.cli.Path") as mock_path, \
         patch("builtins.open"), \
         patch("json.loads", return_value={"type": "object"}), \
         patch("yaml.safe_load", return_value={}), \
         patch("jsonschema.validate"):
         
        instance = mock_path.return_value
        instance.is_dir.return_value = True
        mock_file = MagicMock()
        mock_file.name = "scenario.aes.yaml"
        instance.glob.return_value = [mock_file]
        cli.handle_aes_validate(mock_args)


# --- handle_replay ---
def test_handle_replay_success(mock_args):
    mock_args.path = "some_trace.jsonl"
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events") as mock_load:
         
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
async def test_run_scenario_success(mock_args):
    mock_args.scenario = "scen.json"
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_engine:
         
        mock_engine.return_value = []
        await cli.run_scenario(mock_args)
        mock_engine.assert_called_once()


# --- run_evaluate ---
@pytest.mark.asyncio
async def test_run_evaluate_success(mock_args, tmp_path):
    # Set proper string paths
    mock_args.path = str(tmp_path)
    mock_args.run_log_dir = str(tmp_path / "logs")
    mock_args.attempts = 2
    
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.loader.load_scenario", return_value=[{"scenario_id": "t1", "title": "T1"}]), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval, \
         patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0), \
         patch("builtins.open"):
         
        mock_eval.return_value = [
            {"metrics": [{"success": True}], "conversation_history": [{"role": "agent", "content": {"summary": "done"}}]}
        ]
        await cli.run_evaluate(mock_args)


# --- handle_auto_translate ---
@pytest.mark.asyncio
async def test_handle_auto_translate_success(mock_args):
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.auto_translate.extract_text", return_value="test text"), \
         patch("eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock) as mock_trans, \
         patch("eval_runner.auto_translate.save_scenario") as mock_save:
         
        mock_trans.return_value = {"scenario_id": "auto"}
        await cli.handle_auto_translate(mock_args)
        mock_save.assert_called_once()

# --- classify_scenario ---
import sys

def test_classify_scenario_basic():
    scenario = {"title": "Help", "description": "Need account reset"}
    
    mock_st_class = MagicMock()
    mock_st_instance = MagicMock()
    mock_st_class.return_value = mock_st_instance
    mock_st_instance.encode.return_value = [0.1]
    
    mock_util = MagicMock()
    mock_util.cos_sim.return_value = [[1.0, 0, 0, 0, 0, 0]]
    
    mock_torch = MagicMock()
    mock_am_instance = MagicMock()
    mock_am_instance.item.return_value = 0
    mock_torch.argmax.return_value = mock_am_instance
    
    with patch.dict("sys.modules", {
        "sentence_transformers": MagicMock(SentenceTransformer=mock_st_class, util=mock_util),
        "torch": mock_torch
    }):
        res = cli.classify_scenario(scenario)
        assert res["industry"] == "finance"

def test_classify_scenario_empty():
    res = cli.classify_scenario({})
    assert res["industry"] == "generic"


# --- handle_calibrate ---
def test_handle_calibrate_success(mock_args):
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.Path.iterdir") as mock_iter, \
         patch("builtins.open") as mock_open:
        
        # mock read lines of a trace log
        mock_open.return_value.__enter__.return_value.readlines.return_value = [
            json.dumps({"event": "evaluation", "metric": "test_metric", "value": 0.5}),
            json.dumps({"event": "evaluation", "metric": "test_metric", "value": 1.0})
        ]
        
        # mock a file item
        f = MagicMock()
        f.suffix = ".jsonl"
        mock_iter.return_value = [f]

        cli.handle_calibrate(mock_args)

def test_handle_calibrate_plot(mock_args):
    mock_args.plot = True
    
    mock_plt = MagicMock()
    
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.Path.iterdir") as mock_iter, \
         patch("builtins.open") as mock_open, \
         patch.dict("sys.modules", {"matplotlib": MagicMock(), "matplotlib.pyplot": mock_plt}):
        
        mock_open.return_value.__enter__.return_value.readlines.return_value = [
            json.dumps({"event": "evaluation", "metric": "xyz", "value": 1})
        ]
        
        f = MagicMock()
        f.suffix = ".jsonl"
        mock_iter.return_value = [f]

        cli.handle_calibrate(mock_args)

