# eval_runner/adapters/langchain.py
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import AESCallbackHandler, BaseAdapter, DualNormalizationHub


class LangChainAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Industrial Adapter: Provides native LangChain support.
    Supports versioned protocols (e.g., 'langchain:v1') and legacy LangServe.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="langchain")

    def on_discover_adapters(self, registry: Any):
        """Register versioned langchain protocols."""
        print("      [Plugin] Registering LangChain adapters (v1) via on_discover_adapters hook.")
        registry.register("langchain", self.execute_langchain_query)
        registry.register("langchain:v1", self.execute_langchain_query)

    # Alias for backward compatibility with legacy unit tests
    async def execute_langserve_query(
        self, payload: dict[str, Any], endpoint: str = None
    ) -> dict[str, Any]:
        """Legacy entry point redirected to the new unified execution path."""
        return await self.execute_langchain_query(payload, endpoint)

    async def execute_langchain_query(
        self, payload: dict[str, Any], endpoint: str = None
    ) -> dict[str, Any]:
        """
        Executes a LangChain chain locally or via LangServe with telemetry.
        """
        task_id = payload.get("task_id", "default_task")
        input_data = payload.get("input", {})
        url = (
            endpoint
            or payload.get("url")
            or payload.get("base_url")
            or payload.get("metadata", {}).get("langserve_url")
        )

        # Branch logic: Local SDK vs Remote LangServe
        if not url:
            # Check for a specific chain path in metadata for local execution
            chain_path = payload.get("metadata", {}).get("chain_path")
            if chain_path:
                return await self._execute_local_sdk(task_id, input_data, chain_path)
            else:
                # Fallback to simulated mode if no path provided (backwards compatibility)
                return await self._execute_simulation(task_id, input_data)
        else:
            return await self._execute_remote_langserve(url, input_data, payload)

    async def _execute_local_sdk(
        self, task_id: str, input_data: Any, chain_path: str
    ) -> dict[str, Any]:
        """Executes a real LangChain chain using the local SDK."""
        try:
            import importlib

            import langchain

            module_name, attr_name = chain_path.split(":")
            module = importlib.import_module(module_name)
            chain = getattr(module, attr_name)

            print(f"      [Adapter] Executing local LangChain ainvoke: {chain_path}")
            handler = AESCallbackHandler(adapter_name="langchain", identifier=task_id)

            # Execution with telemetry
            output = await chain.ainvoke(input_data, config={"callbacks": [handler]})

            # Normalize: Use full hub for dicts; text heuristics for strings
            if isinstance(output, dict):
                action = DualNormalizationHub.normalize(output, 200)
            else:
                action = DualNormalizationHub.normalize_text(str(output))

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "langchain",
                    "version": getattr(langchain, "__version__", "unknown"),
                    "chain_path": chain_path,
                    "protocol": "v1",
                },
            }
        except ImportError as e:
            emit(CoreEvents.ERROR, {"message": f"LangChain SDK not installed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"LangChain SDK not installed: {e}",
            }
        except (AttributeError, ValueError) as e:
            emit(CoreEvents.ERROR, {"message": f"LangChain local execution failed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"LangChain local execution failed: {e}",
            }

    async def _execute_simulation(self, task_id: str, input_data: Any) -> dict[str, Any]:
        """Legacy simulated path for testing environments."""
        handler = AESCallbackHandler(adapter_name="langchain", identifier=task_id)
        handler.on_chain_start({}, input_data)
        handler.on_node_start({"id": [task_id]}, input_data)
        handler.on_node_end({"output": "simulated"})
        handler.on_chain_end({"output": "simulated"})

        output = f"Processed {task_id} via LangChain v1 Simulation"
        return {
            "status": "success",
            "output": output,
            "action": "final_answer",
            "metadata": {"framework": "langchain", "protocol": "v1", "mode": "simulated"},
        }

    async def _execute_remote_langserve(
        self, url: str, input_data: Any, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes a query against a remote LangServe endpoint with connection pooling."""
        from .common import SessionManager

        if not url.endswith("/invoke"):
            url = url.rstrip("/") + "/invoke"

        emit(CoreEvents.CHAIN_START, {"adapter": "langchain", "mode": "remote", "url": url})

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(url, json={"input": input_data}) as response:
                response.raise_for_status()
                return await response.json(), response.status

        try:
            data, status = await self.call_with_retry(_call)
            output = data.get("output", "")
            if isinstance(output, dict):
                action = DualNormalizationHub.normalize(output, status)
            else:
                action = DualNormalizationHub.normalize_text(str(output))

            emit(CoreEvents.CHAIN_END, {"adapter": "langchain", "mode": "remote"})
            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "langchain",
                    "endpoint": url,
                    "mode": "remote",
                    "protocol": "v1",
                },
            }
        except Exception as e:
            emit(CoreEvents.ERROR, {"message": str(e)})
            return {"status": "error", "action": "error", "message": str(e)}
