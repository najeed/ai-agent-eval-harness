# eval_runner/adapters/langgraph.py
from __future__ import annotations

import asyncio
import importlib
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import AESCallbackHandler, BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)

try:
    from langgraph.callbacks import GraphCallbackHandler
except ImportError:  # pragma: no cover - dependency-gated
    GraphCallbackHandler = AESCallbackHandler  # type: ignore[misc,assignment]


_MISSING = object()
_ALLOWED_STREAM_MODES = {
    "values",
    "updates",
    "checkpoints",
    "tasks",
    "debug",
    "messages",
    "custom",
}


def _json_safe(value: Any, *, max_depth: int = 5, _depth: int = 0) -> Any:
    """Convert LangGraph/Pydantic/dataclass objects to bounded JSON-safe data."""
    if _depth > max_depth:
        return f"<max-depth:{type(value).__name__}>"

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    if isinstance(value, dict):
        return {
            str(k): _json_safe(v, max_depth=max_depth, _depth=_depth + 1) for k, v in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v, max_depth=max_depth, _depth=_depth + 1) for v in value]

    if is_dataclass(value):
        try:
            return _json_safe(asdict(value), max_depth=max_depth, _depth=_depth + 1)
        except Exception:
            pass

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"), max_depth=max_depth, _depth=_depth + 1)
        except Exception:
            try:
                return _json_safe(model_dump(), max_depth=max_depth, _depth=_depth + 1)
            except Exception:
                pass

    if hasattr(value, "value") and hasattr(value, "id"):
        return {
            "id": _json_safe(getattr(value, "id", None), max_depth=max_depth, _depth=_depth + 1),
            "value": _json_safe(
                getattr(value, "value", None),
                max_depth=max_depth,
                _depth=_depth + 1,
            ),
        }

    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _extract_interrupts(value: Any) -> list[dict[str, Any]]:
    """Extract LangGraph interrupt objects from dicts, GraphOutput, or stream parts."""
    interrupts: list[dict[str, Any]] = []

    if value is None:
        return interrupts

    if isinstance(value, dict):
        raw = value.get("__interrupt__")
        if raw is not None:
            items = raw if isinstance(raw, (list, tuple)) else [raw]
            for item in items:
                interrupts.append(_json_safe(item))

        direct_interrupts = value.get("interrupts")
        if direct_interrupts:
            items = (
                direct_interrupts
                if isinstance(direct_interrupts, (list, tuple))
                else [direct_interrupts]
            )
            for item in items:
                interrupt_data = _json_safe(item)
                if interrupt_data not in interrupts:
                    interrupts.append(interrupt_data)

        if value.get("type") == "values":
            interrupts.extend(_extract_interrupts(value.get("data")))

        return interrupts

    raw_interrupts = getattr(value, "interrupts", None)
    if raw_interrupts:
        items = raw_interrupts if isinstance(raw_interrupts, (list, tuple)) else [raw_interrupts]
        for item in items:
            interrupts.append(_json_safe(item))

    raw_value = getattr(value, "value", None)
    if isinstance(raw_value, dict) and "__interrupt__" in raw_value:
        interrupts.extend(_extract_interrupts(raw_value))

    return interrupts


def _unwrap_graph_output(value: Any) -> Any:
    """Unwrap LangGraph GraphOutput while preserving ordinary graph outputs."""
    if value is None:
        return None

    if isinstance(value, dict):
        return value

    for attr in ("value", "output", "result"):
        if hasattr(value, attr):
            try:
                candidate = getattr(value, attr)
                if candidate is not None:
                    return candidate
            except Exception:
                continue

    return value


