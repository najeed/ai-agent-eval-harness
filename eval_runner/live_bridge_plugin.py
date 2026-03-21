import requests
import os
from .plugins import BaseEvalPlugin
from .events import CoreEvents


class RemoteBridgePlugin(BaseEvalPlugin):
    """
    Zero-Touch Live Bridge Plugin.
    Propagates engine events to a running Admin Console via HTTP.
    """

    def __init__(self, endpoint="http://localhost:5000/api/debugger/state"):
        self.endpoint = os.environ.get("DEBUGGER_ENDPOINT", endpoint)
        self.active = False
        self._check_console_active()

    def _check_console_active(self):
        """Checks if the console is running to avoid unnecessary noise."""
        try:
            # Minimal timeout to avoid blocking the engine
            resp = requests.get(self.endpoint, timeout=0.1)
            self.active = resp.status_code == 200
        except Exception:
            self.active = False

    def _post_event(self, event_name, data):
        """Internal helper to post events to the console."""
        if not self.active:
            return

        try:
            requests.post(self.endpoint, json={"event": event_name, "data": data}, timeout=0.2)
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
