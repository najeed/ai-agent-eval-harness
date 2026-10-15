"""
test_live_bridge_plugin.py

Full coverage for eval_runner/live_bridge_plugin.py.
Tests cover is_safe_url, RemoteBridgePlugin initialization, heartbeat
check branches, _post_event dispatch, and all event hook methods.
"""

from unittest.mock import MagicMock, patch

import pytest

from eval_runner.live_bridge_plugin import RemoteBridgePlugin, is_safe_url


@pytest.fixture(autouse=True)
def isolate_auth_provider(monkeypatch):
    """Isolates the bridge tests from ambient environment or configured Enterprise backend."""
    from eval_runner.console.auth_manager import register_authorization_backend

    register_authorization_backend(None)
    monkeypatch.delenv("AGENTV_AUTHORIZATION_BACKEND_FACTORY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    with patch("eval_runner.config.SERVICE_API_KEY", ""):
        with patch(
            "eval_runner.console.auth_manager.has_configured_authorization_backend",
            return_value=False,
        ):
            yield
    register_authorization_backend(None)


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
        plugin._denied_diagnostic_emitted = False
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
        captured = capsys.readouterr()
        assert "Bridge access denied (Unauthenticated (401))" in captured.out

    def test_heartbeat_403_disables(self, capsys):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                with patch("requests.get", return_value=mock_response):
                    result = plugin._check_console_active()

        assert result is False
        assert plugin.active is False
        captured = capsys.readouterr()
        assert "Bridge access denied (Unauthorized (403))" in captured.out

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

    def test_heartbeat_with_api_key_header_sent(self, monkeypatch):
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch("eval_runner.config.SERVICE_API_KEY", ""):
                with patch("eval_runner.config.DASHBOARD_API_KEY", "secret-key"):
                    with patch("requests.get", return_value=mock_response) as mock_get:
                        plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "secret-key"

    def test_heartbeat_with_configured_backend_service_credential(self):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_provider = MagicMock()
        mock_provider.get_service_credential.return_value = "backend-service-key-99"

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.has_configured_authorization_backend",
                return_value=True,
            ):
                with patch(
                    "eval_runner.console.auth_manager.get_auth_provider", return_value=mock_provider
                ):
                    with patch("requests.get", return_value=mock_response) as mock_get:
                        plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "backend-service-key-99"

    def test_heartbeat_with_bearer_service_credential(self):
        plugin = self._make_plugin()

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_provider = MagicMock()
        mock_provider.get_service_credential.return_value = "Bearer jwt-token-xyz"

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.has_configured_authorization_backend",
                return_value=True,
            ):
                with patch(
                    "eval_runner.console.auth_manager.get_auth_provider", return_value=mock_provider
                ):
                    with patch("requests.get", return_value=mock_response) as mock_get:
                        plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer jwt-token-xyz"
        assert "X-AES-API-KEY" not in call_kwargs["headers"]

    def test_heartbeat_with_env_service_api_key(self, monkeypatch):
        plugin = self._make_plugin()
        monkeypatch.setenv("SERVICE_API_KEY", "env-service-secret")

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_provider = MagicMock()
        mock_provider.get_service_credential.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.get_auth_provider", return_value=mock_provider
            ):
                with patch("requests.get", return_value=mock_response) as mock_get:
                    plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "env-service-secret"

    def test_heartbeat_when_auth_provider_raises_exception(self, monkeypatch):
        plugin = self._make_plugin()
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.has_configured_authorization_backend",
                return_value=True,
            ):
                with patch(
                    "eval_runner.console.auth_manager.get_auth_provider",
                    side_effect=RuntimeError("Auth backend uninitialized"),
                ):
                    with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                        with patch("eval_runner.config.SERVICE_API_KEY", ""):
                            with patch("requests.get", return_value=mock_response) as mock_get:
                                plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert "X-AES-API-KEY" not in call_kwargs["headers"]
        assert "Authorization" not in call_kwargs["headers"]

    def test_heartbeat_with_env_dashboard_api_key_fallback(self, monkeypatch):
        plugin = self._make_plugin()
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.setenv("DASHBOARD_API_KEY", "env-dash-key-123")

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.has_configured_authorization_backend",
                return_value=False,
            ):
                with patch("eval_runner.config.DASHBOARD_API_KEY", None):
                    with patch("eval_runner.config.SERVICE_API_KEY", ""):
                        with patch("requests.get", return_value=mock_response) as mock_get:
                            plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["X-AES-API-KEY"] == "env-dash-key-123"

    def test_heartbeat_with_no_credentials(self, monkeypatch):
        plugin = self._make_plugin()
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)

        mock_emitter = MagicMock()
        mock_emitter._keyed_subscribers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("eval_runner.events.EventEmitter.get_global", return_value=mock_emitter):
            with patch(
                "eval_runner.console.auth_manager.has_configured_authorization_backend",
                return_value=False,
            ):
                with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
                    with patch("eval_runner.config.SERVICE_API_KEY", ""):
                        with patch("requests.get", return_value=mock_response) as mock_get:
                            plugin._check_console_active()

        call_kwargs = mock_get.call_args[1]
        assert "X-AES-API-KEY" not in call_kwargs["headers"]
        assert "Authorization" not in call_kwargs["headers"]


# ---------------------------------------------------------------------------
# _post_event
# ---------------------------------------------------------------------------


class TestPostEvent:
    def _make_active_plugin(self):
        plugin = RemoteBridgePlugin.__new__(RemoteBridgePlugin)
        plugin.endpoint = "http://localhost:5000/api/debugger/state"
        plugin.active = True
        plugin._denied_diagnostic_emitted = False
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
        captured = capsys.readouterr()
        assert "Bridge access denied (Unauthenticated (401))" in captured.out

    def test_post_403_disables_plugin(self, capsys):
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 403
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", return_value=mock_response):
                plugin._post_event("TEST_EVENT", {})
        assert plugin.active is False
        captured = capsys.readouterr()
        assert "Bridge access denied (Unauthorized (403))" in captured.out

    def test_rate_limited_diagnostic_emitted_only_once(self, capsys):
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 403
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", return_value=mock_response):
                plugin._post_event("TEST_EVENT_1", {})
                # Subsequent post event should be a no-op because active is False
                plugin._post_event("TEST_EVENT_2", {})
        captured = capsys.readouterr()
        # Ensure message was only printed once
        assert captured.out.count("Bridge access denied") == 1

    def test_post_network_error_disables_plugin(self):
        plugin = self._make_active_plugin()
        with patch("eval_runner.config.DASHBOARD_API_KEY", ""):
            with patch("requests.post", side_effect=ConnectionError("Timeout")):
                plugin._post_event("TEST_EVENT", {})
        assert plugin.active is False

    def test_post_with_api_key_header(self, monkeypatch):
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        plugin = self._make_active_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("eval_runner.config.SERVICE_API_KEY", ""):
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
