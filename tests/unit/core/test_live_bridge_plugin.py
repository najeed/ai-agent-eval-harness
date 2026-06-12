"""
test_live_bridge_plugin.py

Full coverage for eval_runner/live_bridge_plugin.py.
Tests cover is_safe_url, RemoteBridgePlugin initialization, heartbeat
check branches, _post_event dispatch, and all event hook methods.
"""

from unittest.mock import MagicMock, patch

from eval_runner.live_bridge_plugin import RemoteBridgePlugin, is_safe_url

# ---------------------------------------------------------------------------
# is_safe_url
# ---------------------------------------------------------------------------


class TestIsSafeUrl:
    def test_public_url_is_safe(self):
        # Mock socket so we don't do real DNS
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            assert is_safe_url("https://example.com/api") is True

    def test_loopback_is_blocked(self):
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            assert is_safe_url("http://localhost/api") is False

    def test_link_local_cloud_metadata_is_blocked(self):
        with patch("socket.gethostbyname", return_value="169.254.169.254"):
            assert is_safe_url("http://169.254.169.254/latest/meta-data") is False

    def test_unspecified_address_is_blocked(self):
        with patch("socket.gethostbyname", return_value="0.0.0.0"):  # nosec B104
            assert is_safe_url("http://0.0.0.0/api") is False  # nosec B104

    def test_ipv6_loopback_blocked(self):
        with patch("socket.gethostbyname", return_value="::1"):
            assert is_safe_url("http://[::1]/api") is False

    def test_missing_scheme_returns_false(self):
        assert is_safe_url("example.com/path") is False

    def test_missing_netloc_returns_false(self):
        assert is_safe_url("file:///local/path") is False

    def test_empty_hostname_returns_false(self):
        """URL with netloc present but parsed hostname empty (e.g. http://:8080/) hits line 21."""
        # urlparse("http://:8080/") → scheme="http", netloc=":8080", hostname="" (falsy)
        # This passes the scheme/netloc check but hostname is empty → line 21 return False
        result = is_safe_url("http://:8080/api")
        assert result is False

    def test_dns_error_returns_false(self):
        with patch("socket.gethostbyname", side_effect=OSError("DNS failure")):
            assert is_safe_url("http://bad-host.internal/api") is False

    def test_empty_string_returns_false(self):
        assert is_safe_url("") is False


# ---------------------------------------------------------------------------
# RemoteBridgePlugin.__init__
# ---------------------------------------------------------------------------


class TestRemoteBridgePluginInit:
    def test_default_endpoint_is_active_unknown(self):
        """Default localhost endpoint bypasses safety check — active stays None."""
        plugin = RemoteBridgePlugin()
        assert plugin.endpoint == "http://localhost:5000/api/debugger/state"
        assert plugin.active is None

    def test_env_override_default_endpoint_is_active_unknown(self, monkeypatch):
        """If DEBUGGER_ENDPOINT is the canonical default, active stays None."""
        monkeypatch.setenv("DEBUGGER_ENDPOINT", "http://localhost:5000/api/debugger/state")
        plugin = RemoteBridgePlugin()
        assert plugin.active is None

    def test_unsafe_custom_endpoint_disables_plugin(self, monkeypatch):
        """A non-default endpoint that fails is_safe_url sets active=False."""
        monkeypatch.setenv("DEBUGGER_ENDPOINT", "http://169.254.169.254/evil")
        with patch("socket.gethostbyname", return_value="169.254.169.254"):
            plugin = RemoteBridgePlugin()
        assert plugin.active is False

    def test_safe_custom_endpoint_leaves_active_unknown(self, monkeypatch, capsys):
        """A non-default, safe endpoint leaves active=None (to be resolved on first use)."""
        monkeypatch.setenv("DEBUGGER_ENDPOINT", "http://debugger.example.com/api/state")
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            plugin = RemoteBridgePlugin()
        assert plugin.active is None


# ---------------------------------------------------------------------------
# _check_console_active
# ---------------------------------------------------------------------------


