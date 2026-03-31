import pytest
from unittest.mock import patch, MagicMock
from eval_runner.live_bridge_plugin import RemoteBridgePlugin
from eval_runner.events import CoreEvents


class MockContext:
    def __init__(self):
        self.scenario_id = "test_scen"
        self.metadata = {"difficulty": 1}
        self.turn_number = 1
        self.agent_name = "test_agent"
        self.turn_metrics = {"accuracy": 1.0}


@pytest.fixture
def plugin():
    with patch("requests.get") as mock_get, \
         patch("eval_runner.live_bridge_plugin.is_safe_url", return_value=True):
        mock_get.return_value.status_code = 200
        p = RemoteBridgePlugin(endpoint="http://mock-console/api/debugger/state")
        # In lazy mode, we don't call check yet, but for test consistency 
        # we can trigger it in the fixture or handle it in tests.
        return p


def test_plugin_check_console_active(plugin):
    """Verify that plugin correctly identifies if console is active."""
    # Initially unknown in lazy mode
    assert plugin.active is None

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        plugin._check_console_active()
        assert plugin.active is True

    with patch("requests.get") as mock_get:
        # Reset and force failure
        plugin.active = None
        mock_get.side_effect = Exception("Down")
        plugin._check_console_active()
        assert plugin.active is False


def test_plugin_posts_events(plugin):
    """Verify that plugin posts events to the endpoint when active."""
    context = MockContext()

    with patch("requests.get") as mock_get, \
         patch("requests.post") as mock_post:
        mock_get.return_value.status_code = 200
        plugin.before_evaluation(context)

        # Verify call
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["event"] == CoreEvents.RUN_START
        assert kwargs["json"]["data"]["scenario"] == "test_scen"


def test_plugin_disables_on_failure(plugin):
    """Verify that plugin disables itself if a POST fails."""
    context = MockContext()

    # Ensure it's active first
    plugin.active = True

    with patch("requests.post") as mock_post:
        mock_post.side_effect = Exception("Console died")
        plugin.on_agent_turn_start(context)

        assert plugin.active is False

        # Subsequent calls should not trigger POST
        plugin.on_turn_end(context)
        assert mock_post.call_count == 1
