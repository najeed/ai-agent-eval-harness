# eval_runner/adapters/ag2.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import os
from collections.abc import Mapping
from typing import Any

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class AG2AdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native AG2 adapter.

    Execution modes:

    1. Native/local AG2 execution:
       payload.metadata.agent_path (preferred) or payload.metadata.logic_path
       must resolve to an instantiated AG2 Agent or a factory returning one.

    2. Remote AG2 HTTP execution:
       explicit HTTP endpoint or AG2_API_URL.

    No synthetic/simulation success path is provided. A certifiable execution
    must execute a real AG2 agent or a real remote AG2 endpoint.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="ag2")

    def on_discover_adapters(self, registry: Any):
        """Register the AG2 adapter."""
        registry.register("ag2", self.execute_ag2_query)

    async def execute_ag2_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute an AG2 agent turn.

        Supported local metadata:
          metadata.agent_path / metadata.logic_path
              module:attribute resolving to:
                - an AG2 Agent instance
                - a zero-argument factory returning an Agent
                - a factory accepting `payload=...` or `message=...`

        Supported remote execution:
          explicit endpoint argument, payload["url"], or config.AG2_API_URL
          when the resolved value is an HTTP(S) URL.

        The adapter deliberately does not retry native AG2 execution because
        replaying an agent turn can duplicate non-idempotent tool side effects.
        """

        span_context = kwargs.get("span_context") or payload.get("span_context")
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}

        agent_id = str(
            payload.get("agent_id")
            or payload.get("task_id")
            or metadata.get("agent_id")
            or "default_agent"
        )

        message = self._resolve_message(payload)
        url = endpoint or kwargs.get("url") or payload.get("url")

        # Explicit remote endpoint always wins.
        if self._is_http_url(url):
            return await self._execute_remote_api(
                payload=payload,
                url=str(url),
                message=message,
                agent_id=agent_id,
                span_context=span_context,
            )

        # Optional configured remote fallback.
        configured_url = getattr(config, "AG2_API_URL", None)
        if not url and self._is_http_url(configured_url):
            return await self._execute_remote_api(
                payload=payload,
                url=str(configured_url),
                message=message,
                agent_id=agent_id,
                span_context=span_context,
            )

        try:
            ag2 = self._import_ag2()

            agent = await self._resolve_agent(
                payload=payload,
                metadata=metadata,
                ag2=ag2,
            )

            return await self._execute_native_agent(
                agent=agent,
                ag2=ag2,
                message=message,
                agent_id=agent_id,
                span_context=span_context,
                payload=payload,
            )

        except ImportError as exc:
            return self._error(
                message=str(exc),
                agent_id=agent_id,
                mode="native",
                span_context=span_context,
            )
        except TimeoutError:
            timeout = float(getattr(config, "DEFAULT_ADAPTER_TIMEOUT", 30.0))
            return self._error(
                message=f"AG2 execution timed out after {timeout:.1f}s.",
                agent_id=agent_id,
                mode="native",
                span_context=span_context,
            )
        except Exception as exc:
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "message": f"AG2 execution failed: {exc}",
                    "exception_type": type(exc).__name__,
                },
                span_context=span_context,
            )
            return self._error(
                message=f"AG2 execution failed: {exc}",
                agent_id=agent_id,
                mode="native",
                span_context=span_context,
            )

    async def _execute_native_agent(
        self,
        agent: Any,
        ag2: Any,
        message: str,
        agent_id: str,
        span_context: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a real AG2 Agent using the current async Agent.ask API."""

        if agent is None:
            raise ValueError(
                "AG2 agent resolution returned None. "
                "Provide metadata.agent_path pointing to an AG2 Agent or factory."
            )

        ask = getattr(agent, "ask", None)
        if not callable(ask):
            raise TypeError("Resolved AG2 target is not an AG2 Agent: missing callable ask().")

        framework_version = str(getattr(ag2, "__version__", "unknown"))
        agent_name = str(getattr(agent, "name", agent_id))

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "agent_name": agent_name,
                "framework": "ag2",
                "version": framework_version,
                "mode": "native",
                "protocol": "v1",
            },
            span_context=span_context,
        )

        emit(
            CoreEvents.NODE_START,
            {
                "adapter": "ag2",
                "node_id": agent_name,
            },
            span_context=span_context,
        )

        stream = self._build_memory_stream(ag2)
        ask_kwargs = self._build_ask_kwargs(payload, stream)

        timeout = float(getattr(config, "DEFAULT_ADAPTER_TIMEOUT", 30.0))

        try:
            if ask_kwargs:
                reply = await asyncio.wait_for(
                    ask(message, **ask_kwargs),
                    timeout=timeout,
                )
            else:
                reply = await asyncio.wait_for(
                    ask(message),
                    timeout=timeout,
                )

            event_summary = await self._collect_reply_events(
                reply=reply,
                agent_id=agent_id,
                span_context=span_context,
            )

            body = getattr(reply, "body", None)
            parsed_content = await self._extract_reply_content(reply)

            output = body if isinstance(body, str) else self._stringify(parsed_content)

            if not output:
                output = self._stringify(parsed_content)

            if not output:
                raise ValueError("AG2 returned an empty final response.")

            action = DualNormalizationHub.normalize_text(output)

            emit(
                CoreEvents.AGENT_RESPONSE,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "output": output,
                    "action": action,
                },
                span_context=span_context,
            )

            emit(
                CoreEvents.NODE_END,
                {
                    "adapter": "ag2",
                    "node_id": agent_name,
                    "action": action,
                },
                span_context=span_context,
            )

            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "action": action,
                },
                span_context=span_context,
            )

            return {
                "status": "success",
                "output": output,
                "content": parsed_content,
                "action": action,
                "metadata": {
                    "framework": "ag2",
                    "version": framework_version,
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "mode": "native",
                    "protocol": "v1",
                    "reply_type": type(reply).__name__,
                    "event_summary": event_summary,
                    "model": self._resolve_agent_model(agent),
                },
            }

        except Exception:
            emit(
                CoreEvents.NODE_END,
                {
                    "adapter": "ag2",
                    "node_id": agent_name,
                    "action": "error",
                },
                span_context=span_context,
            )
            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "action": "error",
                },
                span_context=span_context,
            )
            raise

    async def _execute_remote_api(
        self,
        payload: dict[str, Any],
        url: str,
        message: str,
        agent_id: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute an AG2-compatible remote HTTP endpoint."""

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "protocol": "v1",
                "mode": "remote",
                "endpoint": url,
            },
            span_context=span_context,
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        api_key = payload.get("api_key") or payload.get("token") or os.getenv("AG2_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        remote_payload = self._build_remote_payload(
            payload=payload,
            message=message,
            agent_id=agent_id,
        )

        async def _call() -> tuple[dict[str, Any], int]:
            session = await SessionManager.get_session()
            async with session.post(
                url,
                json=remote_payload,
                headers=headers,
                timeout=None,
            ) as response:
                status = response.status
                data = await response.json(content_type=None)

                if status >= 400:
                    response.raise_for_status()

                if not isinstance(data, dict):
                    raise TypeError(
                        f"AG2 remote endpoint returned {type(data).__name__}; expected JSON object."
                    )

                return data, status

        try:
            data, status_code = await self.call_with_retry(_call)

            output = self._extract_remote_output(data)
            if not output:
                raise ValueError("AG2 remote endpoint returned no usable output field.")

            action = DualNormalizationHub.normalize(
                data,
                status_code,
            )

            emit(
                CoreEvents.AGENT_RESPONSE,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "action": action,
                    "output": output,
                },
                span_context=span_context,
            )

            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "action": action,
                    "mode": "remote",
                },
                span_context=span_context,
            )

            return {
                "status": "success",
                "output": output,
                "content": data.get("content", output),
                "action": action,
                "metadata": {
                    "framework": "ag2",
                    "mode": "remote",
                    "endpoint": url,
                    "protocol": "v1",
                    "status_code": status_code,
                },
            }

        except Exception as exc:
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "message": f"AG2 remote execution failed: {exc}",
                    "exception_type": type(exc).__name__,
                    "endpoint": url,
                },
                span_context=span_context,
            )
            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "action": "error",
                    "mode": "remote",
                },
                span_context=span_context,
            )
            return self._error(
                message=f"AG2 remote execution failed: {exc}",
                agent_id=agent_id,
                mode="remote",
                endpoint=url,
                span_context=span_context,
            )

    async def _resolve_agent(
        self,
        payload: dict[str, Any],
        metadata: Mapping[str, Any],
        ag2: Any,
    ) -> Any:
        """
        Resolve a real AG2 Agent from an import path or injected object.

        Supported:
          payload["agent"]
          metadata["agent"]
          metadata["agent_path"]
          metadata["logic_path"]  # legacy alias
        """

        direct_agent = payload.get("agent")
        if direct_agent is None:
            direct_agent = metadata.get("agent")

        if direct_agent is not None:
            if self._is_agent_like(direct_agent):
                return direct_agent
            raise TypeError(
                "payload['agent'] / metadata['agent'] was provided but is not "
                "an AG2 Agent (missing ask())."
            )

        agent_path = (
            metadata.get("agent_path") or metadata.get("logic_path") or payload.get("agent_path")
        )

        if not agent_path:
            raise ValueError(
                "No AG2 agent target configured. "
                "Set metadata.agent_path to module:attribute, where the attribute "
                "is an AG2 Agent or a factory returning one."
            )

        target = self._load_symbol(str(agent_path))

        if self._is_agent_like(target):
            return target

        if not callable(target):
            raise TypeError(
                f"AG2 target '{agent_path}' is neither an Agent nor a callable factory."
            )

        target = await self._invoke_agent_factory(
            factory=target,
            payload=payload,
            message=self._resolve_message(payload),
        )

        if not self._is_agent_like(target):
            raise TypeError(f"AG2 factory '{agent_path}' did not return an object exposing ask().")

        return target

    @staticmethod
    def _load_symbol(path: str) -> Any:
        if ":" not in path:
            raise ValueError(f"Invalid AG2 agent path '{path}'. Expected 'module:attribute'.")

        module_name, attr_name = path.split(":", 1)
        if not module_name or not attr_name:
            raise ValueError(f"Invalid AG2 agent path '{path}'. Expected 'module:attribute'.")

        module = importlib.import_module(module_name)
        try:
            return getattr(module, attr_name)
        except AttributeError as exc:
            raise AttributeError(f"AG2 target '{path}' does not exist.") from exc

    @staticmethod
    async def _invoke_agent_factory(
        factory: Any,
        payload: dict[str, Any],
        message: str,
    ) -> Any:
        """
        Invoke a user-supplied AG2 Agent factory without assuming a single signature.
        Supported signatures are intentionally explicit.
        """
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            result = factory()
            return await result if inspect.isawaitable(result) else result

        parameters = signature.parameters

        if "payload" in parameters:
            result = factory(payload=payload)
        elif "message" in parameters:
            result = factory(message=message)
        elif "task" in parameters:
            result = factory(task=message)
        elif any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            result = factory(payload=payload, message=message)
        elif len(parameters) == 0:
            result = factory()
        else:
            raise TypeError(
                "AG2 factory must accept no arguments, or one of `payload`, `message`, or `task`."
            )

        return await result if inspect.isawaitable(result) else result

    @staticmethod
    def _import_ag2() -> Any:
        try:
            return importlib.import_module("ag2")
        except ImportError:
            raise ImportError(
                "AG2 SDK is not installed. Install the AgentV AG2 extra "
                "with `pip install 'agentv[framework-ag2]'`."
            ) from None

    @staticmethod
    def _is_agent_like(value: Any) -> bool:
        return value is not None and callable(getattr(value, "ask", None))

    @staticmethod
    def _resolve_message(payload: dict[str, Any]) -> str:
        """
        Resolve the canonical task/message without losing the AgentV dispatcher payload.
        """
        candidates = (
            payload.get("message"),
            payload.get("task_description"),
            payload.get("task"),
            payload.get("prompt"),
        )

        for candidate in candidates:
            if candidate is None:
                continue
            if isinstance(candidate, str):
                text = candidate.strip()
                if text:
                    return text
            elif isinstance(candidate, Mapping):
                return AG2AdapterPlugin._stringify(candidate)
            else:
                text = str(candidate).strip()
                if text:
                    return text

        raise ValueError("AG2 execution requires a non-empty task/message.")

    @staticmethod
    def _build_memory_stream(ag2: Any) -> Any | None:
        memory_stream_cls = getattr(ag2, "MemoryStream", None)
        if memory_stream_cls is None:
            return None
        try:
            return memory_stream_cls()
        except Exception:
            return None

    @staticmethod
    def _build_ask_kwargs(
        payload: dict[str, Any],
        stream: Any | None,
    ) -> dict[str, Any]:
        """
        Pass only current AG2 Agent.ask parameters that can be safely represented
        by the adapter contract.
        """
        kwargs: dict[str, Any] = {}

        if stream is not None:
            kwargs["stream"] = stream

        response_schema = payload.get("response_schema")
        if response_schema is not None:
            # Only pass already-instantiated/callable schema objects.
            kwargs["response_schema"] = response_schema

        return kwargs

    async def _collect_reply_events(
        self,
        reply: Any,
        agent_id: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Extract AG2's typed event history without depending on individual event
        implementation details.
        """
        events: list[Any] = []

        history = getattr(reply, "history", None)
        get_events = getattr(history, "get_events", None)

        if callable(get_events):
            try:
                events = await get_events()
            except Exception as exc:
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "message": f"AG2 event history unavailable: {exc}",
                    },
                    span_context=span_context,
                )

        summary = {
            "total_events": len(events),
            "model_requests": 0,
            "model_responses": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "hitl_requests": 0,
        }

        for event in events:
            event_name = type(event).__name__.lower()

            if event_name == "modelrequest":
                summary["model_requests"] += 1
                continue

            if event_name == "modelresponse":
                summary["model_responses"] += 1
                continue

            if "toolcall" in event_name:
                summary["tool_calls"] += 1
                emit(
                    CoreEvents.TOOL_CALL,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "tool_name": self._event_value(
                            event,
                            "name",
                            "tool_name",
                            default="unknown",
                        ),
                        "arguments": self._event_value(
                            event,
                            "arguments",
                            "args",
                            default=None,
                        ),
                    },
                    span_context=span_context,
                )
                continue

            if "toolresult" in event_name:
                summary["tool_results"] += 1
                emit(
                    CoreEvents.TOOL_RESULT,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "tool_name": self._event_value(
                            event,
                            "name",
                            "tool_name",
                            default="unknown",
                        ),
                        "result": self._event_value(
                            event,
                            "content",
                            "result",
                            default=None,
                        ),
                    },
                    span_context=span_context,
                )
                continue

            if "humaninputrequest" in event_name:
                summary["hitl_requests"] += 1
                emit(
                    CoreEvents.HITL_PAUSE,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "message": self._event_value(
                            event,
                            "content",
                            "message",
                            default="AG2 requested human input.",
                        ),
                    },
                    span_context=span_context,
                )

        return summary

    @staticmethod
    async def _extract_reply_content(reply: Any) -> Any:
        content = getattr(reply, "content", None)
        if callable(content):
            value = content()
            return await value if inspect.isawaitable(value) else value

        if content is not None:
            return content

        return getattr(reply, "body", None)

    @staticmethod
    def _resolve_agent_model(agent: Any) -> str | None:
        cfg = getattr(agent, "config", None)
        model = getattr(cfg, "model", None)
        if model:
            return str(model)

        if isinstance(cfg, Mapping):
            model = cfg.get("model")
            if model:
                return str(model)

        return None

    @staticmethod
    def _event_value(
        event: Any,
        *names: str,
        default: Any = None,
    ) -> Any:
        for name in names:
            if hasattr(event, name):
                return getattr(event, name)
        return default

    @staticmethod
    def _build_remote_payload(
        payload: dict[str, Any],
        message: str,
        agent_id: str,
    ) -> dict[str, Any]:
        remote = {
            "agent_id": agent_id,
            "message": message,
        }

        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            # Preserve declarative execution metadata but never send an in-process
            # Agent object or non-serializable callback/factory.
            safe_metadata = {}
            for key, value in metadata.items():
                if key in {"agent", "factory", "callback", "callable"}:
                    continue
                if callable(value):
                    continue
                safe_metadata[key] = value
            remote["metadata"] = safe_metadata

        for key in (
            "task_id",
            "session_id",
            "conversation_id",
            "response_schema",
            "input",
        ):
            if key in payload and payload[key] is not None:
                value = payload[key]
                if not callable(value):
                    remote[key] = value

        return remote

    @staticmethod
    def _extract_remote_output(data: Mapping[str, Any]) -> str:
        candidates = (
            data.get("output"),
            data.get("content"),
            data.get("message"),
            data.get("response"),
            data.get("answer"),
            data.get("result"),
        )

        for candidate in candidates:
            if candidate is None:
                continue

            if isinstance(candidate, str):
                text = candidate.strip()
                if text:
                    return text

            if isinstance(candidate, Mapping):
                nested = (
                    candidate.get("content") or candidate.get("text") or candidate.get("output")
                )
                if nested is not None:
                    text = str(nested).strip()
                    if text:
                        return text

            text = str(candidate).strip()
            if text:
                return text

        return ""

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        try:
            import json

            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    @staticmethod
    def _is_http_url(value: Any) -> bool:
        return isinstance(value, str) and value.lower().startswith(("http://", "https://"))

    @staticmethod
    def _error(
        message: str,
        agent_id: str,
        mode: str,
        span_context: dict[str, Any] | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "framework": "ag2",
            "agent_id": agent_id,
            "mode": mode,
            "protocol": "v1",
        }
        if endpoint:
            metadata["endpoint"] = endpoint

        return {
            "status": "error",
            "action": "error",
            "message": message,
            "metadata": metadata,
        }


async def adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility wrapper for direct adapter invocation."""
    plugin = AG2AdapterPlugin()
    return await plugin.execute_ag2_query(
        payload,
        endpoint=endpoint,
        **kwargs,
    )
