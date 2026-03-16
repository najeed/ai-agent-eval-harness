import pytest
import asyncio
import subprocess
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from eval_runner.quickstart import run_quickstart, start_sample_agent

@patch("subprocess.Popen")
def test_start_sample_agent(mock_popen):
    """Test starting the sample agent process."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    
    # Path mocking isn't strictly necessary if it exists, but good for isolation
    with patch("eval_runner.quickstart.Path.exists", return_value=True), \
         patch("time.sleep"):
        proc = start_sample_agent()
        
    assert proc == mock_process
    mock_popen.assert_called_once()

@pytest.mark.asyncio
async def test_run_quickstart_flow():
    """Test the full quickstart execution flow."""
    # Mock the sample agent process
    mock_process = MagicMock()
    
    # Mock scenario data
    mock_scenario = {"scenario_id": "test", "name": "Test Scenario"}
    
    # Mock engine.run_evaluation
    mock_results = [{"task_id": "1", "status": "success"}]
    
    with patch("eval_runner.quickstart.start_sample_agent", return_value=mock_process), \
         patch("eval_runner.quickstart.Path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("json.load", return_value=mock_scenario), \
         patch("eval_runner.engine.run_evaluation", AsyncMock(return_value=mock_results)), \
         patch("eval_runner.reporter.generate_report") as mock_gen_report, \
         patch("eval_runner.reporter.generate_html_report", return_value="report.html") as mock_gen_html, \
         patch("builtins.print"):
        
        await run_quickstart()
        
        # Verify termination
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()
        
        # Verify reporting
        mock_gen_report.assert_called_once_with(mock_scenario, mock_results, export_trajectory=True)
        mock_gen_html.assert_called_once_with(mock_scenario, mock_results)
