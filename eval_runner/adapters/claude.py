# eval_runner/adapters/claude.py
"""
Anthropic Claude adapter for AgentV.

Implements the Anthropic Messages API over the shared aiohttp SessionManager.

Design goals:
- Exact engine -> adapter input compatibility (`task_description`, `messages`, etc.)
- Direct Anthropic Messages API transport without requiring the Anthropic SDK
- Multi-turn messages and top-level system prompt handling
- Tool use, tool choice, thinking, structured output, metadata and service-tier passthrough
- SSE streaming aggregation
- Provider-native response normalization
- Token/caching telemetry
- Trace-context propagation
- Shared connection pooling and retry behavior
- Fail-closed handling of malformed/empty provider responses
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import aiohttp

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager

logger = logging.getLogger(__name__)

# Anthropic Messages API currently requires this API version header.
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


class ClaudeAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native Anthropic Messages API adapter.

    Protocol:
        claude

    Wire API:
        POST /v1/messages

    The adapter is intentionally transport-level rather than SDK-dependent so the
    core AgentV installation does not need the Anthropic Python SDK.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="claude")

    def on_discover_adapters(self, registry: Any):
        """Register the Claude provider adapter."""
        print("      [Plugin] Registering Claude adapter via on_discover_adapters hook.")
        registry.register("claude", self.execute_claude_query)

    @staticmethod
    def _traceparent(payload: dict[str, Any]) -> str | None:
        span_context = payload.get("span_context")
        if not isinstance(span_context, dict):
            return None

        traceparent = span_context.get("traceparent")
        return traceparent if isinstance(traceparent, str) and traceparent else None

    @staticmethod
    def _resolve_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Resolve the canonical Anthropic `messages` request field.

        Priority:
            messages
            history
            task_description
            task
            prompt
        """
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        if raw_messages is not None:
            if not isinstance(raw_messages, list):
                raise ValueError("Claude 'messages' must be a list.")

            messages: list[dict[str, Any]] = []

            for index, message in enumerate(raw_messages):
                if not isinstance(message, dict):
                    raise ValueError(f"Claude message at index {index} must be an object.")

                role = message.get("role")
                if role not in {"user", "assistant", "system"}:
                    raise ValueError(f"Unsupported Claude message role at index {index}: {role!r}.")

                if "content" not in message:
                    raise ValueError(
                        f"Claude message at index {index} is missing required 'content'."
                    )

                # Anthropic Messages API has no system-role message. System messages
                # are handled separately by `_resolve_system_prompt`.
                messages.append(
                    {key: value for key, value in message.items() if key not in {"name"}}
                )

            return messages

        for key in ("task_description", "task", "prompt"):
            value = payload.get(key)
            if value is not None:
                text = str(value)
                if text.strip():
                    return [{"role": "user", "content": text}]

        raise ValueError(
            "Claude adapter received no input. Provide 'messages' or 'task_description'."
        )

    @staticmethod
    def _resolve_system_prompt(
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str | list[dict[str, Any]] | None:
        """
        Resolve the Anthropic top-level `system` field.

        Explicit payload system configuration wins over system-role messages.
        """
        explicit = payload.get("system")
        if explicit is None:
            explicit = payload.get("system_prompt")

        system_messages: list[Any] = []

        for message in messages:
            if message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, list):
                    system_messages.extend(content)
                elif content is not None:
                    system_messages.append({"type": "text", "text": str(content)})

        if explicit is not None:
            return explicit

        if not system_messages:
            return None

        # Preserve structured text blocks if present; otherwise return a string.
        if len(system_messages) == 1 and isinstance(system_messages[0], dict):
            first = system_messages[0]
            if first.get("type") == "text" and set(first).issubset(
                {"type", "text", "cache_control", "citations"}
            ):
                return str(first["text"])

        return system_messages

    @staticmethod
    def _strip_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove system-role messages before sending to Anthropic."""
        return [m for m in messages if m.get("role") != "system"]

    @staticmethod
    def _resolve_auth(payload: dict[str, Any]) -> str:
        api_key = (
            payload.get("api_key")
            or payload.get("anthropic_api_key")
            or config.ANTHROPIC_API_KEY
            or os.getenv("ANTHROPIC_API_KEY")
        )

        if not api_key:
            raise ValueError("Anthropic API key missing.")

        return str(api_key)

    @staticmethod
    def _resolve_url(payload: dict[str, Any], url: str | None) -> str:
        endpoint = (
            url
            or payload.get("url")
            or payload.get("base_url")
            or config.ANTHROPIC_BASE_URL
            or "https://api.anthropic.com/v1/messages"
        )

        endpoint = str(endpoint).rstrip("/")

        if endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/messages"
        elif not endpoint.endswith("/messages"):
            # Accept a host/base URL without requiring callers to know the
            # exact Messages API path.
            if endpoint.endswith("/v1"):
                endpoint = f"{endpoint}/messages"
            elif "/v1/messages" not in endpoint:
                endpoint = f"{endpoint}/v1/messages"

        return endpoint

    @staticmethod
    def _resolve_headers(payload: dict[str, Any], api_key: str) -> dict[str, str]:
        headers: dict[str, str] = {
            "x-api-key": api_key,
            "anthropic-version": str(
                payload.get("anthropic_version")
                or payload.get("api_version")
                or config.ANTHROPIC_VERSION
                or DEFAULT_ANTHROPIC_VERSION
            ),
            "content-type": "application/json",
            "accept": "application/json",
        }

        traceparent = ClaudeAdapterPlugin._traceparent(payload)
        if traceparent:
            headers["traceparent"] = traceparent

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        beta_headers = (
            payload.get("anthropic_beta")
            or payload.get("anthropic_betas")
            or metadata.get("anthropic_beta")
            or metadata.get("anthropic_betas")
        )

        if isinstance(beta_headers, str):
            beta_headers = [beta_headers]

        if isinstance(beta_headers, (list, tuple, set)):
            values = [str(v).strip() for v in beta_headers if str(v).strip()]
            if values:
                headers["anthropic-beta"] = ",".join(values)

        user_profile_id = payload.get("anthropic_user_profile_id") or metadata.get(
            "anthropic_user_profile_id"
        )
        if user_profile_id:
            headers["anthropic-user-profile-id"] = str(user_profile_id)

        workspace_id = payload.get("anthropic_workspace_id") or metadata.get(
            "anthropic_workspace_id"
        )
        if workspace_id:
            headers["anthropic-workspace-id"] = str(workspace_id)

        return headers

    @staticmethod
    def _copy_optional_request_fields(
        payload: dict[str, Any],
        request: dict[str, Any],
    ) -> None:
        """
        Copy supported Anthropic Messages API fields without leaking arbitrary
        harness-internal payload attributes.
        """
        supported_fields = {
            "temperature",
            "top_p",
            "top_k",
            "stop_sequences",
            "stream",
            "tools",
            "tool_choice",
            "thinking",
            "output_config",
            "metadata",
            "service_tier",
            "container",
            "inference_geo",
            "cache_control",
            "compaction",
        }

        for field in supported_fields:
            if field in payload and payload[field] is not None:
                request[field] = payload[field]

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        chunks: list[str] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            if block.get("type") == "text":
                text = block.get("text")
                if text:
                    chunks.append(str(text))

        return "".join(chunks)

    @staticmethod
    def _extract_thinking(content: list[Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            if block_type in {"thinking", "redacted_thinking"}:
                blocks.append(block)

        return blocks

    @staticmethod
    def _extract_tool_calls(content: list[Any]) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            if block.get("type") != "tool_use":
                continue

            tool_calls.append(
                {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {}),
                    "type": "tool_use",
                }
            )

        return tool_calls

    @staticmethod
    def _extract_citations(content: list[Any]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            block_citations = block.get("citations")
            if isinstance(block_citations, list):
                citations.extend(item for item in block_citations if isinstance(item, dict))

        return citations

    @staticmethod
    def _usage_metadata(usage: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(usage, dict):
            return {}

        # Preserve the provider's raw counters while exposing a canonical
        # AgentV token structure.
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)

        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)

        total_tokens = input_tokens + output_tokens

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            **usage,
        }

    @classmethod
    def _normalize_message_response(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("Anthropic returned a non-object response.")

        if data.get("type") == "error":
            error_obj = data.get("error")
            if isinstance(error_obj, dict):
                message = error_obj.get("message") or str(error_obj)
                error_type = error_obj.get("type")
            else:
                message = str(error_obj or "Anthropic API error.")
                error_type = None

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "error_type": error_type,
                    "raw_response": data,
                },
            }

        content = data.get("content")
        if not isinstance(content, list):
            raise ValueError("Anthropic response missing valid 'content' blocks.")

        output = cls._extract_text(content)
        thinking = cls._extract_thinking(content)
        tool_calls = cls._extract_tool_calls(content)
        citations = cls._extract_citations(content)

        stop_reason = data.get("stop_reason")
        stop_sequence = data.get("stop_sequence")

        if tool_calls or stop_reason == "tool_use":
            action = "processing"
        elif stop_reason in {"end_turn", "stop_sequence", "max_tokens", "compaction"}:
            action = DualNormalizationHub.normalize_text(output) if output else "final_answer"
        elif output:
            action = DualNormalizationHub.normalize_text(output)
        else:
            # Unknown empty terminal state is not allowed to become a
            # successful final answer.
            action = "error"

        if not output and not tool_calls and not thinking:
            return {
                "status": "error",
                "action": "error",
                "message": ("Anthropic returned no usable text, tool-use, or thinking content."),
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "response_id": data.get("id"),
                    "model": data.get("model"),
                    "stop_reason": stop_reason,
                    "raw_response": data,
                },
            }

        usage = cls._usage_metadata(data.get("usage"))

        if usage:
            emit(
                "metric_update",
                {
                    "adapter": "claude",
                    "tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                },
            )

        return {
            "status": "success",
            "output": output,
            "action": action,
            "tool_calls": tool_calls,
            "thinking": thinking,
            "citations": citations,
            "metadata": {
                "framework": "claude",
                "provider": "anthropic",
                "response_id": data.get("id"),
                "response_type": data.get("type"),
                "model": data.get("model"),
                "role": data.get("role"),
                "stop_reason": stop_reason,
                "stop_sequence": stop_sequence,
                "usage": usage,
                "container": data.get("container"),
                "service_tier": data.get("service_tier"),
                "raw_content_blocks": content,
            },
        }

    @classmethod
    def _aggregate_sse_events(
        cls,
        events: list[tuple[str | None, dict[str, Any]]],
    ) -> dict[str, Any]:
        """
        Reconstruct a final Anthropic Message from RawMessageStreamEvent events.
        """
        message: dict[str, Any] = {
            "type": "message",
            "content": [],
            "usage": {},
        }

        block_map: dict[int, dict[str, Any]] = {}
        final_usage: dict[str, Any] = {}

        for event_type, data in events:
            if event_type == "message_start":
                msg = data.get("message")
                if isinstance(msg, dict):
                    message.update(msg)

                    initial_usage = msg.get("usage")
                    if isinstance(initial_usage, dict):
                        final_usage.update(initial_usage)

            elif event_type == "content_block_start":
                index = data.get("index")
                block = data.get("content_block")

                if isinstance(index, int) and isinstance(block, dict):
                    block_map[index] = dict(block)

            elif event_type == "content_block_delta":
                index = data.get("index")
                delta = data.get("delta")

                if not isinstance(index, int) or not isinstance(delta, dict):
                    continue

                block = block_map.setdefault(index, {})

                delta_type = delta.get("type")

                if delta_type == "text_delta":
                    block["type"] = "text"
                    block["text"] = f"{block.get('text', '')}{delta.get('text', '')}"

                elif delta_type == "thinking_delta":
                    block["type"] = "thinking"
                    block["thinking"] = f"{block.get('thinking', '')}{delta.get('thinking', '')}"

                elif delta_type == "signature_delta":
                    block["signature"] = f"{block.get('signature', '')}{delta.get('signature', '')}"

                elif delta_type == "input_json_delta":
                    block["type"] = "tool_use"

                    partial_json = delta.get("partial_json", "")
                    block["_partial_json"] = f"{block.get('_partial_json', '')}{partial_json}"

            elif event_type == "content_block_stop":
                index = data.get("index")
                if isinstance(index, int) and index in block_map:
                    block = block_map[index]

                    partial_json = block.pop("_partial_json", None)
                    if partial_json is not None:
                        try:
                            block["input"] = json.loads(partial_json)
                        except json.JSONDecodeError:
                            # Preserve incomplete provider data rather than
                            # fabricating successful tool arguments.
                            block["input"] = {"_invalid_partial_json": partial_json}

            elif event_type == "message_delta":
                delta = data.get("delta")
                usage = data.get("usage")

                if isinstance(delta, dict):
                    if delta.get("stop_reason") is not None:
                        message["stop_reason"] = delta["stop_reason"]
                    if delta.get("stop_sequence") is not None:
                        message["stop_sequence"] = delta["stop_sequence"]

                if isinstance(usage, dict):
                    final_usage.update(usage)

            elif event_type == "message_stop":
                pass

        ordered_blocks = [block_map[i] for i in sorted(block_map)]
        message["content"] = ordered_blocks
        message["usage"] = final_usage

        return message

    async def _read_stream(
        self,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        """
        Read an Anthropic SSE response and reconstruct the final Message object.

        Handles event/data pairs, multiline SSE data, pings, and terminal events.
        """
        events: list[tuple[str | None, dict[str, Any]]] = []
        current_event: str | None = None
        data_lines: list[str] = []

        async for raw_line in response.content:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

            if line == "":
                if data_lines:
                    raw_data = "\n".join(data_lines)

                    if raw_data != "[DONE]":
                        try:
                            parsed = json.loads(raw_data)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"Anthropic SSE returned invalid JSON event: {raw_data}"
                            ) from exc

                        if isinstance(parsed, dict):
                            events.append((current_event, parsed))

                    current_event = None
                    data_lines = []

                continue

            if line.startswith(":"):
                # SSE comment / keep-alive.
                continue

            if line.startswith("event:"):
                current_event = line[6:].strip()
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue

        # Flush a final event if the stream ended without a blank separator.
        if data_lines:
            raw_data = "\n".join(data_lines)
            if raw_data != "[DONE]":
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Anthropic SSE returned invalid trailing JSON event: {raw_data}"
                    ) from exc

                if isinstance(parsed, dict):
                    events.append((current_event, parsed))

        if not events:
            raise ValueError("Anthropic streaming response contained no SSE events.")

        return self._aggregate_sse_events(events)

    async def execute_claude_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute an Anthropic Messages API request.

        Expected engine inputs include:
            task_description
            messages
            system/system_prompt
            model
            max_tokens
            temperature
            tools
            tool_choice
            thinking
            output_config
            stream

        Returns an AgentV-normalized response dictionary.
        """
        try:
            if not isinstance(payload, dict):
                raise ValueError("Claude adapter payload must be an object.")

            api_key = self._resolve_auth(payload)
            endpoint = self._resolve_url(payload, url)

            messages = self._resolve_messages(payload)
            system_prompt = self._resolve_system_prompt(payload, messages)
            messages = self._strip_system_messages(messages)

            if not messages:
                raise ValueError(
                    "Claude Messages API requires at least one user or assistant message."
                )

            model = str(
                payload.get("model") or payload.get("anthropic_model") or config.ANTHROPIC_MODEL
            )

            if not model:
                raise ValueError("Anthropic model is required.")

            max_tokens_raw = payload.get("max_tokens", config.LLM_MAX_TOKENS)
            try:
                max_tokens = int(max_tokens_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Claude 'max_tokens' must be an integer.") from exc

            if max_tokens < 0:
                raise ValueError("Claude 'max_tokens' must be >= 0.")

            request: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }

            if system_prompt is not None:
                request["system"] = system_prompt

            self._copy_optional_request_fields(payload, request)

            # The engine expects a terminal JSON object even when the provider
            # internally uses SSE.
            stream = bool(request.get("stream", False))

            headers = self._resolve_headers(payload, api_key)
            if stream:
                headers["accept"] = "text/event-stream"

            timeout_seconds = payload.get("timeout", config.DEFAULT_ADAPTER_TIMEOUT)
            try:
                timeout_seconds = float(timeout_seconds)
            except (TypeError, ValueError):
                timeout_seconds = float(config.DEFAULT_ADAPTER_TIMEOUT)

            emit(
                CoreEvents.CHAIN_START,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "model": model,
                    "endpoint": endpoint,
                    "stream": stream,
                },
                span_context=payload.get("span_context"),
            )

            async def _call() -> dict[str, Any]:
                session = await SessionManager.get_session()

                timeout = aiohttp.ClientTimeout(total=max(timeout_seconds, 1.0))

                async with session.post(
                    endpoint,
                    json=request,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if response.status >= 400:
                        # Read the provider body before raising so diagnostics
                        # retain the actual Anthropic error payload.
                        body_text = await response.text()

                        error_message = body_text.strip()
                        try:
                            body_json = json.loads(body_text)
                        except json.JSONDecodeError:
                            body_json = None

                        if isinstance(body_json, dict):
                            error_obj = body_json.get("error")
                            if isinstance(error_obj, dict):
                                error_message = str(
                                    error_obj.get("message")
                                    or error_obj.get("type")
                                    or error_message
                                )

                        raise aiohttp.ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=error_message,
                            headers=response.headers,
                        )

                    if stream:
                        return await self._read_stream(response)

                    data = await response.json()

                    if not isinstance(data, dict):
                        raise ValueError("Anthropic non-streaming response is not a JSON object.")

                    return data

            data = await self.call_with_retry(_call)

            normalized = self._normalize_message_response(data)

            if normalized.get("status") == "success":
                emit(
                    CoreEvents.CHAIN_END,
                    {
                        "adapter": "claude",
                        "provider": "anthropic",
                        "model": model,
                        "response_id": normalized.get("metadata", {}).get("response_id"),
                        "stop_reason": normalized.get("metadata", {}).get("stop_reason"),
                    },
                    span_context=payload.get("span_context"),
                )
            else:
                emit(
                    CoreEvents.ERROR,
                    {
                        "adapter": "claude",
                        "provider": "anthropic",
                        "message": normalized.get("message"),
                    },
                    span_context=payload.get("span_context"),
                )

            # Preserve the exact request envelope required for forensic/debug
            # purposes without retaining the API key.
            normalized.setdefault("metadata", {})
            normalized["metadata"].update(
                {
                    "endpoint": endpoint,
                    "request": request,
                    "execution_mode": "native",
                    "adapter_version": "2.0.0",
                }
            )

            return normalized

        except aiohttp.ClientResponseError as exc:
            message = f"Anthropic API error {exc.status}: {exc.message or 'request failed'}"

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "status_code": exc.status,
                    "message": message,
                },
                span_context=payload.get("span_context") if isinstance(payload, dict) else None,
            )

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "status_code": exc.status,
                    "request_id": (exc.headers.get("request-id") if exc.headers else None),
                },
            }

        except (aiohttp.ClientError, TimeoutError) as exc:
            message = f"Anthropic transport error: {exc}"

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "message": message,
                },
                span_context=payload.get("span_context") if isinstance(payload, dict) else None,
            )

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "error_type": type(exc).__name__,
                },
            }

        except Exception as exc:
            message = f"Anthropic adapter failed: {exc}"

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "message": message,
                },
                span_context=payload.get("span_context") if isinstance(payload, dict) else None,
            )

            logger.exception("Claude adapter execution failed")

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "error_type": type(exc).__name__,
                },
            }
