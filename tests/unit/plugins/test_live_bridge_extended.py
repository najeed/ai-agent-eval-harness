import pytest
from unittest.mock import patch, MagicMock
from eval_runner.live_bridge_plugin import RemoteBridgePlugin
from eval_runner.events import CoreEvents

@pytest.fixture
def mock_config():
    with patch("eval_runner.config") as mock:
        mock.DASHBOARD_API_KEY = "test-key"
        yield mock

def test_bridge_heartbeat_success(mock_config):
    with patch("eval_runner.live_bridge_plugin.is_safe_url", return_value=True):
        plugin = RemoteBridgePlugin(endpoint="http://test.com/api")
    
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        assert plugin._check_console_active() is True
        assert plugin.active is True
        mock_get.assert_called_once()

def test_bridge_heartbeat_unauthorized(mock_config):
    plugin = RemoteBridgePlugin(endpoint="http://test.com/api")
    
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 401
        assert plugin._check_console_active() is False
        assert plugin.active is False

def test_bridge_post_event_unauthorized(mock_config):
    plugin = RemoteBridgePlugin(endpoint="http://test.com/api")
    plugin.active = True # Manually set to active
    
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 401
        plugin._post_event("test_event", {"some": "data"})
        
        # Should now be inactive
        assert plugin.active is False
        mock_post.assert_called_once()

def test_bridge_disables_on_exception(mock_config):
    plugin = RemoteBridgePlugin(endpoint="http://test.com/api")
    plugin.active = True
    
    with patch("requests.post") as mock_post:
        mock_post.side_effect = Exception("Network Down")
        plugin._post_event("test_event", {})
        
        assert plugin.active is False

def test_bridge_lifecycle_events(mock_config):
    plugin = RemoteBridgePlugin(endpoint="http://test.com/api")
    plugin.active = True
    
    mock_context = MagicMock()
    mock_context.scenario_id = "scen_1"
    mock_context.metadata = {"industry": "test"}
    mock_context.turn_number = 1
    
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        
        plugin.before_evaluation(mock_context)
        assert mock_post.call_count == 1
        
        plugin.on_agent_turn_start(mock_context)
        assert mock_post.call_count == 2
        
        plugin.on_turn_end(mock_context)
        assert mock_post.call_count == 3
