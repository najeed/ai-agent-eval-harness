# eval_runner/adapters/autogen.py
from typing import Any

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub


class AG2AdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Industrial Adapter: AG2 (formerly AutoGen) with Forensic Trust Protocol compliance.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="ag2")

    def on_discover_adapters(self, registry: Any):
        """Register the ag2:// protocol."""
        print("      [Plugin] Registering AG2 adapters (v1) via on_discover_adapters hook.")
        registry.register("ag2", self.execute_autogen_query)

    async def execute_autogen_query(
        self, payload: dict[str, Any], endpoint: str = None, **kwargs
    ) -> dict[str, Any]:
        """
        Executes an AG2-based agentic workflow with standardized telemetry.
        Supports both local SDK logic and remote API fallback.
        """
        span_context = kwargs.get("span_context") or payload.get("span_context")
        agent_id = payload.get("agent_id", payload.get("task_id", "default_agent"))
        message = payload.get("message", payload.get("task_description", ""))

        # Support both 'endpoint' (registry standard) and 'url' (legacy/unit tests)
        url_candidate = endpoint or kwargs.get("url") or payload.get("url")

        # [Industrial Hardening] Distinguish between agent names and remote URLs
        is_explicit_remote = url_candidate and str(url_candidate).startswith("http")

        # If no explicit remote URL, check if we have a default fallback URL in config
        config_url = getattr(config, "AG2_API_URL", None)

        if is_explicit_remote:
            return await self._execute_remote_api(payload, url_candidate, span_context)

        try:
            # Check for real SDK (support both rebranded 'ag2' and legacy 'autogen' modules)
            try:
                import ag2 as autogen

                is_installed = True
            except ImportError:
                try:
                    import autogen

                    is_installed = True
                except ImportError:
                    is_installed = False

            if is_installed:
                version = getattr(autogen, "__version__", "unknown")
            else:
                version = "unknown"

            # [No-Masking Policy] If SDK missing for local execution, check for fallback
            if not is_installed:
                if config_url and str(config_url).startswith("http"):
                    # [Telemetry Compliance] Signal remote-fallback mode
                    emit(
                        CoreEvents.TURN_START,
                        {
                            "adapter": "ag2",
                            "agent_id": agent_id,
                            "message": message,
                            "mode": "remote-fallback",
                        },
                        span_context=span_context,
                    )
                    return await self._execute_remote_api(payload, config_url, span_context)

                # [Industrial Requirement] Use specific error message for diagnostic tools
                raise ImportError(
                    "AG2 SDK not installed. Required for local industrial-grade execution. "
                    "Native execution failed."
                ) from None

            # Path to the custom logic in metadata
            logic_path = payload.get("metadata", {}).get("logic_path")
            if not logic_path:
                return await self._execute_simulation(payload)

            import importlib

            module_name, attr_name = logic_path.split(":")
            module = importlib.import_module(module_name)
            handler_func = getattr(module, attr_name)

            print(f"      [Adapter] Executing AG2 workflow: {logic_path}")

            # Execute the provided logic
            chat_result = await handler_func()

            # Extract output from chat result
            output = ""
            if hasattr(chat_result, "chat_history"):
                output = chat_result.chat_history[-1].get("content", "")

            action = DualNormalizationHub.normalize_text(output)

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "ag2",
                    "version": version,
                    "logic_path": logic_path,
                },
            }

        except ImportError as e:
            emit(CoreEvents.ERROR, {"message": str(e)})
            return {
                "status": "error",
                "action": "error",
                "message": str(e),
                "metadata": {"framework": "ag2", "mode": "failed"},
            }
        except Exception as e:
            emit(CoreEvents.ERROR, {"message": f"AG2 execution failed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"AG2 execution failed: {e}",
                "metadata": {"framework": "ag2", "mode": "failed"},
            }

    async def _execute_remote_api(
        self, payload: dict[str, Any], url: str, span_context: dict[str, Any] = None
    ) -> dict[str, Any]:
        """Executes AG2 via remote API."""
        from .common import SessionManager

        agent_id = payload.get("agent_id", payload.get("task_id", "default_agent"))

        # [Telemetry Compliance] Signal start of remote execution
        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "protocol": "v1",
                "mode": "remote",
            },
            span_context=span_context,
        )

        print(f"      [Adapter] Executing AG2 Remote API: {url}")

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    res = response.raise_for_status()
                    if hasattr(res, "__await__"):
                        await res

                json_data = response.json()
                if hasattr(json_data, "__await__"):
                    json_data = await json_data
                return json_data

        try:
            data = await self.call_with_retry(_call)
            output = data.get("output", "")
            action = DualNormalizationHub.normalize_text(output)

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "ag2",
                    "mode": "remote",
                    "endpoint": url,
                    "protocol": "v1",
                },
            }
        except Exception as e:
            emit(
                CoreEvents.ERROR,
                {"message": f"AG2 Remote API failed: {e}"},
                span_context=span_context,
            )
            return {
                "status": "error",
                "action": "error",
                "message": f"AG2 Remote API failed: {e}",
                "metadata": {"framework": "ag2", "mode": "failed"},
            }

    async def _execute_simulation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Fallback simulation for testing environments."""
        # [No-Masking] Even simulation requires SDK check if it uses SDK components
        try:
            import ag2  # noqa: F401
        except ImportError:
            try:
                import autogen  # noqa: F401
            except ImportError:
                raise ImportError(
                    "AG2 SDK not installed. Required for simulation parity. "
                    "Native execution failed."
                ) from None

        # [Telemetry Compliance] Signal start of simulated execution
        agent_id = payload.get("agent_id", payload.get("task_id", "default_agent"))
        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "protocol": "v1",
                "mode": "simulated",
            },
        )
        emit(
            CoreEvents.NODE_START,
            {
                "adapter": "autogen",
                "node_id": agent_id,
            },
        )

        return {
            "status": "success",
            "output": "Simulation: AG2 agent completed task successfully.",
            "action": "final_answer",
            "metadata": {"framework": "ag2", "mode": "simulated", "protocol": "v1"},
        }


# Legacy alias for backward compatibility with existing test suites
AutoGenAdapterPlugin = AG2AdapterPlugin
