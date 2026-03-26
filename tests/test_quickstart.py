import pytest
import json
import asyncio
import subprocess
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from eval_runner.quickstart import run_quickstart, start_sample_agent


@patch("subprocess.Popen")
def test_start_sample_agent(mock_popen, tmp_path, monkeypatch):
    """Test starting the sample agent process."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sample_agent").mkdir()
    (tmp_path / "sample_agent" / "agent_app.py").write_text("print('hello')")

    with patch("time.sleep"):
        proc = start_sample_agent()

    assert proc == mock_process
    mock_popen.assert_called_once()


@pytest.mark.asyncio
async def test_run_quickstart_flow(tmp_path, monkeypatch):
    """Test the full quickstart execution flow."""
    monkeypatch.chdir(tmp_path)
    # Mock the sample agent process
    mock_process = MagicMock()

    # Create real scenario file at the hardcoded path expected by quickstart.py
    scen_path = "industries/telecom/scenarios/technical_support/13814_home_internet_slow_speed.json"
    scen_file = tmp_path / scen_path
    scen_file.parent.mkdir(parents=True, exist_ok=True)
    
    mock_scenario = {"scenario_id": "test", "name": "Test Scenario"}
    scen_file.write_text(json.dumps(mock_scenario), encoding="utf-8")

    # Mock results
    mock_results = [{"task_id": "1", "status": "success"}]

    with patch("eval_runner.quickstart.start_sample_agent", return_value=mock_process), \
         patch("eval_runner.quickstart.engine.run_evaluation", return_value=mock_results), \
         patch("eval_runner.quickstart.reporter.generate_report") as mock_gen_report, \
         patch("eval_runner.quickstart.reporter.generate_html_report", return_value="report.html") as mock_gen_html, \
         patch("builtins.print"):

        await run_quickstart()

        # Verify termination
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()

        # Verify reporting
        mock_gen_report.assert_called_once_with(mock_scenario, mock_results, export_trajectory=True)
        mock_gen_html.assert_called_once_with(mock_scenario, mock_results)
