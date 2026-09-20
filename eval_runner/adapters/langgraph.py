# eval_runner/adapters/langgraph.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import (
    AESCallbackHandler,
    BaseAdapter,
    DualNormalizationHub,
    bounded_text,
    json_safe,
    validate_http_endpoint,
)

logger = logging.getLogger(__name__)

_MISSING = object()

_ALLOWED_STREAM_MODES = {
    "values",
    "updates",
    "messages",
    "custom",
    "checkpoints",
    "tasks",
    "debug",
}

_ALLOWED_EXECUTION_KWARGS = {
    "context",
    "output_keys",
    "interrupt_before",
    "interrupt_after",
    "durability",
    "subgraphs",
}

_MAX_STREAM_EVENTS = 100
_MAX_STATE_KEYS = 256
_MAX_STATE_TASKS = 128
_MAX_ERROR_LENGTH = 2000


def _load_object(path: str) -> Any:
    """Load module:attribute or module.attribute object."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError(
            "LangGraph graph_path must be a non-empty "
            "'module:attribute' or 'module.attribute' path."
        )

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


async def _resolve_factory(obj: Any, payload: Mapping[str, Any]) -> Any:
    """Resolve a graph factory without swallowing factory execution errors."""
    if hasattr(obj, "ainvoke") and callable(obj.ainvoke):
        return obj

    if not callable(obj):
        raise TypeError(
            "Resolved LangGraph object is not executable and is not callable. "
            "Expected an object exposing 'ainvoke' or a callable factory."
        )

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise TypeError("LangGraph adapter metadata must be an object.")

    factory_kwargs = metadata.get("graph_factory_kwargs") or {}
    if not isinstance(factory_kwargs, Mapping):
        raise TypeError("metadata.graph_factory_kwargs must be an object.")

    # Do not catch TypeError from inside the factory. A genuine factory bug
    # must remain observable instead of being mistaken for a zero-arg factory.
    resolved = obj(**dict(factory_kwargs))

    if inspect.isawaitable(resolved):
        resolved = await resolved

    if not hasattr(resolved, "ainvoke") or not callable(resolved.ainvoke):
        raise TypeError(
            "Resolved LangGraph factory did not return an object exposing "
            "the required async 'ainvoke' API."
        )

    return resolved


def _extract_interrupts(value: Any) -> list[dict[str, Any]]:
    """Extract LangGraph interrupt payloads without copying arbitrary state."""
    interrupts: list[dict[str, Any]] = []

    if value is None:
        return interrupts

    if isinstance(value, Mapping):
        raw = value.get("__interrupt__")
        if raw is not None:
            items = raw if isinstance(raw, (list, tuple)) else [raw]
            for item in items:
                normalized = json_safe(item)
                if normalized not in interrupts:
                    interrupts.append(normalized)

        direct = value.get("interrupts")
        if direct is not None:
            items = direct if isinstance(direct, (list, tuple)) else [direct]
            for item in items:
                normalized = json_safe(item)
                if normalized not in interrupts:
                    interrupts.append(normalized)

        nested_type = value.get("type")
        if nested_type == "values":
            interrupts.extend(_extract_interrupts(value.get("data")))

        return interrupts

    raw_interrupts = getattr(value, "interrupts", None)
    if raw_interrupts:
        items = raw_interrupts if isinstance(raw_interrupts, (list, tuple)) else [raw_interrupts]
        for item in items:
            normalized = json_safe(item)
            if normalized not in interrupts:
                interrupts.append(normalized)

    raw_value = getattr(value, "value", None)
    if raw_value is not None and raw_value is not value:
        interrupts.extend(_extract_interrupts(raw_value))

    raw_data = getattr(value, "data", None)
    if raw_data is not None and raw_data is not value:
        interrupts.extend(_extract_interrupts(raw_data))

    return interrupts


def _unwrap_graph_output(value: Any) -> Any:
    """Unwrap LangGraph GraphOutput while preserving ordinary graph outputs."""
    if value is None:
        return None

    if isinstance(value, Mapping):
        return value

    for attr in ("value", "output", "result"):
        if hasattr(value, attr):
            try:
                candidate = getattr(value, attr)
            except Exception:
                continue

            if candidate is not None:
                return candidate

    return value


def _extract_stream_part(chunk: Any) -> tuple[str | None, Any]:
    """
    Normalize LangGraph v2 StreamPart objects and legacy dict/tuple forms.

    Current LangGraph v2 streaming yields typed stream-part objects. Older
    integrations may still surface dicts or tuples.
    """
    if isinstance(chunk, Mapping):
        chunk_type = chunk.get("type")
        if chunk_type is not None:
            return str(chunk_type), chunk.get("data")

        if len(chunk) == 1:
            key, value = next(iter(chunk.items()))
            return str(key), value

        return None, chunk

    chunk_type = getattr(chunk, "type", None)
    if chunk_type is not None:
        return str(chunk_type), getattr(chunk, "data", None)

    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        return chunk[0], chunk[1]

    return None, chunk


def _stream_chunk_summary(
    chunk_type: str | None,
    chunk: Any,
    sequence: int,
) -> dict[str, Any]:
    """Produce bounded telemetry without persisting streamed payloads."""
    summary: dict[str, Any] = {
        "sequence": sequence,
        "type": chunk_type or type(chunk).__name__,
    }

    if isinstance(chunk, Mapping):
        if "name" in chunk:
            summary["name"] = bounded_text(str(chunk["name"]), 256)
        if "node" in chunk:
            summary["node"] = bounded_text(str(chunk["node"]), 256)

    if hasattr(chunk, "id"):
        try:
            summary["id"] = bounded_text(str(chunk.id), 256)
        except Exception:
            pass

    return summary


def _summarize_state_field(value: Any) -> dict[str, Any]:
    """Bound state inspection to structural metadata, not arbitrary payloads."""
    summary: dict[str, Any] = {
        "type": type(value).__name__,
    }

    if isinstance(value, Mapping):
        keys = list(value.keys())
        summary["kind"] = "mapping"
        summary["size"] = len(keys)
        summary["keys"] = [bounded_text(str(key), 256) for key in keys[:_MAX_STATE_KEYS]]
        summary["keys_truncated"] = len(keys) > _MAX_STATE_KEYS
        return summary

    if isinstance(value, (list, tuple, set, frozenset)):
        summary["kind"] = "sequence"
        summary["size"] = len(value)
        return summary

    if isinstance(value, str):
        summary["kind"] = "string"
        summary["length"] = len(value)
        return summary

    if isinstance(value, bytes):
        summary["kind"] = "bytes"
        summary["length"] = len(value)
        return summary

    return summary


def _summarize_snapshot(snapshot: Any) -> dict[str, Any]:
    """
    Capture checkpoint metadata without copying arbitrary graph/application
    state into AgentV evidence.
    """
    state: dict[str, Any] = {
        "type": type(snapshot).__name__,
    }

    for attr in ("created_at", "next", "parent_config"):
        if hasattr(snapshot, attr):
            try:
                state[attr] = json_safe(getattr(snapshot, attr))
            except Exception:
                logger.debug(
                    "Failed to serialize LangGraph snapshot field '%s'.",
                    attr,
                    exc_info=True,
                )

    if hasattr(snapshot, "tasks"):
        try:
            tasks = snapshot.tasks or ()
            task_list = list(tasks)
            state["tasks"] = {
                "count": len(task_list),
                "items": [json_safe(task) for task in task_list[:_MAX_STATE_TASKS]],
                "truncated": len(task_list) > _MAX_STATE_TASKS,
            }
        except Exception:
            logger.debug(
                "Failed to serialize LangGraph snapshot tasks.",
                exc_info=True,
            )

    if hasattr(snapshot, "metadata"):
        try:
            state["metadata"] = json_safe(snapshot.metadata)
        except Exception:
            logger.debug(
                "Failed to serialize LangGraph snapshot metadata.",
                exc_info=True,
            )

    if hasattr(snapshot, "config"):
        try:
            config = snapshot.config
            state["config"] = json_safe(config)
        except Exception:
            logger.debug(
                "Failed to serialize LangGraph snapshot config.",
                exc_info=True,
            )

    if hasattr(snapshot, "values"):
        try:
            values = snapshot.values
            state["values_summary"] = _summarize_state_field(values)
        except Exception:
            logger.debug(
                "Failed to summarize LangGraph snapshot values.",
                exc_info=True,
            )

    return state


class _LangGraphTelemetryHandler(AESCallbackHandler):
    """LangGraph callback bridge into AgentV's event bus."""

    def __init__(
        self,
        adapter_name: str,
        identifier: str,
        span_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            adapter_name=adapter_name,
            identifier=identifier,
        )
        self.span_context = span_context

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        emit(
            event,
            data,
            span_context=self.span_context,
        )

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: Any,
        **kwargs: Any,
    ) -> None:
        try:
            super().on_chain_start(serialized, inputs, **kwargs)
        except Exception:
            logger.debug("LangGraph chain-start telemetry failed.", exc_info=True)

    def on_chain_end(
        self,
        outputs: Any,
        **kwargs: Any,
    ) -> None:
        try:
            super().on_chain_end(outputs, **kwargs)
        except Exception:
            logger.debug("LangGraph chain-end telemetry failed.", exc_info=True)

    def on_chain_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ERROR,
            {
                "adapter": "langgraph",
                "error_type": type(error).__name__,
                "message": bounded_text(str(error), _MAX_ERROR_LENGTH),
            },
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        tool_name = None
        if isinstance(serialized, Mapping):
            tool_name = serialized.get("name")

        self._emit(
            CoreEvents.TOOL_CALL,
            {
                "adapter": "langgraph",
                "tool_name": bounded_text(
                    str(tool_name or "unknown"),
                    256,
                ),
                "input_type": type(input_str).__name__,
            },
        )

    def on_tool_end(
        self,
        output: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.TOOL_RESULT,
            {
                "adapter": "langgraph",
                "output_type": type(output).__name__,
            },
        )

    def on_node_start(
        self,
        serialized: dict[str, Any],
        inputs: Any,
        **kwargs: Any,
    ) -> None:
        node_name = None
        if isinstance(serialized, Mapping):
            node_name = serialized.get("name") or serialized.get("id")

        self._emit(
            CoreEvents.ADAPTER_DEBUG,
            {
                "adapter": "langgraph",
                "event": "node_start",
                "node": bounded_text(
                    str(node_name or "unknown"),
                    256,
                ),
            },
        )

    def on_node_end(
        self,
        outputs: Any,
        **kwargs: Any,
    ) -> None:
        self._emit(
            CoreEvents.ADAPTER_DEBUG,
            {
                "adapter": "langgraph",
                "event": "node_end",
                "output_type": type(outputs).__name__,
            },
        )


class LangGraphAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production LangGraph adapter.

    Supports:
      * Local compiled LangGraph applications via graph_path.
      * LangGraph Server deployments via RemoteGraph.
      * Async graph execution through ainvoke/astream.
      * LangGraph v2 typed stream parts.
      * Resumable interrupts via Command(resume=...).
      * Explicit thread/checkpoint-aware execution.
      * Callback telemetry through RunnableConfig.
      * Bounded stream and state evidence.
      * Fail-closed graph resolution and input validation.
    """

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="langgraph")

    def on_discover_adapters(self, registry: Any) -> None:
        registry.register("langgraph", self.execute_langgraph_node)
        registry.register("langgraph:v2", self.execute_langgraph_node)

    async def execute_langgraph_node(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Execute a real LangGraph application and return an AgentV result."""
        if not isinstance(payload, dict):
            raise TypeError("LangGraph adapter payload must be an object.")

        metadata = payload.get("metadata") or {}
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

            version = str(getattr(langgraph, "__version__", "unknown"))

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

            self._attach_callback(
                runnable_config,
                telemetry,
            )

            command_input = self._build_command_input(
                payload,
                graph_input,
            )

            stream_enabled = self._resolve_bool(
                payload.get(
                    "stream",
                    metadata.get("stream", False),
                )
            ) or bool(
                payload.get(
                    "stream_mode",
                    metadata.get("stream_mode"),
                )
            )

            if stream_enabled:
                result, stream_summary = await self._execute_stream(
                    graph=graph,
                    graph_input=command_input,
                    runnable_config=runnable_config,
                    payload=payload,
                    metadata=metadata,
                    telemetry=telemetry,
                )
            else:
                result, stream_summary = await self._execute_invoke(
                    graph=graph,
                    graph_input=command_input,
                    runnable_config=runnable_config,
                    payload=payload,
                    metadata=metadata,
                )

            interrupt_data = _extract_interrupts(result)

            capture_state = self._resolve_bool(
                payload.get(
                    "capture_state",
                    metadata.get("capture_state", True),
                )
            )

            capture_state_values = self._resolve_bool(
                payload.get(
                    "capture_state_values",
                    metadata.get("capture_state_values", False),
                )
            )

            state_snapshot = await self._read_state(
                graph,
                runnable_config,
                enabled=capture_state,
                include_values=capture_state_values,
            )

            output = _unwrap_graph_output(result)

            if interrupt_data:
                action = "hitl_pause"
                status = "hitl_pause"
            else:
                action = self._normalize_output(output)
                status = "error" if action == "error" else "success"

            configurable = runnable_config.get("configurable")
            thread_id = configurable.get("thread_id") if isinstance(configurable, Mapping) else None

            result_metadata = {
                "framework": "langgraph",
                "version": version,
                "adapter_version": "v3",
                "protocol": "langgraph",
                "mode": ("remote" if self._is_remote_target(execution_target) else "local"),
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
                "thread_id": thread_id,
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
            return self._error_result(
                node_id=node_id,
                message=(
                    "LangGraph dependency is not installed. "
                    "Install the AgentV LangGraph framework extra."
                ),
                error=exc,
                span_context=span_context,
            )

        except Exception as exc:
            return self._error_result(
                node_id=node_id,
                message=f"LangGraph execution failed: {exc}",
                error=exc,
                span_context=span_context,
            )

    async def _resolve_execution_target(
        self,
        execution_target: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Any:
        """Resolve a local graph object or LangGraph RemoteGraph."""
        if execution_target is None:
            raise ValueError(
                "No LangGraph execution target supplied. "
                "Provide graph_path for a local graph or an HTTP endpoint "
                "for a LangGraph Server deployment."
            )

        target = str(execution_target).strip()

        if self._is_remote_target(target):
            return self._create_remote_graph(
                endpoint=target,
                payload=payload,
                metadata=metadata,
            )

        graph_obj = _load_object(target)
        return await _resolve_factory(
            graph_obj,
            {
                **payload,
                "metadata": metadata,
            },
        )

    @staticmethod
    def _create_remote_graph(
        endpoint: str,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> Any:
        """Create a first-party LangGraph RemoteGraph client."""
        validate_http_endpoint(endpoint)

        try:
            from langgraph.pregel.remote import RemoteGraph
        except ImportError as exc:
            raise ImportError(
                "LangGraph RemoteGraph support is unavailable in the installed LangGraph package."
            ) from exc

        assistant_id = (
            payload.get("assistant_id")
            or payload.get("graph_id")
            or payload.get("agent_id")
            or metadata.get("assistant_id")
            or metadata.get("graph_id")
            or metadata.get("graph_name")
        )

        if not assistant_id:
            raise ValueError(
                "Remote LangGraph execution requires an assistant_id, graph_id, or graph_name."
            )

        api_key = (
            payload.get("api_key") or metadata.get("api_key") or metadata.get("langgraph_api_key")
        )

        headers = metadata.get("headers") or payload.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise TypeError("LangGraph headers must be an object.")

        normalized_headers = {str(key): str(value) for key, value in headers.items()}

        distributed_tracing = LangGraphAdapterPlugin._resolve_bool(
            payload.get(
                "distributed_tracing",
                metadata.get("distributed_tracing", False),
            )
        )

        return RemoteGraph(
            str(assistant_id),
            url=endpoint,
            api_key=str(api_key) if api_key is not None else None,
            headers=normalized_headers,
            name=str(metadata.get("graph_name") or assistant_id),
            distributed_tracing=distributed_tracing,
        )

    @staticmethod
    def _resolve_input(payload: Mapping[str, Any]) -> Any:
        """
        Resolve an explicit graph input.

        The adapter never invents a graph schema. An explicit input payload
        takes precedence over convenience message/task fields.
        """
        if "input" in payload:
            return payload["input"]

        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise TypeError("LangGraph adapter metadata must be an object.")

        if "input" in metadata:
            return metadata["input"]

        if "input_payload" in payload:
            return payload["input_payload"]

        if "input_payload" in metadata:
            return metadata["input_payload"]

        input_key = payload.get("input_key") or metadata.get("input_key")

        if input_key:
            if not isinstance(input_key, str) or not input_key.strip():
                raise ValueError("LangGraph input_key must be a non-empty string.")

            message = payload.get(
                "task_description",
                payload.get("message"),
            )

            if message is None:
                raise ValueError(
                    "LangGraph input_key was supplied but no task_description "
                    "or message is available."
                )

            return {
                input_key: message,
            }

        if "messages" in payload:
            return {
                "messages": payload["messages"],
            }

        if "messages" in metadata:
            return {
                "messages": metadata["messages"],
            }

        if "task_description" in payload:
            return {
                "task_description": payload["task_description"],
            }

        if "message" in payload:
            return {
                "message": payload["message"],
            }

        raise ValueError(
            "LangGraph adapter requires an explicit input, input_payload, "
            "messages, task_description, message, or input_key."
        )

    @staticmethod
    def _build_runnable_config(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        node_id: str,
    ) -> dict[str, Any]:
        """Build RunnableConfig while preserving caller-supplied config."""
        user_config = payload.get("config")

        if user_config is None:
            user_config = metadata.get("config") or {}

        if not isinstance(user_config, Mapping):
            raise TypeError("LangGraph config must be an object.")

        config_data: dict[str, Any] = dict(user_config)

        configurable = config_data.get("configurable") or {}
        if not isinstance(configurable, Mapping):
            raise TypeError("LangGraph config.configurable must be an object.")

        configurable_data = dict(configurable)

        thread_id = payload.get("thread_id") or metadata.get("thread_id")

        if thread_id is not None:
            configurable_data["thread_id"] = str(thread_id)

        config_data["configurable"] = configurable_data

        run_id = payload.get("run_id") or metadata.get("run_id")

        if run_id is not None:
            config_data["run_id"] = str(run_id)

        tags = config_data.get("tags")
        if tags is None:
            tags = []
        elif isinstance(tags, str):
            tags = [tags]
        elif isinstance(tags, Sequence):
            tags = list(tags)
        else:
            tags = [str(tags)]

        for tag in ("agentv", "adapter:langgraph"):
            if tag not in tags:
                tags.append(tag)

        config_data["tags"] = tags

        lc_metadata = config_data.get("metadata")
        if lc_metadata is None:
            lc_metadata = {}
        if not isinstance(lc_metadata, Mapping):
            raise TypeError("LangGraph config.metadata must be an object.")

        lc_metadata_data = dict(lc_metadata)
        lc_metadata_data.update(
            {
                "agentv_adapter": "langgraph",
                "agentv_adapter_version": "v3",
                "agentv_node_id": node_id,
            }
        )
        config_data["metadata"] = lc_metadata_data

        return config_data

    @staticmethod
    def _attach_callback(
        runnable_config: dict[str, Any],
        telemetry: _LangGraphTelemetryHandler,
    ) -> None:
        """Append AgentV telemetry without replacing caller callbacks."""
        callbacks = runnable_config.get("callbacks")

        if callbacks is None:
            runnable_config["callbacks"] = [telemetry]
            return

        if isinstance(callbacks, list):
            if telemetry not in callbacks:
                runnable_config["callbacks"] = [
                    *callbacks,
                    telemetry,
                ]
            return

        if isinstance(callbacks, tuple):
            runnable_config["callbacks"] = [
                *callbacks,
                telemetry,
            ]
            return

        runnable_config["callbacks"] = [
            callbacks,
            telemetry,
        ]

    @staticmethod
    def _build_command_input(
        payload: Mapping[str, Any],
        graph_input: Any,
    ) -> Any:
        """Convert an explicit resume request into a LangGraph Command."""
        resume = payload.get("resume", _MISSING)

        if resume is _MISSING:
            metadata = payload.get("metadata") or {}
            if isinstance(metadata, Mapping):
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
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Execute graph.ainvoke using only supported execution controls."""
        kwargs = self._execution_kwargs(
            payload=payload,
            metadata=metadata,
        )

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
            config=runnable_config,
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
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        telemetry: _LangGraphTelemetryHandler,
    ) -> tuple[Any, dict[str, Any]]:
        """Execute LangGraph astream and capture bounded stream telemetry."""
        if not hasattr(graph, "astream") or not callable(graph.astream):
            raise TypeError(
                "Resolved LangGraph object does not expose the required async 'astream' API."
            )

        stream_mode = payload.get("stream_mode") or metadata.get("stream_mode") or "values"

        if isinstance(stream_mode, str):
            if stream_mode not in _ALLOWED_STREAM_MODES:
                raise ValueError(
                    f"Unsupported LangGraph stream_mode '{stream_mode}'. "
                    f"Supported modes: {sorted(_ALLOWED_STREAM_MODES)}"
                )
        elif isinstance(stream_mode, (list, tuple)):
            stream_mode = list(stream_mode)
            invalid = [mode for mode in stream_mode if mode not in _ALLOWED_STREAM_MODES]
            if invalid:
                raise ValueError(f"Unsupported LangGraph stream modes: {invalid}")
        else:
            raise TypeError("LangGraph stream_mode must be a string or list of strings.")

        stream_version = str(
            payload.get("stream_version") or metadata.get("stream_version") or "v2"
        )

        if stream_version not in {"v1", "v2"}:
            raise ValueError("LangGraph stream_version must be 'v1' or 'v2'.")

        kwargs = self._execution_kwargs(
            payload=payload,
            metadata=metadata,
        )
        kwargs["stream_mode"] = stream_mode
        kwargs["version"] = stream_version

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "langgraph",
                "operation": "astream",
                "stream_mode": stream_mode,
                "stream_version": stream_version,
            },
            span_context=payload.get("span_context"),
        )

        final_output: Any = None
        last_message: Any = None
        event_count = 0
        node_update_count = 0
        interrupt_events: list[dict[str, Any]] = []
        samples: list[dict[str, Any]] = []

        async for chunk in graph.astream(
            graph_input,
            config=runnable_config,
            **kwargs,
        ):
            event_count += 1

            chunk_type, chunk_data = _extract_stream_part(chunk)

            chunk_interrupts = _extract_interrupts(chunk)
            for interrupt in chunk_interrupts:
                if interrupt not in interrupt_events:
                    interrupt_events.append(interrupt)

            if chunk_type == "values":
                final_output = chunk_data

            elif chunk_type == "updates":
                node_update_count += 1
                if final_output is None:
                    final_output = chunk_data

            elif chunk_type == "messages":
                last_message = chunk_data
                if final_output is None:
                    final_output = chunk_data

            elif chunk_type in {
                "checkpoints",
                "tasks",
                "debug",
                "custom",
            }:
                node_update_count += 1
                if final_output is None:
                    final_output = chunk_data

            else:
                final_output = chunk_data

            if len(samples) < _MAX_STREAM_EVENTS:
                sample = _stream_chunk_summary(
                    chunk_type,
                    chunk,
                    event_count,
                )
                samples.append(sample)

                telemetry._emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "langgraph",
                        "event": "stream_chunk",
                        **sample,
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

        if interrupt_events and final_output is None:
            final_output = {
                "__interrupt__": interrupt_events,
            }

        return final_output, {
            "enabled": True,
            "mode": "astream",
            "stream_mode": stream_mode,
            "stream_version": stream_version,
            "events": event_count,
            "node_updates": node_update_count,
            "interrupt_events": interrupt_events,
            "sampled_events": samples,
            "sampled_events_truncated": event_count > _MAX_STREAM_EVENTS,
            "last_message_type": (
                type(last_message).__name__ if last_message is not None else None
            ),
        }

    @staticmethod
    def _execution_kwargs(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Resolve explicit LangGraph execution controls.

        Only known LangGraph execution arguments are forwarded. This prevents
        arbitrary metadata from becoming unsupported Python keyword arguments.
        """
        controls = payload.get("execution") or metadata.get("execution") or {}

        if not isinstance(controls, Mapping):
            raise TypeError("LangGraph execution controls must be an object.")

        source = dict(controls)

        for key in _ALLOWED_EXECUTION_KWARGS:
            if key in payload:
                source[key] = payload[key]
            elif key in metadata:
                source[key] = metadata[key]

        kwargs: dict[str, Any] = {}

        for key in _ALLOWED_EXECUTION_KWARGS:
            if key in source:
                kwargs[key] = source[key]

        return kwargs

    async def _read_state(
        self,
        graph: Any,
        runnable_config: Mapping[str, Any],
        *,
        enabled: bool,
        include_values: bool,
    ) -> dict[str, Any] | None:
        """
        Inspect authoritative checkpoint state when a thread is explicitly
        bound. Full state values remain opt-in to avoid unbounded evidence.
        """
        if not enabled:
            return None

        configurable = runnable_config.get("configurable")
        if not isinstance(configurable, Mapping):
            return None

        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None

        if not hasattr(graph, "aget_state") or not callable(graph.aget_state):
            return None

        try:
            snapshot = await graph.aget_state(
                dict(runnable_config),
            )

            if snapshot is None:
                return None

            state = _summarize_snapshot(snapshot)

            if include_values and hasattr(snapshot, "values"):
                try:
                    state["values"] = json_safe(snapshot.values)
                except Exception as exc:
                    state["values_error"] = {
                        "type": type(exc).__name__,
                        "message": bounded_text(
                            str(exc),
                            _MAX_ERROR_LENGTH,
                        ),
                    }

            return state

        except Exception as exc:
            logger.debug(
                "LangGraph state inspection failed: %s",
                exc,
                exc_info=True,
            )
            return {
                "error": bounded_text(
                    str(exc),
                    _MAX_ERROR_LENGTH,
                ),
                "error_type": type(exc).__name__,
            }

    @staticmethod
    def _normalize_output(output: Any) -> str:
        """Normalize graph output into an AgentV action."""
        output = _unwrap_graph_output(output)

        if output is None:
            return "error"

        if isinstance(output, Mapping):
            if "__interrupt__" in output:
                return "hitl_pause"

            explicit_action = output.get("action")
            if explicit_action in {
                "call_tool",
                "call_multiple_tools",
                "hitl_pause",
                "final_answer",
                "completed",
                "processing",
                "error",
            }:
                return str(explicit_action)

            if output.get("tool_calls"):
                tool_calls = output["tool_calls"]
                if isinstance(tool_calls, Sequence) and not isinstance(
                    tool_calls,
                    (str, bytes),
                ):
                    return "call_multiple_tools" if len(tool_calls) > 1 else "call_tool"
                return "call_tool"

            messages = output.get("messages")
            if isinstance(messages, Sequence) and not isinstance(
                messages,
                (str, bytes),
            ):
                for message in reversed(messages):
                    message_action = LangGraphAdapterPlugin._normalize_message(message)
                    if message_action is not None:
                        return message_action

            if not output:
                return "error"

            return DualNormalizationHub.normalize(
                dict(output),
                200,
            )

        if isinstance(output, Sequence) and not isinstance(
            output,
            (str, bytes),
        ):
            for item in reversed(output):
                message_action = LangGraphAdapterPlugin._normalize_message(item)
                if message_action is not None:
                    return message_action

            if len(output) == 0:
                return "error"

        if isinstance(output, str):
            if not output.strip():
                return "error"
            return DualNormalizationHub.normalize_text(output)

        return DualNormalizationHub.normalize_text(str(output))

    @staticmethod
    def _normalize_message(message: Any) -> str | None:
        """Recognize tool calls/actions in common LangGraph message shapes."""
        if message is None:
            return None

        if isinstance(message, Mapping):
            explicit_action = message.get("action")
            if explicit_action:
                return str(explicit_action)

            tool_calls = message.get("tool_calls")
            if tool_calls:
                try:
                    return "call_multiple_tools" if len(tool_calls) > 1 else "call_tool"
                except TypeError:
                    return "call_tool"

            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return DualNormalizationHub.normalize_text(content)

            return None

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            try:
                return "call_multiple_tools" if len(tool_calls) > 1 else "call_tool"
            except TypeError:
                return "call_tool"

        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return DualNormalizationHub.normalize_text(content)

        return None

    @staticmethod
    def _error_result(
        *,
        node_id: str,
        message: str,
        error: BaseException,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Emit bounded error telemetry and return a normalized error result."""
        safe_message = bounded_text(
            message,
            _MAX_ERROR_LENGTH,
        )

        emit(
            CoreEvents.ERROR,
            {
                "adapter": "langgraph",
                "node_id": node_id,
                "error_type": type(error).__name__,
                "message": safe_message,
            },
            span_context=span_context,
        )

        return {
            "status": "error",
            "action": "error",
            "message": safe_message,
            "metadata": {
                "framework": "langgraph",
                "mode": "failed",
                "error_type": type(error).__name__,
            },
        }

    @staticmethod
    def _resolve_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

        return bool(value)

    @staticmethod
    def _is_remote_target(target: str | None) -> bool:
        if not target:
            return False

        normalized = str(target).strip().lower()
        return normalized.startswith(("http://", "https://"))


async def adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility entry point for direct adapter discovery."""
    merged_payload = dict(payload or {})

    if kwargs:
        metadata = dict(merged_payload.get("metadata") or {})
        metadata.update({key: value for key, value in kwargs.items() if key != "endpoint"})
        merged_payload["metadata"] = metadata

    plugin = LangGraphAdapterPlugin()
    return await plugin.execute_langgraph_node(
        merged_payload,
        endpoint=endpoint,
    )