class TestCheckConsoleActive:
    def _make_plugin(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = None
        return plugin

    def test_cached_active_true_returns_immediately(self):
        plugin = self._make_plugin()
        plugin.active = True
        assert plugin._check_console_active() is True

    def test_cached_active_false_returns_immediately(self):
        plugin = self._make_plugin()
        plugin.active = False
        assert plugin._check_console_active() is False

    def test_local_subscriber_detected_disables_bridge(self):
        """If 'debugger' key is in EventEmitter keyed subscribers, skip HTTP."""
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {"debugger": object()}

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            result = plugin._check_console_active()

        assert result is False
        assert plugin.active is False

    def test_heartbeat_200_activates(self):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                with patch("requests.get", return_value=mock_response):
                    result = plugin._check_console_active()

        assert result is True
        assert plugin.active is True

    def test_heartbeat_401_disables(self, capsys):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                with patch("requests.get", return_value=mock_response):
                    result = plugin._check_console_active()

        assert result is False
        assert plugin.active is False

    def test_heartbeat_network_error_disables(self):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                with patch("requests.get", side_effect=ConnectionError("Refused")):
                    result = plugin._check_console_active()

        assert result is False
        assert plugin.active is False

    def test_heartbeat_with_api_key_header_sent(self):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.DASHBOARD_API_KEY", "secret-key"):
                with patch("requests.get", return_value=mock_response) as mock_get:
                    plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "secret-key"


# ---------------------------------------------------------------------------
# _post_event
# ---------------------------------------------------------------------------


class TestPostEvent:
    def _make_active_plugin(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = True
        return plugin

    def test_active_false_skips_post(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = False
        with patch("requests.post") as mock_post:
            plugin._post_event("TURN_START", {})
        mock_post.assert_not_called()

    def test_active_none_triggers_heartbeat_and_skips_if_inactive(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = None

        with patch.object(plugin, "_check_console_active", return_value=False):
            with patch("requests.post") as mock_post:
                plugin._post_event("TURN_START", {})
        mock_post.assert_not_called()

    def test_post_success(self):
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", return_value=mock_response):
                plugin._post_event("TEST_EVENT", {"key": "value"})
        assert plugin.active is True

    def test_post_401_disables_plugin(self, capsys):
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 401
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", return_value=mock_response):
                plugin._post_event("TEST_EVENT", {})
        assert plugin.active is False

    def test_post_network_error_disables_plugin(self):
        plugin = self._make_active_plugin()
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", side_effect=ConnectionError("Timeout")):
                plugin._post_event("TEST_EVENT", {})
        assert plugin.active is False

    def test_post_with_api_key_header(self):
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("eval_runner.config.DASHBOARD_API_KEY", "my-api-key"):
            with patch("requests.post", return_value=mock_response) as mock_post:
                plugin._post_event("TEST_EVENT", {})
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "my-api-key"


# ---------------------------------------------------------------------------
# Event hook methods
# ---------------------------------------------------------------------------


class TestEventHooks:
    def _make_active_plugin(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = True
        return plugin

    def test_before_evaluation(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()
        ctx.identifier = "eval-01"
        ctx.metadata = {"scenario": "test"}

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.before_evaluation(ctx)
        mock_post.assert_called_once()
        args = mock_post.call_args[0]
        assert args[1]["id"] == "eval-01"

    def test_on_agent_turn_start(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()
        ctx.turn_number = 3
        ctx.agent_name = "MyAgent"

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.on_agent_turn_start(ctx)
        args = mock_post.call_args[0]
        assert args[1]["turn_idx"] == 3
        assert args[1]["agent_name"] == "MyAgent"

    def test_on_agent_turn_start_no_agent_name_attr(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock(spec=["turn_number"])
        ctx.turn_number = 1

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.on_agent_turn_start(ctx)
        args = mock_post.call_args[0]
        assert args[1]["agent_name"] == "agent"

    def test_on_turn_end(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()
        ctx.turn_number = 2
        ctx.turn_metrics = {"score": 0.9}

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.on_turn_end(ctx)
        args = mock_post.call_args[0]
        assert args[1]["metrics"] == {"score": 0.9}

    def test_on_turn_end_no_metrics_attr(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock(spec=["turn_number"])
        ctx.turn_number = 1

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.on_turn_end(ctx)
        args = mock_post.call_args[0]
        assert args[1]["metrics"] == {}

    def test_on_tool_request(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()

        with patch.object(plugin, "_post_event") as mock_post:
            result = plugin.on_tool_request(ctx, "search", arguments={"q": "test"})
        assert result is True
        args = mock_post.call_args[0]
        assert args[1]["tool"] == "search"
        assert args[1]["arguments"] == {"q": "test"}

    def test_on_tool_result(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.on_tool_result(ctx, "search", result="42")
        args = mock_post.call_args[0]
        assert args[1]["tool"] == "search"
        assert args[1]["result"] == "42"

    def test_after_evaluation(self):
        plugin = self._make_active_plugin()
        ctx = MagicMock()
        results = [1, 2, 3]

        with patch.object(plugin, "_post_event") as mock_post:
            plugin.after_evaluation(ctx, results)
        args = mock_post.call_args[0]
        assert args[1]["results_count"] == 3
        assert args[1]["status"] == "COMPLETED"
