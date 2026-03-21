import pytest
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner.exporter import HFExporter

def test_exporter_git_fail(tmp_path):
    # Mock subprocess to fail
    with patch("subprocess.check_output", side_effect=Exception("no git")):
        # Just check the commit resolution
        export_path = tmp_path / "out.json"
        trace_path = tmp_path / "run.jsonl"
        with open(trace_path, "w") as f:
            f.write(json.dumps({"event": "run_start"}) + "\n")
            
        HFExporter.export(str(trace_path), str(export_path))
        with open(export_path, "r") as f:
            data = json.load(f)
            assert data[0]["meta"]["commit"] == "unknown"

def test_exporter_file_not_found(tmp_path, capsys):
    trace_path = tmp_path / "ghost.jsonl"
    HFExporter.export(str(trace_path), "out.json")
    out, _ = capsys.readouterr()
    assert "not found" in out

def test_exporter_load_events_fail(tmp_path, capsys):
    trace_path = tmp_path / "run.jsonl"
    with open(trace_path, "w") as f:
        f.write("corrupt\n")
    
    with patch("eval_runner.exporter.load_events", side_effect=Exception("Load fail")):
        HFExporter.export(str(trace_path), "out.json")
        out, _ = capsys.readouterr()
        assert "Failed to load events" in out

def test_push_to_hf_file_not_found(capsys):
    HFExporter.push_to_hf("ghost.json", "repo_id")
    out, _ = capsys.readouterr()
    assert "not found" in out

def test_push_to_hf_import_error(tmp_path, capsys):
    dataset_path = tmp_path / "data.json"
    dataset_path.touch()
    with patch.dict("sys.modules", {"huggingface_hub": None}):
        HFExporter.push_to_hf(str(dataset_path), "repo_id")
        out, _ = capsys.readouterr()
        assert "SDK not found" in out

def test_push_to_hf_auth_hint(tmp_path, capsys):
    dataset_path = tmp_path / "data.json"
    dataset_path.touch()
    
    # Mock HfApi to raise unauthorized
    mock_api = MagicMock()
    mock_api.upload_file.side_effect = Exception("Unauthorized: Please login")
    
    with patch("huggingface_hub.HfApi", return_value=mock_api):
        HFExporter.push_to_hf(str(dataset_path), "repo_id")
        out, _ = capsys.readouterr()
        assert "Please run 'huggingface-cli login'" in out
