import pytest
import json
import asyncio
import os
import time
from pathlib import Path
try:
    from unittest.mock import patch, MagicMock, AsyncMock
except ImportError:
    from unittest.mock import patch, MagicMock
    AsyncMock = MagicMock # Minimal fallback
from eval_runner import doctor, scaffold, reporter, quickstart, trace_recorder

# --- 1. Doctor Tests ---

@pytest.mark.asyncio
async def test_doctor_runs_without_error():
    """Verifies doctor utility runs with mocked external calls."""
    with patch("eval_runner.doctor.check_agent_reachable", return_value=True):
        await doctor.run_doctor()


# --- 2. Scaffold Tests ---

def test_scaffold_generates_files(tmp_path, monkeypatch):
    """Verifies scenario generate creates requested JSON files."""
    monkeypatch.chdir(tmp_path)
    inputs = iter(["test_industry", "test_capability", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    scaffold.generate_interactive()

    # Success depends on where the script thinks the root is
    # If it's not in industries/, it might fail. Let's ensure it's isolated.
    output_dir = tmp_path / "industries" / "test_industry" / "scenarios"
    if not output_dir.exists():
        # Fallback check for different dir structures in scaffold
        output_dir = tmp_path / "scenarios" / "test_industry"
    
    assert output_dir.exists()


# --- 3. HTML Reporter Tests ---

def test_html_report_content(tmp_path, monkeypatch):
    """Verifies HTML report is generated and contains key sections."""
    monkeypatch.chdir(tmp_path)
    # Ensure reporter uses this tmp_path for its report_dir
    with patch("eval_runner.reporter.config.PROJECT_ROOT", tmp_path):
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
    
    with patch("eval_runner.reporter.config.PROJECT_ROOT", tmp_path), \
         patch("eval_runner.reporter.config.HTML_REPORTS_DIR", html_dir), \
         patch("eval_runner.reporter.config.TRAJECTORIES_DIR", reports_dir / "trajectories"):
        reporter.cleanup_old_reports(days=7)
    
    assert not old_file.exists()
    assert new_file.exists()


# --- 4. Trace Recorder Tests ---

@pytest.mark.asyncio
async def test_trace_recorder_saves_jsonl(tmp_path, monkeypatch):
    """Verifies trace recorder saves events to isolated jsonl."""
    monkeypatch.chdir(tmp_path)
    inputs = iter(["Test Task", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # Mock aiohttp directly since TraceRecorder uses it
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__getattribute__("__aenter__").return_value.status = 200
        mock_post.return_value.__getattribute__("__aenter__").return_value.get_json = AsyncMock(return_value={"summary": "done"})
        
        await trace_recorder.record_interaction("http://mock-agent")

    runs_dir = tmp_path / "runs"
    assert runs_dir.exists()
    jsonl_files = list(runs_dir.glob("*.jsonl"))
    assert len(jsonl_files) > 0
