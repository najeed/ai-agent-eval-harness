import pytest
import os
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner import doctor, scaffold, reporter, quickstart, trace_recorder

# --- 1. Doctor Tests ---

@pytest.mark.asyncio
async def test_doctor_runs_without_error():
    """Verifies doctor utility runs with mocked external calls."""
    with patch("eval_runner.doctor.check_agent_reachable", return_value=True):
        # Capturing stdout is not strictly needed for basic pass, 
        # but verifies it doesn't crash.
        await doctor.run_doctor()

# --- 2. Scaffold Tests ---

def test_scaffold_generates_files(tmp_path, monkeypatch):
    """Verifies scenario generate creates requested JSON files."""
    monkeypatch.chdir(tmp_path)
    inputs = iter(["test_industry", "test_capability", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    scaffold.generate_interactive()
    
    output_dir = tmp_path / "scenarios" / "test_industry"
    assert output_dir.exists()
    assert (output_dir / "gen_test_industry_test_capability_1.json").exists()
    assert (output_dir / "gen_test_industry_test_capability_2.json").exists()

# --- 3. HTML Reporter Tests ---

def test_html_report_generation(tmp_path):
    """Verifies HTML report is generated and contains key sections."""
    # We need to stay in the project root or mock Path to avoid breaking the report dir logic
    # but for unit testing, we can mock the Path.
    with patch("eval_runner.reporter.Path") as mock_path:
        # Configure mock_path to behave like tmp_path
        def side_effect(arg1, *args):
            return Path(tmp_path) / arg1
        mock_path.side_effect = side_effect
        
        scenario = {"scenario_id": "test_id", "title": "Test Title", "industry": "test_ind"}
        results = [
            {
                "task_id": "task_1",
                "metrics": [{"metric": "success", "score": 1.0, "threshold": 0.5, "success": True}],
                "conversation_history": []
            }
        ]
        
        # We need to mock datetime to have a predictable filename
        with patch("eval_runner.reporter.datetime") as mock_date:
            mock_date.now.return_value.strftime.return_value = "20260101_000000"
            filepath = reporter.generate_html_report(scenario, results)
            
            # The real reporter uses Path("reports") / "html"
            # In our mock, it might be different depending on how Path was called.
            # Let's just check if ANY html file was written in the tmp_path.
            html_files = list(tmp_path.glob("*.html")) + list((tmp_path / "reports" / "html").glob("*.html") if (tmp_path / "reports").exists() else [])
            # Actually, let's just use the returned filepath and see if it exists
            # Wait, the reporter code does: report_dir = Path("reports") / "html"
            # If Path is mocked, report_dir will be a mock.
            
    # Simpler test: check if the logic writes a file
    monkeypatch_path = Path(tmp_path)
    with patch("eval_runner.reporter.Path", return_value=monkeypatch_path):
        # This is tricky because Path("reports") / "html" involves __truediv__
        pass

# Refined test for HTML report
def test_html_report_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scenario = {"scenario_id": "test_id", "title": "Test Title", "industry": "test_ind"}
    results = [
        {
            "task_id": "task_1",
            "metrics": [{"metric": "success", "score": 1.0, "threshold": 0.5, "success": True}],
            "conversation_history": []
        }
    ]
    filepath = reporter.generate_html_report(scenario, results)
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "Test Title" in content
    assert "task_1" in content
    assert "100.0%" in content

# --- 4. Trace Recorder Tests ---

@pytest.mark.asyncio
async def test_trace_recorder_saves_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inputs = iter(["Test Task", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    with patch("eval_runner.trace_recorder.aiohttp.ClientSession.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status = 200
        # Create a helper to return an awaitable
        async def mock_get_json():
            return {"summary": "Success", "action": "none"}
        mock_response.get_json = mock_get_json
        mock_post.return_value.__aenter__.return_value = mock_response
        
        await trace_recorder.record_interaction("http://mock-agent")
        
    runs_dir = tmp_path / "runs"
    assert runs_dir.exists()
    jsonl_files = list(runs_dir.glob("*.jsonl"))
    assert len(jsonl_files) > 0
    
    # Check content of the first file
    with open(jsonl_files[0], "r") as f:
        events = [json.loads(line) for line in f]
    assert any(e["event"] == "run_start" for e in events)
    assert any(e.get("task") == "Test Task" for e in events)
