from unittest.mock import MagicMock, patch

import pytest

from eval_runner.quickstart import run_quickstart, start_sample_agent


@pytest.mark.asyncio
async def test_start_sample_agent_not_found(capsys):
    """Verify that start_sample_agent handles missing agent file."""
    with patch("pathlib.Path.exists", return_value=False):
        result = start_sample_agent()
        assert result is None
        out, _ = capsys.readouterr()
        assert "Error: Sample agent not found" in out


@pytest.mark.asyncio
async def test_run_quickstart_no_agent(capsys):
    """Verify that run_quickstart exits if agent fails to start."""
    with patch("eval_runner.quickstart.start_sample_agent", return_value=None):
        await run_quickstart()
        out, _ = capsys.readouterr()
        assert "AgentV - Quickstart Demo" in out
        # Should return early without trying to load scenario


@pytest.mark.asyncio
async def test_run_quickstart_no_scenario(capsys):
    """Verify that run_quickstart handles missing scenario file."""
    mock_agent = MagicMock()
    with patch("eval_runner.quickstart.start_sample_agent", return_value=mock_agent):
        # Selective mock to only fail the specific scenario path check
        def selective_exists(self):
            if "13814_home_internet_slow_speed.json" in str(self):
                return False
            return True

        with patch("pathlib.Path.exists", autospec=True, side_effect=selective_exists):
            await run_quickstart()
            out, _ = capsys.readouterr()
            assert "Error: Quickstart scenario not found" in out
            assert "Shutting down sample agent" in out
            mock_agent.terminate.assert_called_once()
