import json
import pytest
from pathlib import Path
from eval_runner.trace_utils import load_events

def test_load_events_jsonl(tmp_path):
    """Verify loading from a standard JSONL file."""
    events = [
        {"event": "run_start", "id": 1},
        {"event": "task_start", "id": 2}
    ]
    trace_file = tmp_path / "test.jsonl"
    with open(trace_file, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
            
    loaded = load_events(trace_file)
    assert len(loaded) == 2
    assert loaded[0]["event"] == "run_start"

def test_load_events_json_array(tmp_path):
    """Verify loading from a standard JSON array file (exported trace)."""
    events = [
        {"event": "run_start", "id": 1},
        {"event": "task_start", "id": 2}
    ]
    trace_file = tmp_path / "test.json"
    with open(trace_file, "w") as f:
        json.dump(events, f, indent=2)
        
    loaded = load_events(trace_file)
    assert len(loaded) == 2
    assert loaded[0]["event"] == "run_start"

def test_load_events_empty_file(tmp_path):
    """Verify handling of empty files."""
    trace_file = tmp_path / "empty.jsonl"
    trace_file.write_text("")
    
    loaded = load_events(trace_file)
    assert loaded == []

def test_load_events_malformed_jsonl(tmp_path):
    """Verify that malformed lines in JSONL are skipped."""
    trace_file = tmp_path / "malformed.jsonl"
    trace_file.write_text('{"event": "start"}\n{invalid_json}\n{"event": "end"}')
    
    loaded = load_events(trace_file)
    assert len(loaded) == 2
    assert loaded[0]["event"] == "start"
    assert loaded[1]["event"] == "end"

def test_load_events_not_found():
    """Verify that FileNotFoundError is raised for missing files."""
    with pytest.raises(FileNotFoundError):
        load_events("non_existent_file.jsonl")