def _load_object(path: str) -> Any:
    """Load module:attribute or module.attr object path."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("LangGraph graph_path must be a non-empty 'module:attribute' path.")

    path = path.strip()

    if ":" in path:
        module_name, attr_path = path.split(":", 1)
    else:
        module_name, _, attr_path = path.rpartition(".")

    if not module_name or not attr_path:
        raise ValueError(
            f"Invalid LangGraph graph_path '{path}'. "
            "Expected 'module:attribute' or 'module.attribute'."
        )

    obj = importlib.import_module(module_name)

    for part in attr_path.split("."):
        obj = getattr(obj, part)

    return obj


def _resolve_graph(obj: Any, payload: dict[str, Any]) -> Any:
    """Resolve a concrete executable LangGraph graph."""
    if callable(obj) and not hasattr(obj, "ainvoke"):
        metadata = payload.get("metadata") or {}
        factory_kwargs = metadata.get("graph_factory_kwargs") or {}

        if not isinstance(factory_kwargs, dict):
            raise ValueError("metadata.graph_factory_kwargs must be an object.")

        try:
            obj = obj(**factory_kwargs)
        except TypeError:
            obj = obj()

    if not hasattr(obj, "ainvoke") or not callable(obj.ainvoke):
        raise TypeError(
            "Resolved LangGraph object does not expose the required async 'ainvoke' API."
        )

    return obj


class _LangGraphTelemetryHandler(GraphCallbackHandler):
    """LangGraph-aware callback bridge into AgentV's event bus."""

    def __init__(
        self,
        adapter_name: str,
        identifier: str,
        span_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._generic = AESCallbackHandler(
            adapter_name=adapter_name,
            identifier=identifier,
        )
        self.span_context = span_context

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        emit(event, data, span_context=self.span_context)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self._generic.on_chain_start(serialized, inputs, **kwargs)

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        self._generic.on_chain_end(outputs, **kwargs)

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "adapter": "langgraph",
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )

    def on_node_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self._generic.on_node_start(serialized, inputs, **kwargs)

    def on_node_end(self, outputs: Any, **kwargs: Any) -> None:
        self._generic.on_node_end(outputs, **kwargs)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        self._generic.on_llm_start(serialized, prompts, **kwargs)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self._generic.on_llm_end(response, **kwargs)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.TOOL_CALL,
            {
                "adapter": "langgraph",
                "tool_name": (serialized.get("name") if isinstance(serialized, dict) else None)
                or "unknown",
                "input_summary": type(input_str).__name__,
            },
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        self._emit(
            CoreEvents.TOOL_RESULT,
            {
                "adapter": "langgraph",
                "output_type": type(output).__name__,
            },
        )

    def on_interrupt(self, event: Any) -> None:
        interrupts = getattr(event, "interrupts", ()) or ()
        self._emit(
            CoreEvents.HITL_PAUSE,
            {
                "adapter": "langgraph",
                "run_id": str(getattr(event, "run_id", "") or ""),
                "checkpoint_id": str(getattr(event, "checkpoint_id", "") or ""),
                "checkpoint_ns": list(getattr(event, "checkpoint_ns", ()) or ()),
                "interrupts": _json_safe(interrupts),
            },
        )

    def on_resume(self, event: Any) -> None:
        self._emit(
            CoreEvents.ADAPTER_DEBUG,
            {
                "adapter": "langgraph",
                "event": "graph_resume",
                "run_id": str(getattr(event, "run_id", "") or ""),
                "checkpoint_id": str(getattr(event, "checkpoint_id", "") or ""),
                "checkpoint_ns": list(getattr(event, "checkpoint_ns", ()) or ()),
            },
        )


class LangGraphAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production LangGraph adapter.

    Supports:
      * Local compiled LangGraph applications via graph_path.
      * LangGraph Server deployments via RemoteGraph.
      * Async graph execution through ainvoke/astream.
      * Resumable interrupts via Command(resume=...).
      * Thread/checkpoint-aware execution.
      * Graph-level and LangChain callback telemetry.
      * Structured stream capture.
      * State/checkpoint inspection after execution.
      * Fail-closed behavior when no executable graph is bound.
    """

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="langgraph")

    def on_discover_adapters(self, registry: Any) -> None:
        """Register LangGraph protocol versions."""
        registry.register("langgraph", self.execute_langgraph_node)
        registry.register("langgraph:v2", self.execute_langgraph_node)

    async def execute_langgraph_node(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Execute a real LangGraph graph and return a normalized AgentV result."""
        if not isinstance(payload, dict):
            raise TypeError("LangGraph adapter payload must be an object.")

        metadata = payload.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise TypeError("LangGraph adapter metadata must be an object.")

        node_id = str(
            payload.get("node_id")
            or payload.get("task_id")
            or payload.get("agent_id")
            or metadata.get("node_id")
            or "langgraph-run"
        )

        span_context = payload.get("span_context")
        if not isinstance(span_context, dict):
            span_context = None

        execution_target = (
            payload.get("graph_path")
            or metadata.get("graph_path")
            or payload.get("graph")
            or endpoint
        )

        try:
            import langgraph

            version = getattr(langgraph, "__version__", "unknown")

            graph = await self._resolve_execution_target(
                execution_target=execution_target,
                payload=payload,
                metadata=metadata,
            )

            graph_input = self._resolve_input(payload)
            runnable_config = self._build_runnable_config(
                payload=payload,
                metadata=metadata,
                node_id=node_id,
            )

            telemetry = _LangGraphTelemetryHandler(
                adapter_name="langgraph",
                identifier=node_id,
                span_context=span_context,
            )

            self._attach_callback(runnable_config, telemetry)

            command_input = self._build_command_input(payload, graph_input)

            stream_enabled = bool(
                payload.get("stream")
                or metadata.get("stream")
                or payload.get("stream_mode")
                or metadata.get("stream_mode")
            )

            if stream_enabled:
                result, stream_summary = await self._execute_stream(
                    graph=graph,
                    graph_input=command_input,
                    runnable_config=runnable_config,
                    payload=payload,
                    telemetry=telemetry,
                )
            else:
                result, stream_summary = await self._execute_invoke(
                    graph=graph,
                    graph_input=command_input,
                    runnable_config=runnable_config,
                    payload=payload,
                )

            interrupt_data = _extract_interrupts(result)

            state_snapshot = await self._read_state(
                graph,
                runnable_config,
                enabled=bool(payload.get("capture_state", metadata.get("capture_state", True))),
            )

            output = _unwrap_graph_output(result)

            if interrupt_data:
                action = "hitl_pause"
                status = "hitl_pause"
            else:
                action = self._normalize_output(output)
                status = "error" if action == "error" else "success"

            result_metadata = {
                "framework": "langgraph",
                "version": version,
                "protocol": "v2",
                "mode": "remote" if self._is_remote_target(execution_target) else "local",
                "graph_path": (
                    execution_target
                    if execution_target and not self._is_remote_target(execution_target)
                    else None
                ),
                "endpoint": (
                    execution_target
                    if execution_target and self._is_remote_target(execution_target)
                    else None
                ),
                "node_id": node_id,
                "thread_id": (
                    (runnable_config.get("configurable") or {}).get("thread_id")
                    if isinstance(runnable_config.get("configurable"), dict)
                    else None
                ),
                "interrupts": interrupt_data,
                "state": state_snapshot,
                "stream": stream_summary,
            }

            return {
                "status": status,
                "output": output,
                "action": action,
                "metadata": result_metadata,
            }

        except asyncio.CancelledError:
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "langgraph",
                    "node_id": node_id,
                    "message": "LangGraph execution cancelled.",
                },
                span_context=span_context,
            )
            raise
        except ImportError as exc:
            message = (
                "LangGraph dependency is not installed. "
                "Install the AgentV LangGraph framework extra."
            )
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "langgraph",
                    "node_id": node_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                span_context=span_context,
            )
            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "langgraph",
                    "mode": "failed",
                    "error_type": type(exc).__name__,
                },
            }
        except Exception as exc:
            message = f"LangGraph execution failed: {exc}"
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "langgraph",
                    "node_id": node_id,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                span_context=span_context,
            )
            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "langgraph",
                    "mode": "failed",
                    "error_type": type(exc).__name__,
                },
            }

    async def _resolve_execution_target(
        self,
        execution_target: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Any:
        """Resolve a local graph object or construct a LangGraph RemoteGraph."""
        if execution_target is None:
            raise ValueError(
                "No LangGraph execution target supplied. "
                "Provide metadata.graph_path for a local compiled graph or "
                "an HTTP endpoint for a LangGraph Server deployment."
            )

        if self._is_remote_target(str(execution_target)):
            return self._create_remote_graph(
                endpoint=str(execution_target),
                payload=payload,
                metadata=metadata,
            )

        graph_obj = _load_object(str(execution_target))

        graph_factory_kwargs = metadata.get("graph_factory_kwargs")
        if graph_factory_kwargs is not None:
            metadata = dict(metadata)
            metadata["graph_factory_kwargs"] = graph_factory_kwargs

        graph = _resolve_graph(graph_obj, payload)
        return graph

    @staticmethod
    def _create_remote_graph(
        endpoint: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Any:
        """Create a RemoteGraph client for a LangGraph Server deployment."""
        try:
            from langgraph.pregel.remote import RemoteGraph
        except ImportError as exc:
            raise ImportError(
                "LangGraph RemoteGraph support requires the LangGraph SDK/runtime."
            ) from exc

        assistant_id = (
            payload.get("assistant_id")
            or payload.get("graph_id")
            or payload.get("agent_id")
            or metadata.get("assistant_id")
            or metadata.get("graph_id")
            or metadata.get("assistant_id")
        )

        if not assistant_id:
            raise ValueError("Remote LangGraph execution requires assistant_id/graph_id.")

        api_key = (
            payload.get("api_key") or metadata.get("api_key") or metadata.get("langgraph_api_key")
        )

        headers = metadata.get("headers") or {}
        if not isinstance(headers, dict):
            raise TypeError("metadata.headers must be an object.")

        return RemoteGraph(
            str(assistant_id),
            url=endpoint,
            api_key=api_key,
            headers={str(k): str(v) for k, v in headers.items()},
            name=str(metadata.get("graph_name") or assistant_id),
            distributed_tracing=bool(metadata.get("distributed_tracing", False)),
        )

    @staticmethod
    def _resolve_input(payload: dict[str, Any]) -> Any:
        """Resolve graph input without fabricating execution state."""
        if "input" in payload:
            return payload["input"]

        metadata = payload.get("metadata") or {}

        if "input" in metadata:
            return metadata["input"]

        if "messages" in payload:
            return {"messages": payload["messages"]}

        if "task_description" in payload:
            return {"task_description": payload["task_description"]}

        if "message" in payload:
            return {"message": payload["message"]}

        raise ValueError(
            "LangGraph adapter requires an explicit 'input', 'messages', "
            "'task_description', or 'message'."
        )

    @staticmethod
    def _build_runnable_config(
        payload: dict[str, Any],
        metadata: dict[str, Any],
        node_id: str,
    ) -> dict[str, Any]:
        """Build a LangGraph RunnableConfig while preserving caller configuration."""
        user_config = payload.get("config")
        if user_config is None:
            user_config = metadata.get("config") or {}

        if not isinstance(user_config, dict):
            raise TypeError("LangGraph config must be an object.")

        config_data = dict(user_config)

        configurable = config_data.get("configurable")
        if configurable is None:
            configurable = {}
        if not isinstance(configurable, dict):
            raise TypeError("LangGraph config.configurable must be an object.")

        run_id = (
            payload.get("run_id")
            or metadata.get("run_id")
            or payload.get("task_id")
            or payload.get("agent_id")
            or node_id
        )

        configurable.setdefault("thread_id", str(run_id))
        config_data["configurable"] = configurable

        tags = config_data.get("tags")
        if tags is None:
            tags = []
        elif not isinstance(tags, list):
            tags = list(tags) if isinstance(tags, (tuple, set)) else [str(tags)]

        mandatory_tags = ["agentv", "adapter:langgraph"]
        for tag in mandatory_tags:
            if tag not in tags:
                tags.append(tag)

        config_data["tags"] = tags

        lc_metadata = config_data.get("metadata")
        if lc_metadata is None:
            lc_metadata = {}
        if not isinstance(lc_metadata, dict):
            raise TypeError("LangGraph config.metadata must be an object.")

        lc_metadata.update(
            {
                "agentv_adapter": "langgraph",
                "agentv_adapter_version": "v2",
                "agentv_node_id": node_id,
            }
        )
        config_data["metadata"] = lc_metadata

        return config_data

    @staticmethod
    def _attach_callback(
        runnable_config: dict[str, Any],
        telemetry: _LangGraphTelemetryHandler,
    ) -> None:
        """Append AgentV telemetry without allowing it to be silently replaced."""
        callbacks = runnable_config.get("callbacks")

        if callbacks is None:
            runnable_config["callbacks"] = [telemetry]
            return

        if isinstance(callbacks, list):
            if telemetry not in callbacks:
                runnable_config["callbacks"] = [*callbacks, telemetry]
            return

        if isinstance(callbacks, tuple):
            runnable_config["callbacks"] = [*callbacks, telemetry]
            return

        runnable_config["callbacks"] = [callbacks, telemetry]

    @staticmethod
    def _build_command_input(payload: dict[str, Any], graph_input: Any) -> Any:
        """Convert an explicit resume request into a LangGraph Command."""
        resume = payload.get("resume", _MISSING)

        if resume is _MISSING:
            metadata = payload.get("metadata") or {}
            resume = metadata.get("resume", _MISSING)

        if resume is _MISSING:
            return graph_input

        try:
            from langgraph.types import Command
        except ImportError as exc:
            raise ImportError(
                "LangGraph Command support is unavailable in the installed dependency."
            ) from exc

        return Command(resume=resume)

    async def _execute_invoke(
        self,
        graph: Any,
        graph_input: Any,
        runnable_config: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Execute graph.ainvoke with supported LangGraph controls."""
        kwargs = self._execution_kwargs(payload)

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "langgraph",
                "operation": "ainvoke",
            },
            span_context=payload.get("span_context"),
        )

        output = await graph.ainvoke(
            graph_input,
            runnable_config,
            **kwargs,
        )

        emit(
            CoreEvents.CHAIN_END,
            {
                "adapter": "langgraph",
                "operation": "ainvoke",
            },
            span_context=payload.get("span_context"),
        )

        return output, {
            "enabled": False,
            "mode": "ainvoke",
            "events": 0,
        }

    async def _execute_stream(
        self,
        graph: Any,
        graph_input: Any,
        runnable_config: dict[str, Any],
        payload: dict[str, Any],
        telemetry: _LangGraphTelemetryHandler,
    ) -> tuple[Any, dict[str, Any]]:
        """Execute LangGraph astream and retain a bounded forensic stream summary."""
        if not hasattr(graph, "astream") or not callable(graph.astream):
            raise TypeError(
                "Resolved LangGraph object does not expose the required async 'astream' API."
            )

        stream_mode = (
            payload.get("stream_mode")
            or (payload.get("metadata") or {}).get("stream_mode")
            or "values"
        )

        if isinstance(stream_mode, str):
            if stream_mode not in _ALLOWED_STREAM_MODES:
                raise ValueError(
                    f"Unsupported LangGraph stream_mode '{stream_mode}'. "
                    f"Supported modes: {sorted(_ALLOWED_STREAM_MODES)}"
                )
        elif isinstance(stream_mode, (list, tuple)):
            invalid = [m for m in stream_mode if m not in _ALLOWED_STREAM_MODES]
            if invalid:
                raise ValueError(f"Unsupported LangGraph stream modes: {invalid}")
            stream_mode = list(stream_mode)
        else:
            raise TypeError("LangGraph stream_mode must be a string or list of strings.")

        version = str(payload.get("stream_version") or "v2")
        if version not in {"v1", "v2"}:
            version = "v2"

        kwargs = self._execution_kwargs(payload)
        kwargs["stream_mode"] = stream_mode
        kwargs["version"] = version

        if "subgraphs" in payload:
            kwargs["subgraphs"] = bool(payload["subgraphs"])
        elif "subgraphs" in (payload.get("metadata") or {}):
            kwargs["subgraphs"] = bool(payload["metadata"]["subgraphs"])

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "langgraph",
                "operation": "astream",
                "stream_mode": stream_mode,
                "stream_version": version,
            },
            span_context=payload.get("span_context"),
        )

        final_output: Any = None
        event_count = 0
        interrupt_events: list[dict[str, Any]] = []
        node_update_count = 0

        async for chunk in graph.astream(
            graph_input,
            runnable_config,
            **kwargs,
        ):
            event_count += 1

            chunk_interrupts = _extract_interrupts(chunk)
            if chunk_interrupts:
                interrupt_events.extend(chunk_interrupts)

            if version == "v2" and isinstance(chunk, dict) and "type" in chunk:
                chunk_type = chunk.get("type")
                chunk_data = chunk.get("data")

                if chunk_type == "values":
                    final_output = chunk_data
                elif chunk_type == "updates":
                    node_update_count += 1
                elif chunk_type in {"checkpoints", "tasks", "debug"}:
                    node_update_count += 1
                elif chunk_type == "custom":
                    telemetry._emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {
                            "adapter": "langgraph",
                            "event": "custom_stream",
                            "data_type": type(chunk_data).__name__,
                        },
                    )
            else:
                final_output = chunk

            if event_count <= 100:
                telemetry._emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "langgraph",
                        "event": "stream_chunk",
                        "sequence": event_count,
                        "chunk_type": (
                            chunk.get("type")
                            if isinstance(chunk, dict) and "type" in chunk
                            else type(chunk).__name__
                        ),
                    },
                )

        emit(
            CoreEvents.CHAIN_END,
            {
                "adapter": "langgraph",
                "operation": "astream",
                "stream_events": event_count,
            },
            span_context=payload.get("span_context"),
        )

        if interrupt_events:
            final_output = (
                final_output if final_output is not None else {"__interrupt__": interrupt_events}
            )

        return final_output, {
            "enabled": True,
            "mode": "astream",
            "stream_mode": stream_mode,
            "stream_version": version,
            "events": event_count,
            "node_updates": node_update_count,
            "interrupt_events": interrupt_events,
            "truncated_event_telemetry": event_count > 100,
        }

    @staticmethod
    def _execution_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
        """Resolve explicit LangGraph execution controls."""
        metadata = payload.get("metadata") or {}
        controls = payload.get("execution") or metadata.get("execution") or {}

        if not isinstance(controls, dict):
            raise TypeError("LangGraph execution controls must be an object.")

        kwargs: dict[str, Any] = {}

        source = dict(controls)
        for key in (
            "context",
            "output_keys",
            "interrupt_before",
            "interrupt_after",
            "durability",
            "control",
        ):
            if key in payload:
                source[key] = payload[key]
            elif key in metadata:
                source[key] = metadata[key]

        for key in (
            "context",
            "output_keys",
            "interrupt_before",
            "interrupt_after",
            "durability",
            "control",
        ):
            if key in source:
                kwargs[key] = source[key]

        return kwargs

    async def _read_state(
        self,
        graph: Any,
        runnable_config: dict[str, Any],
        *,
        enabled: bool,
    ) -> dict[str, Any] | None:
        """Read authoritative persisted LangGraph state when supported."""
        if not enabled:
            return None

        if not hasattr(graph, "aget_state") or not callable(graph.aget_state):
            return None

        try:
            snapshot = await graph.aget_state(runnable_config)

            if snapshot is None:
                return None

            state = {
                "type": type(snapshot).__name__,
            }

            for attr in (
                "values",
                "next",
                "tasks",
                "metadata",
                "config",
                "created_at",
                "parent_config",
            ):
                if hasattr(snapshot, attr):
                    try:
                        state[attr] = _json_safe(getattr(snapshot, attr))
                    except Exception:
                        logger.debug(
                            "Failed serializing LangGraph state field '%s'.",
                            attr,
                            exc_info=True,
                        )

            return state
        except Exception as exc:
            logger.debug("LangGraph state inspection failed: %s", exc, exc_info=True)
            return {
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    @staticmethod
    def _normalize_output(output: Any) -> str:
        """Normalize graph output into an AgentV action."""
        output = _unwrap_graph_output(output)

        if output is None:
            return "error"

        if isinstance(output, dict):
            if "__interrupt__" in output:
                return "hitl_pause"

            if not output:
                return "error"

            return DualNormalizationHub.normalize(output, 200)

        if isinstance(output, str):
            if not output.strip():
                return "error"
            return DualNormalizationHub.normalize_text(output)

        return DualNormalizationHub.normalize_text(str(output))

    @staticmethod
    def _is_remote_target(target: str | None) -> bool:
        if not target:
            return False
        target = str(target).lower().strip()
        return target.startswith("http://") or target.startswith("https://")


async def adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility entry point for direct adapter discovery."""
    merged_payload = dict(payload or {})

    if kwargs:
        metadata = dict(merged_payload.get("metadata") or {})
        metadata.update({k: v for k, v in kwargs.items() if k not in {"endpoint"}})
        merged_payload["metadata"] = metadata

    plugin = LangGraphAdapterPlugin()
    return await plugin.execute_langgraph_node(merged_payload, endpoint=endpoint)
