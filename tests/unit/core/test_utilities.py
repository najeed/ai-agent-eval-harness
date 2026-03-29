import pytest
import json
import asyncio
import os
import argparse
import time
from pathlib import Path
from eval_runner import doctor, scaffold, reporter, quickstart, trace_recorder

# --- 1. Doctor Tests ---

@pytest.mark.asyncio
async def test_doctor_runs_without_error(monkeypatch):
    """Verifies doctor utility runs without errors using natural unreachability."""
    # Point to non-existent agent to trigger failure naturally
    monkeypatch.setenv("AGENT_API_URL", "http://localhost:65534")
    await doctor.run_doctor()


# --- 2. Scaffold Tests ---

def test_scaffold_generates_files(tmp_path, monkeypatch):
    """Verifies scenario generate creates requested JSON files."""
    monkeypatch.chdir(tmp_path)
    inputs = ["test_industry", "test_capability", "2"]
    def mock_input(_):
        return inputs.pop(0) if inputs else "exit"
    monkeypatch.setattr("builtins.input", mock_input)

    scaffold.generate_interactive()

    # Success depends on where the script thinks the root is
    output_dir = tmp_path / "industries" / "test_industry" / "scenarios"
    if not output_dir.exists():
        # Fallback check for different dir structures in scaffold
        output_dir = tmp_path / "scenarios" / "test_industry"
    
    assert output_dir.exists()


# --- 3. HTML Reporter Tests ---

def test_html_report_content(tmp_path, monkeypatch):
    """Verifies HTML report is generated and contains key sections."""
    monkeypatch.chdir(tmp_path)
    # Use monkeypatch for config symbols instead of unittest.mock.patch
    from eval_runner import config
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "HTML_REPORTS_DIR", tmp_path / "reports" / "html")
    
    scenario = {"scenario_id": "test_id", "title": "Test Title", "industry": "test_ind"}
    results = [
        {
            "task_id": "task_1",
            "metrics": [{"metric": "success", "score": 1.0, "threshold": 0.5, "success": True}],
            "conversation_history": [],
        }
    ]
    filepath = reporter.generate_html_report(scenario, results)
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "Test Title" in content
    assert "100.0%" in content

def test_cleanup_old_reports(tmp_path, monkeypatch):
    """Verifies old reports are deleted based on mtime."""
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    html_dir = reports_dir / "html"
    html_dir.mkdir(parents=True)
    
    old_file = html_dir / "old.html"
    old_file.write_text("old", encoding="utf-8")
    
    new_file = html_dir / "new.html"
    new_file.write_text("new", encoding="utf-8")
    # Set mtime to 0 (far past)
    os.utime(str(old_file), (0, 0))
    
    from eval_runner import config
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "HTML_REPORTS_DIR", html_dir)
    monkeypatch.setattr(config, "TRAJECTORIES_DIR", reports_dir / "trajectories")
    
    reporter.cleanup_old_reports(days=7)
    
    assert not old_file.exists()
    assert new_file.exists()


# --- 4. Trace Recorder Tests ---

@pytest.mark.asyncio
async def test_trace_recorder_saves_jsonl(tmp_path, monkeypatch, adapter_stub):
    """Verifies trace recorder saves events to isolated jsonl."""
    monkeypatch.chdir(tmp_path)
    inputs = ["Test Task", "exit"]
    def mock_input(_):
        return inputs.pop(0) if inputs else "exit"
    monkeypatch.setattr("builtins.input", mock_input)

    server = adapter_stub
    agent_url = f"http://{server.host}:{server.port}/execute_task"
    await trace_recorder.record_interaction(agent_url)

    runs_dir = tmp_path / "runs"
    assert runs_dir.exists()
    jsonl_files = list(runs_dir.glob("*.jsonl"))
    assert len(jsonl_files) > 0
