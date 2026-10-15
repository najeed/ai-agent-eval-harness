import logging
import os
import socket
from urllib.parse import urlparse

import requests

from .events import CoreEvents
from .plugins import BaseEvalPlugin

logger = logging.getLogger(__name__)


def is_safe_url(url_str: str) -> bool:
    """Checks if a URL refers to a safe, non-internal location."""
    try:
        parsed = urlparse(url_str)
        if not parsed.scheme or not parsed.netloc:
            return False

        # Resolve to IP
        hostname = parsed.hostname
        if not hostname:
            return False

        # Allow localhost ONLY if explicitly configured by the system,
        # but block it by default if provided by a scenario/untrusted environment.
        ip = socket.gethostbyname(hostname)

        # Block Loopback, Multicast, Link-Local (Cloud Meta), and Private subnets
        # if they originate from an untrusted source.
        # Note: 169.254.169.254 is the standard Cloud Metadata IP.
        forbidden = ["127.", "169.254", "0.0.0.0", "::1"]  # nosec B104
        for addr in forbidden:
            if ip.startswith(addr):
                return False
        return True
    except Exception:
        return False


class RemoteBridgePlugin(BaseEvalPlugin):
    """
    Zero-Touch Live Bridge Plugin.
    Propagates engine events to a running Visual Debugger via HTTP.
    """

    def __init__(self, endpoint="http://localhost:5000/api/debugger/state"):
        self.endpoint = os.environ.get("DEBUGGER_ENDPOINT", endpoint)
        # R1.1 Remediation: Validate external/untrusted endpoints
        # Note: We allow localhost specifically if it matches our default
        if self.endpoint != "http://localhost:5000/api/debugger/state":
            if not is_safe_url(self.endpoint):
                print(f"⚠️  Security: Blocking unsafe bridge endpoint: {self.endpoint}")
                self.active = False
                return

        self.active = None  # Unknown
        self._denied_diagnostic_emitted = False

    def _resolve_service_headers(self) -> dict[str, str]:
        """
        Resolves generic server-side machine credentials for the background bridge client.
        Prioritizes the active configured authorization backend and SERVICE_API_KEY
        over legacy static DASHBOARD_API_KEY.
        Never copies browser session cookies, user handoff tokens, tenant headers,
        or URL query parameters into background Runtime traffic.
        """
        headers: dict[str, str] = {}
        cred: str | None = None

        # 1. Attempt to resolve from active configured authorization backend
        try:
            from .console.auth_manager import (
                get_auth_provider,
                has_configured_authorization_backend,
            )

            if has_configured_authorization_backend():
                provider = get_auth_provider()
                if hasattr(provider, "get_service_credential") and callable(
                    provider.get_service_credential
                ):
                    cred = provider.get_service_credential()
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("Failed resolving bridge credential from auth provider: %s", exc)
            cred = None

        # 2. Check deployment-secret variable SERVICE_API_KEY
        if not cred:
            env_service = os.getenv("SERVICE_API_KEY")
            if env_service and env_service.strip():
                cred = env_service.strip()

        # 3. Compatible fallback to deployment-configured static DASHBOARD_API_KEY
        if not cred:
            from . import config

            configured_key = getattr(config, "DASHBOARD_API_KEY", None) or os.getenv(
                "DASHBOARD_API_KEY"
            )
            if configured_key and str(configured_key).strip():
                cred = str(configured_key).strip()

        if cred and isinstance(cred, str) and cred.strip():
            clean_cred = cred.strip()
            if clean_cred.startswith("Bearer "):
                headers["Authorization"] = clean_cred
            else:
                headers["X-AES-API-KEY"] = clean_cred

        return headers

    def _handle_denied_response(self, status_code: int) -> None:
        """
        Emits exactly one rate-limited diagnostic per bridge instance
        and disables further traffic.
        """
        self.active = False
        if not getattr(self, "_denied_diagnostic_emitted", False):
            self._denied_diagnostic_emitted = True
            reason = "Unauthenticated (401)" if status_code == 401 else "Unauthorized (403)"
            print(
                f"[RemoteBridgePlugin] Bridge access denied ({reason}): "
                f"Service principal missing or lacks required debugger permissions for "
                f"{self.endpoint}. Disabling further bridge traffic for this instance.",
                flush=True,
            )

    def _check_console_active(self):
        """Perform a heartbeat check to see if the Visual Debugger is alive."""
        if self.active is not None:
            return self.active

        from . import events

        # [Industrial Hardening]: Skip HTTP POSTs if we are running in the same
        # process as the Console (Visual Debugger). The Console already has a
        # local subscriber registered via subscribe_debugger().
        if "debugger" in events.EventEmitter.get_global()._keyed_subscribers:
            print("[RemoteBridgePlugin] Local subscriber detected. Skipping HTTP bridge.")
            self.active = False
            return False

        headers = self._resolve_service_headers()

        try:
            # We use a simple GET on the state endpoint as a heartbeat
            response = requests.get(self.endpoint, headers=headers, timeout=0.2)
            # 200 (Success) means the console is active and accessible.
            # 401/403 (Denied) means unauthenticated or unauthorized;
            # disable bridge and halt looping.
            if response.status_code in (401, 403):
                self._handle_denied_response(response.status_code)
                return False
            self.active = response.status_code == 200
        except Exception:
            self.active = False
        return self.active

    def _post_event(self, event_name, data):
        """Update the Visual Debugger state with the latest turn data."""
        if self.active is False:
            return

        if self.active is None:
            if not self._check_console_active():
                return

        headers = self._resolve_service_headers()

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json={"event": event_name, "data": data},
                timeout=0.5,
            )
            if response.status_code in (401, 403):
                self._handle_denied_response(response.status_code)
        except Exception:
            # If the console dies, stop trying for this run
            self.active = False

    def before_evaluation(self, context, **kwargs):
        self._post_event(
            CoreEvents.RUN_START,
            {"id": context.identifier, "metadata": context.metadata},
        )

    def on_agent_turn_start(self, context, **kwargs):
        self._post_event(
            CoreEvents.TURN_START,
            {
                "turn_idx": context.turn_number,
                "agent_name": getattr(context, "agent_name", "agent"),
            },
        )

    def on_turn_end(self, context, **kwargs):
        self._post_event(
            CoreEvents.TURN_END,
            {
                "turn_idx": context.turn_number,
                "metrics": getattr(context, "turn_metrics", {}),
            },
        )

    def on_tool_request(self, context, tool, arguments=None, **kwargs):
        self._post_event(CoreEvents.TOOL_CALL, {"tool": tool, "arguments": arguments})
        return True

    def on_tool_result(self, context, tool, result, **kwargs):
        self._post_event(CoreEvents.TOOL_RESULT, {"tool": tool, "result": result})

    def after_evaluation(self, context, results, **kwargs):
        self._post_event(CoreEvents.RUN_END, {"status": "COMPLETED", "results_count": len(results)})
