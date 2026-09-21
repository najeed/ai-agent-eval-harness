# eval_runner/adapters/claude.py
"""
Anthropic Claude adapter for AgentV.

Implements the Anthropic Messages API over the shared AgentV adapter
infrastructure.

Design goals:
- Native Anthropic Messages API transport without an SDK dependency
- Canonical AgentV input compatibility
- Multi-turn conversation support
- Top-level system prompt handling
- Tool use and parallel tool-call normalization
- Thinking / structured output / prompt caching / MCP connector passthrough
- SSE streaming aggregation with fail-closed malformed-event handling
- Provider-native usage, stop-reason, citation and request-id telemetry
- Shared lifecycle-scoped connection pooling and retry behavior from common.py
- Trace-context propagation
- No false-success on empty, malformed, partial or provider-error responses
- No API-key or full request-body duplication in normalized evidence metadata
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Any

import aiohttp

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import AdapterSessionPool, BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

_TRACEPARENT_RE = re.compile(
    r"^[\da-f]{2}-[\da-f]{32}-[\da-f]{16}-[\da-f]{2}$",
    re.IGNORECASE,
)

_RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 502, 503, 504})


class ClaudeAdapterError(RuntimeError):
    """Raised for provider-level Claude adapter failures."""


class ClaudeAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native Anthropic Messages API adapter.

    Protocol:
        claude

    Wire API:
        POST /v1/messages
    """

    def __init__(self, session_pool: AdapterSessionPool | None = None):
        BaseAdapter.__init__(
            self,
            name="claude",
            session_pool=session_pool,
        )

    def on_discover_adapters(self, registry: Any):
        """Register the Claude provider adapter."""
        registry.register("claude", self.execute_claude_query)

    # ------------------------------------------------------------------
    # Boundary resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _traceparent(payload: dict[str, Any]) -> str | None:
        span_context = payload.get("span_context")
        if not isinstance(span_context, dict):
            return None

        traceparent = span_context.get("traceparent")
        if not isinstance(traceparent, str):
            return None

        traceparent = traceparent.strip()

        if not _TRACEPARENT_RE.fullmatch(traceparent):
            return None

        return traceparent

    @staticmethod
    def _resolve_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Resolve canonical Anthropic messages.

        Priority:
            messages
            history
            task_description
            task
            prompt
            input
        """
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        if raw_messages is not None:
            if not isinstance(raw_messages, list):
                raise ClaudeAdapterError("'messages' must be a list.")

            messages: list[dict[str, Any]] = []

            for index, message in enumerate(raw_messages):
                if not isinstance(message, dict):
                    raise ClaudeAdapterError(f"Message at index {index} must be an object.")

                role = message.get("role")

                if not isinstance(role, str) or not role.strip():
                    raise ClaudeAdapterError(f"Message at index {index} is missing a valid role.")

                role = role.strip()

                if role not in {"user", "assistant", "system"}:
                    raise ClaudeAdapterError(
                        f"Unsupported Claude message role at index {index}: {role!r}."
                    )

                if "content" not in message:
                    raise ClaudeAdapterError(
                        f"Message at index {index} is missing required 'content'."
                    )

                normalized = dict(message)
                normalized["role"] = role

                # `name` is not a supported Messages API message field.
                normalized.pop("name", None)

                messages.append(normalized)

            return messages

        for key in ("task_description", "task", "prompt", "input"):
            value = payload.get(key)

            if value is None:
                continue

            if isinstance(value, str):
                text = value
            else:
                try:
                    text = json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                except (TypeError, ValueError) as exc:
                    raise ClaudeAdapterError(
                        f"Unable to serialize Claude input from '{key}'."
                    ) from exc

            if text.strip():
                return [
                    {
                        "role": "user",
                        "content": text,
                    }
                ]

        raise ClaudeAdapterError(
            "Claude adapter received no input. Provide 'messages' "
            "or one of 'task_description', 'task', 'prompt', or 'input'."
        )

    @staticmethod
    def _resolve_system_prompt(
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> str | list[dict[str, Any]] | None:
        """
        Convert system-role messages into Anthropic's top-level system field.

        Explicit payload configuration takes precedence.
        """
        explicit = payload.get("system")

        if explicit is None:
            explicit = payload.get("system_prompt")

        if explicit is None:
            metadata = payload.get("metadata")

            if isinstance(metadata, dict):
                explicit = metadata.get("system")

                if explicit is None:
                    explicit = metadata.get("system_prompt")

        system_blocks: list[Any] = []

        for message in messages:
            if message.get("role") != "system":
                continue

            content = message.get("content")

            if isinstance(content, list):
                system_blocks.extend(content)
            elif content is not None:
                system_blocks.append(
                    {
                        "type": "text",
                        "text": str(content),
                    }
                )

        if explicit is not None:
            if isinstance(explicit, (str, list)):
                return explicit

            raise ClaudeAdapterError(
                "'system'/'system_prompt' must be a string or content-block list."
            )

        if not system_blocks:
            return None

        if len(system_blocks) == 1:
            first = system_blocks[0]

            if (
                isinstance(first, dict)
                and first.get("type") == "text"
                and isinstance(first.get("text"), str)
            ):
                return str(first["text"])

        return system_blocks

    @staticmethod
    def _strip_system_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [message for message in messages if message.get("role") != "system"]

    @staticmethod
    def _resolve_auth(payload: dict[str, Any]) -> str:
        api_key = (
            payload.get("api_key")
            or payload.get("anthropic_api_key")
            or config.ANTHROPIC_API_KEY
            or os.getenv("ANTHROPIC_API_KEY")
        )

        if not api_key:
            raise ClaudeAdapterError("Anthropic API key missing.")

        api_key = str(api_key).strip()

        if not api_key:
            raise ClaudeAdapterError("Anthropic API key is empty.")

        return api_key

    @staticmethod
    def _resolve_url(
        payload: dict[str, Any],
        url: str | None,
    ) -> str:
        endpoint = (
            url
            or payload.get("url")
            or payload.get("base_url")
            or config.ANTHROPIC_BASE_URL
            or "https://api.anthropic.com/v1/messages"
        )

        endpoint = str(endpoint).strip().rstrip("/")

        if not endpoint:
            raise ClaudeAdapterError("Anthropic endpoint is empty.")

        if endpoint.endswith("/messages"):
            return endpoint

        if endpoint.endswith("/v1"):
            return f"{endpoint}/messages"

        if endpoint.endswith("/v1/"):
            return f"{endpoint}messages"

        return f"{endpoint}/v1/messages"

    @staticmethod
    def _resolve_headers(
        payload: dict[str, Any],
        api_key: str,
        *,
        stream: bool,
    ) -> dict[str, str]:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": str(
                payload.get("anthropic_version")
                or payload.get("api_version")
                or config.ANTHROPIC_VERSION
                or DEFAULT_ANTHROPIC_VERSION
            ),
            "content-type": "application/json",
            "accept": "text/event-stream" if stream else "application/json",
        }

        traceparent = ClaudeAdapterPlugin._traceparent(payload)

        if traceparent:
            headers["traceparent"] = traceparent

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        beta_values = (
            payload.get("anthropic_beta")
            or payload.get("anthropic_betas")
            or metadata.get("anthropic_beta")
            or metadata.get("anthropic_betas")
        )

        if isinstance(beta_values, str):
            beta_values = [beta_values]

        if isinstance(beta_values, (list, tuple, set)):
            values = [str(value).strip() for value in beta_values if str(value).strip()]

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
    def _resolve_model(payload: dict[str, Any]) -> str:
        model = payload.get("model") or payload.get("anthropic_model") or config.ANTHROPIC_MODEL

        if not model:
            raise ClaudeAdapterError("Anthropic model is required.")

        model = str(model).strip()

        if not model:
            raise ClaudeAdapterError("Anthropic model is empty.")

        return model

    @staticmethod
    def _resolve_max_tokens(payload: dict[str, Any]) -> int:
        raw_value = payload.get(
            "max_tokens",
            config.LLM_MAX_TOKENS,
        )

        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ClaudeAdapterError("'max_tokens' must be an integer.") from exc

        if value <= 0:
            raise ClaudeAdapterError("'max_tokens' must be greater than zero.")

        return value

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_supported_fields(
        payload: dict[str, Any],
        request: dict[str, Any],
    ) -> None:
        """
        Copy only provider-recognized request fields.

        Harness/runtime metadata is deliberately excluded.
        """
        supported_fields = (
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
            "context_management",
            "mcp_servers",
            "speed",
        )

        for field in supported_fields:
            if field in payload and payload[field] is not None:
                request[field] = payload[field]

    @classmethod
    def _build_request(
        cls,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        messages = cls._resolve_messages(payload)
        system_prompt = cls._resolve_system_prompt(payload, messages)

        messages = cls._strip_system_messages(messages)

        if not messages:
            raise ClaudeAdapterError(
                "Claude Messages API requires at least one user or assistant message."
            )

        request: dict[str, Any] = {
            "model": cls._resolve_model(payload),
            "max_tokens": cls._resolve_max_tokens(payload),
            "messages": messages,
        }

        if system_prompt is not None:
            request["system"] = system_prompt

        cls._copy_supported_fields(payload, request)

        return request, str(request["model"])

    # ------------------------------------------------------------------
    # Evidence / diagnostics
    # ------------------------------------------------------------------

    @staticmethod
    def _request_fingerprint(request: dict[str, Any]) -> str:
        canonical = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_summary(
        request: dict[str, Any],
    ) -> dict[str, Any]:
        messages = request.get("messages")
        tools = request.get("tools")

        return {
            "model": request.get("model"),
            "message_count": (len(messages) if isinstance(messages, list) else None),
            "tool_count": (len(tools) if isinstance(tools, list) else None),
            "stream": bool(request.get("stream", False)),
            "has_system": "system" in request,
            "has_thinking": "thinking" in request,
            "has_output_config": "output_config" in request,
            "has_mcp_servers": "mcp_servers" in request,
        }

    @staticmethod
    def _provider_request_id(
        data: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        if isinstance(data, dict):
            request_id = data.get("request_id")

            if isinstance(request_id, str) and request_id:
                return request_id

        if headers:
            for key in (
                "request-id",
                "x-request-id",
                "anthropic-request-id",
            ):
                value = headers.get(key)

                if value:
                    return str(value)

        return None

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _usage_metadata(
        cls,
        usage: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(usage, dict):
            return {}

        input_tokens = cls._safe_int(usage.get("input_tokens"))
        output_tokens = cls._safe_int(usage.get("output_tokens"))

        cache_creation = cls._safe_int(usage.get("cache_creation_input_tokens"))
        cache_read = cls._safe_int(usage.get("cache_read_input_tokens"))

        total_tokens = input_tokens + output_tokens

        normalized = dict(usage)

        normalized.update(
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            }
        )

        return normalized

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        parts: list[str] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text")

                if text is not None:
                    parts.append(str(text))

        return "".join(parts).strip()

    @staticmethod
    def _extract_thinking(
        content: list[Any],
    ) -> list[dict[str, Any]]:
        thinking: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            if block.get("type") in {
                "thinking",
                "redacted_thinking",
            }:
                thinking.append(dict(block))

        return thinking

    @staticmethod
    def _extract_tool_calls(
        content: list[Any],
    ) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            if block.get("type") != "tool_use":
                continue

            name = block.get("name")
            tool_id = block.get("id")
            tool_input = block.get("input", {})

            if not isinstance(name, str) or not name.strip():
                raise ClaudeAdapterError(
                    "Anthropic returned a tool_use block without a valid name."
                )

            if not isinstance(tool_input, dict):
                raise ClaudeAdapterError(f"Anthropic tool '{name}' returned non-object input.")

            tool_calls.append(
                {
                    "tool": name,
                    "params": tool_input,
                    "call_id": tool_id,
                    "id": tool_id,
                }
            )

        return tool_calls

    @staticmethod
    def _extract_citations(
        content: list[Any],
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            value = block.get("citations")

            if isinstance(value, list):
                citations.extend(item for item in value if isinstance(item, dict))

        return citations

    @classmethod
    def _normalize_message_response(
        cls,
        data: dict[str, Any],
        *,
        response_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ClaudeAdapterError("Anthropic returned a non-object response.")

        if data.get("type") == "error":
            error_obj = data.get("error")

            if isinstance(error_obj, dict):
                message = (
                    error_obj.get("message") or error_obj.get("type") or "Anthropic API error."
                )
                error_type = error_obj.get("type")
            else:
                message = str(error_obj or "Anthropic API error.")
                error_type = None

            return {
                "status": "error",
                "action": "error",
                "message": str(message),
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "error_type": error_type,
                    "request_id": cls._provider_request_id(
                        data,
                        response_headers,
                    ),
                },
            }

        content = data.get("content")

        if not isinstance(content, list):
            raise ClaudeAdapterError("Anthropic response is missing a valid 'content' array.")

        output = cls._extract_text(content)
        thinking = cls._extract_thinking(content)
        tool_calls = cls._extract_tool_calls(content)
        citations = cls._extract_citations(content)

        stop_reason = data.get("stop_reason")
        stop_sequence = data.get("stop_sequence")
        stop_details = data.get("stop_details")

        usage = cls._usage_metadata(data.get("usage"))

        request_id = cls._provider_request_id(
            data,
            response_headers,
        )

        if tool_calls:
            if len(tool_calls) == 1:
                call = tool_calls[0]

                result = {
                    "status": "success",
                    "action": "call_tool",
                    "output": output,
                    "content": output,
                    "tool_name": call["tool"],
                    "tool_params": call["params"],
                    "tool_calls": tool_calls,
                }
            else:
                result = {
                    "status": "success",
                    "action": "call_multiple_tools",
                    "output": output,
                    "content": output,
                    "tool_calls": tool_calls,
                }

        elif output:
            result = {
                "status": "success",
                "output": output,
                "content": output,
                "action": DualNormalizationHub.normalize_text(output),
            }

        elif thinking:
            raise ClaudeAdapterError(
                "Anthropic returned thinking content without usable output or tool calls."
            )

        else:
            raise ClaudeAdapterError("Anthropic returned neither usable text nor tool calls.")

        result.update(
            {
                "thinking": thinking,
                "citations": citations,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "response_id": data.get("id"),
                    "request_id": request_id,
                    "response_type": data.get("type"),
                    "model": data.get("model"),
                    "role": data.get("role"),
                    "stop_reason": stop_reason,
                    "stop_sequence": stop_sequence,
                    "stop_details": stop_details,
                    "usage": usage,
                    "container": data.get("container"),
                    "service_tier": data.get("service_tier"),
                    "raw_content_blocks": content,
                },
            }
        )

        if usage:
            emit(
                "metric_update",
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                },
            )

        return result

    # ------------------------------------------------------------------
    # SSE handling
    # ------------------------------------------------------------------

    @classmethod
    def _aggregate_sse_events(
        cls,
        events: list[tuple[str | None, dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """
        Reconstruct the final Anthropic Message from SSE events.

        Returns:
            (message, response diagnostics)
        """
        if not events:
            raise ClaudeAdapterError("Anthropic streaming response contained no events.")

        message: dict[str, Any] = {
            "type": "message",
            "content": [],
            "usage": {},
        }

        block_map: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        diagnostics: dict[str, str] = {}

        saw_message_start = False
        saw_message_stop = False

        for explicit_event_type, data in events:
            event_type = explicit_event_type or data.get("type")

            if event_type == "ping":
                continue

            if event_type == "error":
                error_obj = data.get("error")

                if isinstance(error_obj, dict):
                    message_text = (
                        error_obj.get("message")
                        or error_obj.get("type")
                        or "Anthropic streaming API error."
                    )
                else:
                    message_text = str(error_obj or "Anthropic streaming API error.")

                request_id = data.get("request_id")

                if request_id:
                    diagnostics["request_id"] = str(request_id)

                raise ClaudeAdapterError(str(message_text))

            if event_type == "message_start":
                saw_message_start = True

                start_message = data.get("message")

                if isinstance(start_message, dict):
                    message.update(start_message)

                    request_id = start_message.get("request_id")

                    if request_id:
                        diagnostics["request_id"] = str(request_id)

                    initial_usage = start_message.get("usage")

                    if isinstance(initial_usage, dict):
                        usage.update(initial_usage)

                continue

            if event_type == "content_block_start":
                index = data.get("index")
                block = data.get("content_block")

                if isinstance(index, int) and isinstance(block, dict):
                    block_map[index] = dict(block)

                continue

            if event_type == "content_block_delta":
                index = data.get("index")
                delta = data.get("delta")

                if not isinstance(index, int) or not isinstance(delta, dict):
                    raise ClaudeAdapterError(
                        "Anthropic returned an invalid content_block_delta event."
                    )

                block = block_map.setdefault(
                    index,
                    {},
                )

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

                    partial_json = delta.get(
                        "partial_json",
                        "",
                    )

                    if not isinstance(
                        partial_json,
                        str,
                    ):
                        raise ClaudeAdapterError(
                            "Anthropic input_json_delta contained non-string partial_json."
                        )

                    block["_partial_json"] = f"{block.get('_partial_json', '')}{partial_json}"

                elif delta_type == "citations_delta":
                    citation = delta.get("citation")

                    if citation is not None:
                        if not isinstance(
                            citation,
                            dict,
                        ):
                            raise ClaudeAdapterError(
                                "Anthropic citations_delta contained a non-object citation."
                            )

                        block.setdefault(
                            "citations",
                            [],
                        ).append(citation)

                continue

            if event_type == "content_block_stop":
                index = data.get("index")

                if not isinstance(index, int):
                    raise ClaudeAdapterError(
                        "Anthropic content_block_stop contained an invalid index."
                    )

                block = block_map.get(index)

                if block is None:
                    raise ClaudeAdapterError(f"Anthropic stopped unknown content block {index}.")

                partial_json = block.pop(
                    "_partial_json",
                    None,
                )

                if partial_json is not None:
                    if not partial_json.strip():
                        block["input"] = {}
                    else:
                        try:
                            parsed_input = json.loads(partial_json)
                        except json.JSONDecodeError as exc:
                            raise ClaudeAdapterError(
                                f"Anthropic returned malformed tool input JSON: {exc.msg}."
                            ) from exc

                        if not isinstance(
                            parsed_input,
                            dict,
                        ):
                            raise ClaudeAdapterError(
                                "Anthropic tool input must decode to an object."
                            )

                        block["input"] = parsed_input

                continue

            if event_type == "message_delta":
                delta = data.get("delta")
                delta_usage = data.get("usage")

                if isinstance(delta, dict):
                    if "stop_reason" in delta:
                        message["stop_reason"] = delta["stop_reason"]

                    if "stop_sequence" in delta:
                        message["stop_sequence"] = delta["stop_sequence"]

                    if "stop_details" in delta:
                        message["stop_details"] = delta["stop_details"]

                if isinstance(delta_usage, dict):
                    usage.update(delta_usage)

                continue

            if event_type == "message_stop":
                saw_message_stop = True
                continue

            raise ClaudeAdapterError(
                f"Anthropic returned unsupported SSE event type: {event_type!r}."
            )

        if not saw_message_start:
            raise ClaudeAdapterError("Anthropic stream never emitted message_start.")

        # `message_stop` is normally emitted by Anthropic. Do not fabricate
        # content if a proxy truncates the stream.
        if not saw_message_stop:
            raise ClaudeAdapterError("Anthropic stream ended without message_stop.")

        ordered_blocks = [block_map[index] for index in sorted(block_map)]

        message["content"] = ordered_blocks
        message["usage"] = usage

        return message, diagnostics

    async def _read_stream(
        self,
        response: aiohttp.ClientResponse,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """
        Parse an Anthropic SSE response.

        Supports:
        - event/data pairs
        - multiline data fields
        - comments / keep-alives
        - provider error events
        - terminal message_stop validation
        """
        events: list[tuple[str | None, dict[str, Any]]] = []

        current_event: str | None = None
        data_lines: list[str] = []

        async for raw_line in response.content:
            line = raw_line.decode(
                "utf-8",
                errors="replace",
            ).rstrip("\r\n")

            if line == "":
                if data_lines:
                    raw_data = "\n".join(data_lines)

                    if raw_data != "[DONE]":
                        try:
                            parsed = json.loads(raw_data)
                        except json.JSONDecodeError as exc:
                            raise ClaudeAdapterError(
                                f"Anthropic SSE returned invalid JSON event: {raw_data[:1000]}"
                            ) from exc

                        if not isinstance(
                            parsed,
                            dict,
                        ):
                            raise ClaudeAdapterError(
                                "Anthropic SSE event must decode to an object."
                            )

                        events.append(
                            (
                                current_event,
                                parsed,
                            )
                        )

                current_event = None
                data_lines = []
                continue

            if line.startswith(":"):
                continue

            if line.startswith("event:"):
                current_event = line[6:].strip() or None
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue

        if data_lines:
            raw_data = "\n".join(data_lines)

            if raw_data != "[DONE]":
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    raise ClaudeAdapterError(
                        f"Anthropic SSE returned invalid trailing JSON event: {raw_data[:1000]}"
                    ) from exc

                if not isinstance(
                    parsed,
                    dict,
                ):
                    raise ClaudeAdapterError(
                        "Anthropic trailing SSE event must decode to an object."
                    )

                events.append(
                    (
                        current_event,
                        parsed,
                    )
                )

        return self._aggregate_sse_events(events)

    # ------------------------------------------------------------------
    # HTTP execution
    # ------------------------------------------------------------------

    @staticmethod
    async def _read_error_body(
        response: aiohttp.ClientResponse,
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            raw = await response.read()
        except aiohttp.ClientError as exc:
            return str(exc), None

        if not raw:
            return "", None

        text = raw.decode(
            response.charset or "utf-8",
            errors="replace",
        )

        try:
            parsed = json.loads(text)

            if isinstance(parsed, dict):
                return text, parsed
        except json.JSONDecodeError:
            pass

        return text, None

    @staticmethod
    def _extract_error_message(
        status: int,
        body_text: str,
        body_json: dict[str, Any] | None,
    ) -> str:
        if isinstance(body_json, dict):
            error_obj = body_json.get("error")

            if isinstance(error_obj, dict):
                message = error_obj.get("message") or error_obj.get("type")

                if message:
                    return str(message)

            message = body_json.get("message")

            if message:
                return str(message)

        body_text = body_text.strip()

        if body_text:
            return body_text[:4000]

        return f"Anthropic API returned HTTP {status}."

    async def _post(
        self,
        endpoint: str,
        headers: dict[str, str],
        request: dict[str, Any],
        *,
        stream: bool,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        session = await self.get_session()

        timeout = aiohttp.ClientTimeout(total=max(1.0, timeout_seconds))

        async with session.post(
            endpoint,
            json=request,
            headers=headers,
            timeout=timeout,
        ) as response:
            response_headers = dict(response.headers)

            if not 200 <= response.status < 300:
                body_text, body_json = await self._read_error_body(response)

                message = self._extract_error_message(
                    response.status,
                    body_text,
                    body_json,
                )

                request_id = self._provider_request_id(
                    body_json,
                    response_headers,
                )

                if request_id:
                    message = f"{message} (request_id={request_id})"

                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=message,
                    headers=response.headers,
                )

            if stream:
                data, stream_diagnostics = await self._read_stream(response)

                return {
                    "__claude_stream_result__": data,
                    "__response_headers__": response_headers,
                    "__stream_diagnostics__": stream_diagnostics,
                }

            try:
                data = await response.json(content_type=None)
            except (
                aiohttp.ContentTypeError,
                json.JSONDecodeError,
            ) as exc:
                raise ClaudeAdapterError("Anthropic returned a non-JSON success response.") from exc

            if not isinstance(data, dict):
                raise ClaudeAdapterError("Anthropic returned a non-object JSON response.")

            return {
                "__claude_response__": data,
                "__response_headers__": response_headers,
            }

    # ------------------------------------------------------------------
    # Public adapter entry point
    # ------------------------------------------------------------------

    async def execute_claude_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                raise ClaudeAdapterError("Claude adapter payload must be an object.")

            request, model = self._build_request(payload)

            stream = bool(
                request.get(
                    "stream",
                    False,
                )
            )

            endpoint = self._resolve_url(
                payload,
                url,
            )

            api_key = self._resolve_auth(payload)

            headers = self._resolve_headers(
                payload,
                api_key,
                stream=stream,
            )

            timeout_raw = payload.get(
                "timeout",
                config.DEFAULT_ADAPTER_TIMEOUT,
            )

            try:
                timeout_seconds = float(timeout_raw)
            except (
                TypeError,
                ValueError,
            ):
                timeout_seconds = float(config.DEFAULT_ADAPTER_TIMEOUT)

            timeout_seconds = max(
                1.0,
                timeout_seconds,
            )

            request_fingerprint = self._request_fingerprint(request)

            request_summary = self._request_summary(request)

            emit(
                CoreEvents.CHAIN_START,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "model": model,
                    "endpoint": endpoint,
                    "stream": stream,
                    "request_fingerprint": request_fingerprint,
                },
                span_context=payload.get("span_context"),
            )

            async def _call() -> dict[str, Any]:
                return await self._post(
                    endpoint,
                    headers,
                    request,
                    stream=stream,
                    timeout_seconds=timeout_seconds,
                )

            response_wrapper = await self.call_with_retry(
                _call,
                max_attempts=self.provider_retry_attempts(payload, stream=stream),
                retry_codes=set(_RETRYABLE_HTTP_STATUS_CODES),
                deadline=payload.get("retry_deadline"),
            )

            response_headers = response_wrapper.get(
                "__response_headers__",
                {},
            )

            stream_diagnostics = response_wrapper.get(
                "__stream_diagnostics__",
                {},
            )

            if stream:
                data = response_wrapper.get("__claude_stream_result__")

                if not isinstance(
                    data,
                    dict,
                ):
                    raise ClaudeAdapterError(
                        "Anthropic streaming response did not produce a final message object."
                    )

            else:
                data = response_wrapper.get("__claude_response__")

                if not isinstance(
                    data,
                    dict,
                ):
                    raise ClaudeAdapterError(
                        "Anthropic response wrapper did not contain a JSON object."
                    )

            normalized = self._normalize_message_response(
                data,
                response_headers=response_headers,
            )

            normalized.setdefault(
                "metadata",
                {},
            )

            request_id = (
                normalized["metadata"].get("request_id")
                or stream_diagnostics.get("request_id")
                or self._provider_request_id(
                    data,
                    response_headers,
                )
            )

            normalized["metadata"].update(
                {
                    "endpoint": endpoint,
                    "execution_mode": "native",
                    "adapter_version": "2.1.0",
                    "request_fingerprint": request_fingerprint,
                    "request_summary": request_summary,
                    "request_id": request_id,
                    "streaming": stream,
                }
            )

            if stream_diagnostics:
                normalized["metadata"]["stream_diagnostics"] = stream_diagnostics

            if normalized.get("status") == "success":
                emit(
                    CoreEvents.CHAIN_END,
                    {
                        "adapter": "claude",
                        "provider": "anthropic",
                        "model": model,
                        "response_id": normalized.get(
                            "metadata",
                            {},
                        ).get("response_id"),
                        "request_id": request_id,
                        "stop_reason": normalized.get(
                            "metadata",
                            {},
                        ).get("stop_reason"),
                        "action": normalized.get("action"),
                    },
                    span_context=payload.get("span_context"),
                )
            else:
                emit(
                    CoreEvents.ERROR,
                    {
                        "adapter": "claude",
                        "provider": "anthropic",
                        "model": model,
                        "request_id": request_id,
                        "message": normalized.get("message"),
                    },
                    span_context=payload.get("span_context"),
                )

            return normalized

        except asyncio.CancelledError:
            raise

        except aiohttp.ClientResponseError as exc:
            message = f"Anthropic API error {exc.status}: {exc.message or 'request failed'}"

            request_id = exc.headers.get("request-id") if exc.headers else None

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "status_code": exc.status,
                    "request_id": request_id,
                    "message": message,
                },
                span_context=(payload.get("span_context") if isinstance(payload, dict) else None),
            )

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "status_code": exc.status,
                    "request_id": request_id,
                    "retryable": exc.status in _RETRYABLE_HTTP_STATUS_CODES,
                },
            }

        except (
            aiohttp.ClientError,
            TimeoutError,
        ) as exc:
            message = f"Anthropic transport error: {exc}"

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "message": message,
                    "error_type": type(exc).__name__,
                },
                span_context=(payload.get("span_context") if isinstance(payload, dict) else None),
            )

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "claude",
                    "provider": "anthropic",
                    "error_type": type(exc).__name__,
                    "retryable": True,
                },
            }

        except ClaudeAdapterError as exc:
            message = str(exc)

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "claude",
                    "provider": "anthropic",
                    "message": message,
                    "error_type": type(exc).__name__,
                },
                span_context=(payload.get("span_context") if isinstance(payload, dict) else None),
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
                    "error_type": type(exc).__name__,
                },
                span_context=(payload.get("span_context") if isinstance(payload, dict) else None),
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
