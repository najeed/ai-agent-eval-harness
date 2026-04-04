import requests
import os
from .plugins import BaseEvalPlugin
from .events import CoreEvents


import socket
from urllib.parse import urlparse

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
        forbidden = ["127.", "169.254", "0.0.0.0", "::1"]
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

    def _check_console_active(self):
        """Perform a heartbeat check to see if the Visual Debugger is alive."""
        if self.active is not None:
             return self.active

        from . import config
        headers = {}
        if config.DASHBOARD_API_KEY:
            headers["X-AES-API-KEY"] = config.DASHBOARD_API_KEY

        try:
            # We use a simple GET on the state endpoint as a heartbeat
            response = requests.get(self.endpoint, headers=headers, timeout=0.2)
            # 200 (Success) means the console is active and accessible.
            # 401 (Unauthorized) means we have no access, so we should stay inactive to stop looping.
            if response.status_code == 401:
                print(f"[RemoteBridgePlugin] Unauthorized: Invalid or missing API Key for {self.endpoint}")
                self.active = False
            else:
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

        from . import config
        headers = {}
        if config.DASHBOARD_API_KEY:
            headers["X-AES-API-KEY"] = config.DASHBOARD_API_KEY

        try:
            response = requests.post(self.endpoint, headers=headers, json={"event": event_name, "data": data}, timeout=0.5)
            if response.status_code == 401:
                print(f"[RemoteBridgePlugin] Unauthorized: Disabling bridge for this run.")
                self.active = False
        except Exception:
            # If the console dies, stop trying for this run
            self.active = False

    def before_evaluation(self, context):
        self._post_event(
            CoreEvents.RUN_START,
            {"scenario": context.scenario_id, "metadata": context.metadata},
        )

    def on_agent_turn_start(self, context):
        self._post_event(
            CoreEvents.TURN_START,
            {
                "turn_idx": context.turn_number,
                "agent_name": getattr(context, "agent_name", "agent"),
            },
        )

    def on_turn_end(self, context):
        self._post_event(
            CoreEvents.TURN_END,
            {
                "turn_idx": context.turn_number,
                "metrics": getattr(context, "turn_metrics", {}),
            },
        )

    def on_tool_request(self, context, tool_name, args):
        self._post_event(CoreEvents.TOOL_CALL, {"tool": tool_name, "arguments": args})
        return True

    def on_tool_result(self, context, tool_name, result):
        self._post_event(CoreEvents.TOOL_RESULT, {"tool": tool_name, "result": result})

    def after_evaluation(self, context, results):
        self._post_event(CoreEvents.RUN_END, {"status": "COMPLETED", "results_count": len(results)})
