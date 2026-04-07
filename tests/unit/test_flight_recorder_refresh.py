import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.events import Event, CoreEvents

def test_flight_recorder_refresh_on_run_start():
    """Test that FlightRecorderPlugin refreshes its config when a RUN_START event occurs."""
    # Setup initial state - Mocking config to avoid dependencies
    with patch("eval_runner.config.RUN_LOG_DIR", "default_dir"):
        with patch("os.getenv") as mock_getenv:
            def getenv_initial(key, default=None):
                if key == "RUN_LOG_DIR": return "initial_dir"
                if key == "RUN_LOG_ROTATE_COUNT": return "0"
                return default or "true"
            mock_getenv.side_effect = getenv_initial
            plugin = FlightRecorderPlugin()
            # Note: FlightRecorderPlugin.__init__ calls subscribe, which we might want to avoid or mock
            # but for this test it's fine.
            
    assert str(plugin.log_dir) == "initial_dir"

    # Simulate environment change (e.g. set by a CLI handler)
    with patch("os.getenv") as mock_getenv:
        def getenv_side_effect(key, default=None):
            if key == "RUN_LOG_DIR":
                return "new_dir"
            if key == "RUN_LOG_PER_RUN":
                return "true"
            if key == "RUN_LOG_MASTER":
                return "true"
            if key == "RUN_LOG_ROTATE_COUNT":
                return "0"
            return default
            
        mock_getenv.side_effect = getenv_side_effect
        
        # Create a RUN_START event
        event = Event(name=CoreEvents.RUN_START, data={"run_id": "test_run"})
        
        # We need to mock mkdir and open to avoid actual disk IO
        with patch.object(Path, "mkdir"):
            with patch("builtins.open", MagicMock()):
                plugin.handle_event(event)
            
        assert str(plugin.log_dir) == "new_dir"
        assert str(plugin.master_log_path) == str(Path("new_dir") / "run.jsonl")
        assert plugin.run_id == "test_run"
