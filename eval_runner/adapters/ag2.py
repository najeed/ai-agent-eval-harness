# eval_runner/adapters/ag2.py
from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)


@dataclass
class _ConversationState:
    """Lifecycle-scoped AG2 conversation state."""

    agent: Any
    reply: Any | None = None
    event_cursor: int = 0
    mode: str = "native"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AG2AdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production AG2 adapter.

    Supported execution modes:

    1. Native/local AG2 execution
       metadata.agent_path / metadata.logic_path resolves to:
         - an AG2 Agent instance
         - a zero-argument factory
         - a factory accepting payload=, message=, or task=

       Conversation continuity is preserved through AgentReply.ask(...).

    2. Remote AG2 A2A execution
       endpoint / payload["url"] / AG2_A2A_URL / AG2_API_URL is treated
       as an A2A Agent Card base URL and is executed through AG2's native
       A2AConfig client.

    There is deliberately no generic "AG2-compatible HTTP" protocol.
    A remote endpoint must implement the AG2-supported A2A contract.
    """

    _DEFAULT_TIMEOUT = 30.0
    _DEFAULT_A2A_TIMEOUT = 60.0

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="ag2")

        # Conversation state is intentionally instance-scoped. The adapter
        # instance is lifecycle-scoped by the adapter registry, avoiding
        # process-global conversation leakage across evaluations.
        self._conversations: dict[str, _ConversationState] = {}

    def on_discover_adapters(self, registry: Any) -> None:
        registry.register("ag2", self.execute_ag2_query)

    async def execute_ag2_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute one AG2 turn.

        The adapter accepts both the normalized task fields emitted by the
        current runtime and richer adapter-native fields when supplied by
        future runtime dispatch.
        """
        effective_payload = self._merge_runtime_context(payload, kwargs)

        metadata = effective_payload.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}

        span_context = (
            kwargs.get("span_context")
            or effective_payload.get("span_context")
            or getattr(kwargs.get("turn_ctx"), "span_context", None)
        )

        agent_id = self._resolve_agent_id(effective_payload, metadata)
        message = self._resolve_message(effective_payload, kwargs)
        url = (
            endpoint
            or kwargs.get("url")
            or effective_payload.get("url")
            or effective_payload.get("endpoint")
        )

        conversation_key = self._conversation_key(
            payload=effective_payload,
            metadata=metadata,
            agent_id=agent_id,
            endpoint=url,
        )

        if self._truthy(effective_payload.get("reset_conversation")):
            self._conversations.pop(conversation_key, None)

        if self._is_http_url(url):
            return await self._execute_remote_a2a(
                payload=effective_payload,
                metadata=metadata,
                url=str(url),
                message=message,
                agent_id=agent_id,
                conversation_key=conversation_key,
                span_context=span_context,
            )

        configured_url = (
            getattr(config, "AG2_A2A_URL", None)
            or getattr(config, "AG2_API_URL", None)
            or os.getenv("AG2_A2A_URL")
            or os.getenv("AG2_API_URL")
        )

        if self._is_http_url(configured_url):
            configured_key = self._conversation_key(
                payload=effective_payload,
                metadata=metadata,
                agent_id=agent_id,
                endpoint=str(configured_url),
            )

            return await self._execute_remote_a2a(
                payload=effective_payload,
                metadata=metadata,
                url=str(configured_url),
                message=message,
                agent_id=agent_id,
                conversation_key=configured_key,
                span_context=span_context,
            )

        return await self._execute_native(
            payload=effective_payload,
            metadata=metadata,
            message=message,
            agent_id=agent_id,
            conversation_key=conversation_key,
            span_context=span_context,
        )

    async def _execute_native(
        self,
        payload: dict[str, Any],
        metadata: Mapping[str, Any],
        message: str,
        agent_id: str,
        conversation_key: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            ag2 = self._import_ag2()

            state = self._conversations.get(conversation_key)

            if state is None:
                agent = await self._resolve_agent(
                    payload=payload,
                    metadata=metadata,
                )

                if agent is None:
                    raise ValueError(
                        "AG2 agent resolution returned None. "
                        "Set metadata.agent_path to an AG2 Agent or factory."
                    )

                state = _ConversationState(
                    agent=agent,
                    mode="native",
                )
                self._conversations[conversation_key] = state

            if not self._is_agent_like(state.agent):
                raise TypeError("Resolved AG2 target is not an AG2 Agent: missing callable ask().")

            async with state.lock:
                return await self._execute_native_turn(
                    state=state,
                    ag2=ag2,
                    payload=payload,
                    message=message,
                    agent_id=agent_id,
                    conversation_key=conversation_key,
                    span_context=span_context,
                )

        except ImportError as exc:
            return self._error(
                message=str(exc),
                agent_id=agent_id,
                mode="native",
                span_context=span_context,
            )
        except TimeoutError:
            timeout = self._adapter_timeout()
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

    async def _execute_native_turn(
        self,
        state: _ConversationState,
        ag2: Any,
        payload: dict[str, Any],
        message: str,
        agent_id: str,
        conversation_key: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        agent = state.agent

        framework_version = str(getattr(ag2, "__version__", "unknown"))
        agent_name = str(getattr(agent, "name", agent_id))
        timeout = self._adapter_timeout()

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "agent_name": agent_name,
                "framework": "ag2",
                "version": framework_version,
                "mode": "native",
                "protocol": "ag2-native",
                "conversation_id": conversation_key,
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

        try:
            previous_reply = state.reply

            if previous_reply is not None:
                history_length_before = await self._history_length(previous_reply)
                state.event_cursor = history_length_before

                ask_kwargs = self._build_reply_ask_kwargs(payload)

                if ask_kwargs:
                    reply = await asyncio.wait_for(
                        previous_reply.ask(message, **ask_kwargs),
                        timeout=timeout,
                    )
                else:
                    reply = await asyncio.wait_for(
                        previous_reply.ask(message),
                        timeout=timeout,
                    )
            else:
                stream = self._build_observer_stream(ag2)

                ask_kwargs = self._build_initial_ask_kwargs(
                    payload=payload,
                    stream=stream,
                )

                if ask_kwargs:
                    reply = await asyncio.wait_for(
                        agent.ask(message, **ask_kwargs),
                        timeout=timeout,
                    )
                else:
                    reply = await asyncio.wait_for(
                        agent.ask(message),
                        timeout=timeout,
                    )

                state.event_cursor = 0

            state.reply = reply

            event_summary = await self._collect_reply_events(
                reply=reply,
                start_index=state.event_cursor,
                agent_id=agent_id,
                span_context=span_context,
            )

            state.event_cursor = await self._history_length(reply)

            body = getattr(reply, "body", None)
            parsed_content = await self._extract_reply_content(reply)

            output = (
                body.strip()
                if isinstance(body, str) and body.strip()
                else self._stringify(parsed_content).strip()
            )

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
                    "protocol": "ag2-native",
                    "reply_type": type(reply).__name__,
                    "event_summary": event_summary,
                    "model": self._resolve_agent_model(agent),
                    "conversation_id": conversation_key,
                },
            }

        except Exception:
            self._conversations.pop(conversation_key, None)

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

    async def _execute_remote_a2a(
        self,
        payload: dict[str, Any],
        metadata: Mapping[str, Any],
        url: str,
        message: str,
        agent_id: str,
        conversation_key: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Execute a remote AG2 agent through the native AG2 A2A client.

        The endpoint is an Agent Card base URL, not an arbitrary JSON HTTP
        endpoint. AG2 performs Agent Card discovery and negotiates JSON-RPC,
        REST, or gRPC from the card.
        """
        normalized_url = self._normalize_a2a_card_url(url)

        try:
            ag2 = self._import_ag2()
            a2a_config_cls = self._import_a2a_config()

            response_schema = payload.get("response_schema")
            if response_schema is not None:
                return self._error(
                    message=(
                        "AG2 A2A execution does not support per-request "
                        "response_schema with the pinned AG2 client."
                    ),
                    agent_id=agent_id,
                    mode="remote",
                    endpoint=normalized_url,
                    span_context=span_context,
                )

            state = self._conversations.get(conversation_key)

            if state is None:
                remote_agent = self._build_remote_agent(
                    ag2=ag2,
                    a2a_config_cls=a2a_config_cls,
                    payload=payload,
                    metadata=metadata,
                    url=normalized_url,
                    agent_id=agent_id,
                )

                state = _ConversationState(
                    agent=remote_agent,
                    mode="remote",
                )
                self._conversations[conversation_key] = state

            async with state.lock:
                return await self._execute_remote_turn(
                    state=state,
                    payload=payload,
                    message=message,
                    agent_id=agent_id,
                    conversation_key=conversation_key,
                    endpoint=normalized_url,
                    span_context=span_context,
                    framework_version=str(getattr(ag2, "__version__", "unknown")),
                )

        except ImportError as exc:
            return self._error(
                message=str(exc),
                agent_id=agent_id,
                mode="remote",
                endpoint=normalized_url,
                span_context=span_context,
            )
        except TimeoutError:
            timeout = self._adapter_timeout()
            return self._error(
                message=(f"AG2 remote A2A execution timed out after {timeout:.1f}s."),
                agent_id=agent_id,
                mode="remote",
                endpoint=normalized_url,
                span_context=span_context,
            )
        except Exception as exc:
            self._conversations.pop(conversation_key, None)

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "message": f"AG2 remote A2A execution failed: {exc}",
                    "exception_type": type(exc).__name__,
                    "endpoint": normalized_url,
                },
                span_context=span_context,
            )

            return self._error(
                message=f"AG2 remote A2A execution failed: {exc}",
                agent_id=agent_id,
                mode="remote",
                endpoint=normalized_url,
                span_context=span_context,
            )

    async def _execute_remote_turn(
        self,
        state: _ConversationState,
        payload: dict[str, Any],
        message: str,
        agent_id: str,
        conversation_key: str,
        endpoint: str,
        span_context: dict[str, Any] | None,
        framework_version: str,
    ) -> dict[str, Any]:
        remote_agent = state.agent
        timeout = self._adapter_timeout()

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": "ag2",
                "agent_id": agent_id,
                "framework": "ag2",
                "version": framework_version,
                "mode": "remote",
                "protocol": "a2a",
                "endpoint": endpoint,
                "conversation_id": conversation_key,
            },
            span_context=span_context,
        )

        emit(
            CoreEvents.NODE_START,
            {
                "adapter": "ag2",
                "node_id": agent_id,
            },
            span_context=span_context,
        )

        try:
            previous_reply = state.reply

            if previous_reply is not None:
                if payload.get("response_schema") is not None:
                    raise ValueError("Per-request response_schema is not supported by AG2 A2A.")

                reply = await asyncio.wait_for(
                    previous_reply.ask(message),
                    timeout=timeout,
                )
            else:
                reply = await asyncio.wait_for(
                    remote_agent.ask(message),
                    timeout=timeout,
                )

            state.reply = reply

            event_summary = await self._collect_reply_events(
                reply=reply,
                start_index=state.event_cursor,
                agent_id=agent_id,
                span_context=span_context,
            )

            state.event_cursor = await self._history_length(reply)

            body = getattr(reply, "body", None)
            parsed_content = await self._extract_reply_content(reply)

            output = (
                body.strip()
                if isinstance(body, str) and body.strip()
                else self._stringify(parsed_content).strip()
            )

            if not output:
                raise ValueError("AG2 remote A2A agent returned an empty response.")

            action = DualNormalizationHub.normalize_text(output)

            emit(
                CoreEvents.AGENT_RESPONSE,
                {
                    "adapter": "ag2",
                    "agent_id": agent_id,
                    "output": output,
                    "action": action,
                },
                span_context=span_context,
            )

            emit(
                CoreEvents.NODE_END,
                {
                    "adapter": "ag2",
                    "node_id": agent_id,
                    "action": action,
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
                "content": parsed_content,
                "action": action,
                "metadata": {
                    "framework": "ag2",
                    "version": framework_version,
                    "mode": "remote",
                    "protocol": "a2a",
                    "endpoint": endpoint,
                    "agent_id": agent_id,
                    "reply_type": type(reply).__name__,
                    "event_summary": event_summary,
                    "conversation_id": conversation_key,
                },
            }

        except Exception:
            self._conversations.pop(conversation_key, None)

            emit(
                CoreEvents.NODE_END,
                {
                    "adapter": "ag2",
                    "node_id": agent_id,
                    "action": "error",
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

            raise

    async def _resolve_agent(
        self,
        payload: dict[str, Any],
        metadata: Mapping[str, Any],
    ) -> Any:
        """
        Resolve a real AG2 Agent.

        Supported direct targets:
          payload["agent"]
          metadata["agent"]

        Supported import paths:
          metadata["agent_path"]
          metadata["logic_path"]
          payload["agent_path"]

        Import targets may be:
          - an Agent instance
          - a callable factory
        """
        direct_agent = payload.get("agent") or metadata.get("agent")

        if direct_agent is not None:
            if self._is_agent_like(direct_agent):
                return direct_agent

            raise TypeError(
                "payload['agent'] / metadata['agent'] was provided but is not "
                "an AG2 Agent exposing ask()."
            )

        agent_path = (
            metadata.get("agent_path") or metadata.get("logic_path") or payload.get("agent_path")
        )

        if not agent_path:
            raise ValueError(
                "No AG2 native agent target configured. "
                "Set metadata.agent_path to module:attribute, where the "
                "attribute is an AG2 Agent or factory returning one."
            )

        target = self._load_symbol(str(agent_path))

        if self._is_agent_like(target):
            return target

        if not callable(target):
            raise TypeError(
                f"AG2 target '{agent_path}' is neither an Agent nor a callable factory."
            )

        result = await self._invoke_agent_factory(
            factory=target,
            payload=payload,
            message=self._resolve_message(payload, {}),
        )

        if not self._is_agent_like(result):
            raise TypeError(f"AG2 factory '{agent_path}' did not return an object exposing ask().")

        return result

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
        elif any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
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
    def _import_a2a_config() -> Any:
        try:
            module = importlib.import_module("ag2.a2a")
            return module.A2AConfig
        except (ImportError, AttributeError):
            raise ImportError(
                "The installed AG2 package does not expose A2AConfig. "
                "Install AG2 >= 1.0.0 with A2A support."
            ) from None

    @staticmethod
    def _is_agent_like(value: Any) -> bool:
        return value is not None and callable(getattr(value, "ask", None))

    @staticmethod
    def _resolve_message(
        payload: Mapping[str, Any],
        kwargs: Mapping[str, Any] | None = None,
    ) -> str:
        kwargs = kwargs or {}

        candidates = (
            payload.get("message"),
            payload.get("task_description"),
            payload.get("task"),
            payload.get("prompt"),
            kwargs.get("message"),
            getattr(kwargs.get("turn_ctx"), "current_message", None),
        )

        for candidate in candidates:
            if candidate is None:
                continue

            if isinstance(candidate, str):
                text = candidate.strip()
                if text:
                    return text
                continue

            if isinstance(candidate, Mapping):
                text = AG2AdapterPlugin._stringify(candidate).strip()
                if text:
                    return text
                continue

            text = str(candidate).strip()
            if text:
                return text

        raise ValueError("AG2 execution requires a non-empty task/message.")

    @staticmethod
    def _build_observer_stream(ag2: Any) -> Any | None:
        """
        Create an AG2 MemoryStream for first-turn event observation.

        Conversation continuity does not depend on this stream. Continuation
        is carried by AgentReply.ask(...), avoiding the original per-call
        MemoryStream reset.
        """
        try:
            stream_module = importlib.import_module("ag2.stream")
            stream_cls = stream_module.MemoryStream
        except (ImportError, AttributeError):
            # AG2 versions predating the stream module exposed MemoryStream
            # at the package root. Keep that compatibility path explicit.
            stream_cls = getattr(ag2, "MemoryStream", None)

        if stream_cls is None:
            return None

        try:
            return stream_cls()
        except (RuntimeError, TypeError, ValueError) as exc:
            logger.warning("AG2 MemoryStream construction failed: %s", exc)
            return None

    @staticmethod
    def _build_initial_ask_kwargs(
        payload: Mapping[str, Any],
        stream: Any | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        if stream is not None:
            kwargs["stream"] = stream

        response_schema = payload.get("response_schema")
        if response_schema is not None:
            if not callable(response_schema) and not isinstance(
                response_schema,
                type,
            ):
                raise TypeError(
                    "response_schema must be a callable/type/schema object "
                    "supported by the installed AG2 SDK."
                )
            kwargs["response_schema"] = response_schema

        for field_name in (
            "tools",
            "tool_choice",
            "max_tool_iterations",
        ):
            value = payload.get(field_name)
            if value is not None:
                kwargs[field_name] = value

        return kwargs

    @staticmethod
    def _build_reply_ask_kwargs(
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}

        response_schema = payload.get("response_schema")
        if response_schema is not None:
            if not callable(response_schema) and not isinstance(
                response_schema,
                type,
            ):
                raise TypeError(
                    "response_schema must be a callable/type/schema object "
                    "supported by the installed AG2 SDK."
                )
            kwargs["response_schema"] = response_schema

        for field_name in (
            "tools",
            "tool_choice",
            "max_tool_iterations",
        ):
            value = payload.get(field_name)
            if value is not None:
                kwargs[field_name] = value

        return kwargs

    async def _collect_reply_events(
        self,
        reply: Any,
        start_index: int,
        agent_id: str,
        span_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        events: list[Any] = []

        history = getattr(reply, "history", None)
        get_events = getattr(history, "get_events", None)

        if callable(get_events):
            try:
                raw_events = await get_events()

                if isinstance(raw_events, Sequence):
                    events = list(raw_events)
                else:
                    events = list(raw_events)

            except Exception as exc:
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "message": (f"AG2 event history unavailable: {exc}"),
                    },
                    span_context=span_context,
                )

        start = max(0, min(start_index, len(events)))
        new_events = events[start:]

        summary = {
            "total_events": len(new_events),
            "model_requests": 0,
            "model_responses": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "hitl_requests": 0,
        }

        for event in new_events:
            event_name = type(event).__name__.lower()

            if event_name == "modelrequest":
                summary["model_requests"] += 1
                continue

            if event_name == "modelresponse":
                summary["model_responses"] += 1
                continue

            if "toolcalls" in event_name or "toolcall" in event_name:
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
                            "function_args",
                            default=None,
                        ),
                    },
                    span_context=span_context,
                )
                continue

            if "toolresults" in event_name or "toolresult" in event_name:
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
                            "output",
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
                            "prompt",
                            default="AG2 requested human input.",
                        ),
                    },
                    span_context=span_context,
                )
                continue

            if event_name == "humanmessage":
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "ag2",
                        "agent_id": agent_id,
                        "event_type": "HumanMessage",
                    },
                    span_context=span_context,
                )

        return summary

    @staticmethod
    async def _history_length(reply: Any) -> int:
        history = getattr(reply, "history", None)
        get_events = getattr(history, "get_events", None)

        if not callable(get_events):
            return 0

        try:
            events = await get_events()
            return len(events)
        except Exception:
            return 0

    @staticmethod
    async def _extract_reply_content(reply: Any) -> Any:
        content = getattr(reply, "content", None)

        if callable(content):
            value = content()
            return await value if inspect.isawaitable(value) else value

        if content is not None:
            return content

        response = getattr(reply, "response", None)
        if response is not None:
            response_content = getattr(response, "content", None)
            if response_content is not None:
                return response_content

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

    def _build_remote_agent(
        self,
        ag2: Any,
        a2a_config_cls: Any,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        url: str,
        agent_id: str,
    ) -> Any:
        config_kwargs: dict[str, Any] = {
            "card_url": url,
            "prefer": self._resolve_a2a_preference(payload, metadata),
            "streaming": self._resolve_bool(
                payload,
                metadata,
                "a2a_streaming",
                True,
            ),
            "timeout": self._resolve_float(
                payload,
                metadata,
                "a2a_timeout",
                self._DEFAULT_A2A_TIMEOUT,
            ),
            "max_reconnects": self._resolve_int(
                payload,
                metadata,
                "a2a_max_reconnects",
                3,
            ),
            "reconnect_backoff": self._resolve_float(
                payload,
                metadata,
                "a2a_reconnect_backoff",
                0.5,
            ),
            "polling_interval": self._resolve_float(
                payload,
                metadata,
                "a2a_polling_interval",
                0.5,
            ),
            "input_required_timeout": self._resolve_optional_float(
                payload,
                metadata,
                "a2a_input_required_timeout",
            ),
            "tenant": self._resolve_optional_string(
                payload,
                metadata,
                "tenant",
            ),
            "history_length": self._resolve_optional_int(
                payload,
                metadata,
                "a2a_history_length",
            ),
            "extensions": self._resolve_extensions(
                payload,
                metadata,
            ),
        }

        headers = self._resolve_remote_headers(
            payload=payload,
            metadata=metadata,
        )

        if headers:
            config_kwargs["headers"] = headers

        card_signature_verifier = metadata.get("card_signature_verifier") or payload.get(
            "card_signature_verifier"
        )
        if card_signature_verifier is not None:
            config_kwargs["card_signature_verifier"] = card_signature_verifier

        config_kwargs = {key: value for key, value in config_kwargs.items() if value is not None}

        remote_config = a2a_config_cls(**config_kwargs)

        agent_cls = getattr(ag2, "Agent", None)
        if agent_cls is None:
            raise ImportError("The installed AG2 package does not expose Agent.")

        return agent_cls(
            name=agent_id,
            config=remote_config,
        )

    @staticmethod
    def _resolve_remote_headers(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> dict[str, str]:
        headers: dict[str, str] = {}

        for source in (
            metadata.get("headers"),
            metadata.get("request_headers"),
            payload.get("headers"),
            payload.get("request_headers"),
        ):
            if not isinstance(source, Mapping):
                continue

            for key, value in source.items():
                if key is None or value is None:
                    continue

                key_text = str(key).strip()
                value_text = str(value).strip()

                if key_text and value_text:
                    headers[key_text] = value_text

        authorization = payload.get("authorization") or metadata.get("authorization")

        token = (
            payload.get("api_key")
            or payload.get("token")
            or metadata.get("api_key")
            or metadata.get("token")
        )

        if authorization:
            headers.setdefault(
                "Authorization",
                str(authorization),
            )
        elif token:
            headers.setdefault(
                "Authorization",
                f"Bearer {token}",
            )

        return headers

    @staticmethod
    def _normalize_a2a_card_url(url: str) -> str:
        parts = urlsplit(url)

        if parts.scheme not in {"http", "https"}:
            raise ValueError(f"AG2 A2A endpoint must use HTTP(S), got '{parts.scheme}'.")

        path = parts.path.rstrip("/")

        suffixes = (
            "/.well-known/agent-card.json",
            "/agent-card.json",
        )

        for suffix in suffixes:
            if path.endswith(suffix):
                path = path[: -len(suffix)].rstrip("/")
                break

        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                path,
                parts.query,
                "",
            )
        ).rstrip("/")

    @staticmethod
    def _merge_runtime_context(
        payload: Mapping[str, Any],
        kwargs: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(payload)

        turn_ctx = kwargs.get("turn_ctx")

        if turn_ctx is not None:
            input_payload = getattr(
                turn_ctx,
                "input_payload",
                None,
            )

            if isinstance(input_payload, Mapping):
                for key, value in input_payload.items():
                    merged.setdefault(key, value)

            current_message = getattr(
                turn_ctx,
                "current_message",
                None,
            )

            if current_message and not merged.get("message"):
                merged["message"] = current_message

            history = getattr(turn_ctx, "history", None)

            if history is not None and "history" not in merged:
                merged["history"] = history

            turn_metadata = getattr(
                turn_ctx,
                "metadata",
                None,
            )

            if isinstance(turn_metadata, Mapping):
                existing_metadata = merged.get("metadata")
                combined_metadata = (
                    dict(existing_metadata) if isinstance(existing_metadata, Mapping) else {}
                )

                for key, value in turn_metadata.items():
                    combined_metadata.setdefault(key, value)

                merged["metadata"] = combined_metadata

        return merged

    @staticmethod
    def _resolve_agent_id(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> str:
        value = (
            payload.get("agent_id")
            or payload.get("task_id")
            or metadata.get("agent_id")
            or "default_agent"
        )

        return str(value)

    @staticmethod
    def _conversation_key(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        agent_id: str,
        endpoint: str | None,
    ) -> str:
        explicit = (
            payload.get("conversation_id")
            or payload.get("session_id")
            or metadata.get("conversation_id")
            or metadata.get("session_id")
        )

        if explicit:
            base = str(explicit)
        else:
            evaluation_scope = (
                payload.get("evaluation_id")
                or payload.get("run_id")
                or payload.get("scenario_id")
                or metadata.get("evaluation_id")
                or metadata.get("run_id")
                or metadata.get("scenario_id")
            )

            base = f"{evaluation_scope}:{agent_id}" if evaluation_scope else agent_id

        mode = "remote" if endpoint else "native"
        endpoint_fingerprint = (
            hashlib.sha256(str(endpoint).encode("utf-8")).hexdigest()[:16] if endpoint else "local"
        )

        return f"{mode}:{endpoint_fingerprint}:{base}"

    @staticmethod
    def _adapter_timeout() -> float:
        value = getattr(
            config,
            "DEFAULT_ADAPTER_TIMEOUT",
            AG2AdapterPlugin._DEFAULT_TIMEOUT,
        )

        try:
            timeout = float(value)
        except (TypeError, ValueError):
            timeout = AG2AdapterPlugin._DEFAULT_TIMEOUT

        return max(0.1, timeout)

    @staticmethod
    def _resolve_a2a_preference(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> str | None:
        value = (
            payload.get("a2a_prefer")
            or payload.get("prefer")
            or metadata.get("a2a_prefer")
            or metadata.get("prefer")
        )

        if value is None:
            return None

        value = str(value).strip().lower()

        if value not in {"jsonrpc", "rest", "grpc"}:
            raise ValueError(
                "AG2 A2A transport preference must be one of 'jsonrpc', 'rest', or 'grpc'."
            )

        return value

    @staticmethod
    def _resolve_extensions(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> tuple[str, ...]:
        raw = payload.get("a2a_extensions") or metadata.get("a2a_extensions") or ()

        if isinstance(raw, str):
            raw = [raw]

        if not isinstance(raw, Sequence):
            raise TypeError("AG2 A2A extensions must be a sequence of URI strings.")

        extensions: list[str] = []

        for value in raw:
            value = str(value).strip()
            if value:
                extensions.append(value)

        return tuple(dict.fromkeys(extensions))

    @staticmethod
    def _resolve_bool(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
        default: bool,
    ) -> bool:
        value = payload.get(key, metadata.get(key, default))

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {"1", "true", "yes", "on"}:
                return True

            if normalized in {"0", "false", "no", "off"}:
                return False

        return bool(value)

    @staticmethod
    def _resolve_float(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
        default: float,
    ) -> float:
        value = payload.get(key, metadata.get(key, default))

        try:
            result = float(value)
        except (TypeError, ValueError):
            result = default

        return max(0.0, result)

    @staticmethod
    def _resolve_int(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
        default: int,
    ) -> int:
        value = payload.get(key, metadata.get(key, default))

        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default

        return max(0, result)

    @classmethod
    def _resolve_optional_float(
        cls,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
    ) -> float | None:
        value = payload.get(key, metadata.get(key))

        if value is None:
            return None

        return cls._resolve_float(
            payload,
            metadata,
            key,
            0.0,
        )

    @classmethod
    def _resolve_optional_int(
        cls,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
    ) -> int | None:
        value = payload.get(key, metadata.get(key))

        if value is None:
            return None

        return cls._resolve_int(
            payload,
            metadata,
            key,
            0,
        )

    @staticmethod
    def _resolve_optional_string(
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any],
        key: str,
    ) -> str | None:
        value = payload.get(key, metadata.get(key))

        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @staticmethod
    def _is_http_url(value: Any) -> bool:
        return isinstance(value, str) and urlsplit(value).scheme in {
            "http",
            "https",
        }

    @staticmethod
    def _truthy(value: Any) -> bool:
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
    def _stringify(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )
        except Exception:
            return str(value)

    @staticmethod
    def _error(
        message: str,
        agent_id: str,
        mode: str,
        span_context: dict[str, Any] | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "framework": "ag2",
            "agent_id": agent_id,
            "mode": mode,
            "protocol": ("a2a" if mode == "remote" else "ag2-native"),
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
