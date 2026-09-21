# eval_runner/adapters/openai.py
from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import AdapterSessionPool, BaseAdapter, DualNormalizationHub

_TRACEPARENT_REGEX = re.compile(r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_TERMINAL_RESPONSES_STATUS = {"completed", "incomplete", "failed"}
_STREAM_SENTINEL = "[DONE]"


class OpenAIAdapterError(RuntimeError):
    """Adapter-local error for deterministic OpenAI transport/response failures."""


class OpenAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production OpenAI adapter.

    Supports:
      - OpenAI Responses API
      - OpenAI Chat Completions API
      - OpenAI-compatible Chat Completions endpoints
      - non-streaming and streaming execution
      - AgentV task / message / history input contracts
      - tool/function calls
      - structured output configuration
      - reasoning configuration
      - token telemetry
      - W3C traceparent propagation
      - lifecycle-scoped aiohttp connection pooling
      - retry handling through BaseAdapter
      - normalized AgentV action/output contract

    The adapter deliberately keeps provider-specific request/response semantics
    here while delegating pooling and retry mechanics to common.py.
    """

    def __init__(
        self,
        session_pool: AdapterSessionPool | None = None,
    ) -> None:
        BaseAdapter.__init__(
            self,
            name="openai",
            session_pool=session_pool,
        )

    def on_discover_adapters(self, registry: Any) -> None:
        """Register the OpenAI provider adapter."""
        registry.register("openai", self.execute_openai_query)

    async def execute_openai_query(
        self,
        payload: dict[str, Any],
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute an OpenAI request and normalize it to the AgentV adapter contract.

        Accepted inputs include:
          task_description | task | prompt | input
          messages
          history
          system_prompt
          model
          api_mode: responses | chat_completions
          tools
          tool_choice
          parallel_tool_calls
          temperature
          top_p
          max_output_tokens
          max_completion_tokens
          reasoning
          response_format
          text
          seed
          service_tier
          store
          stream
          timeout
        """
        try:
            effective_payload = self._merge_runtime_payload(payload)

            api_key = self._resolve_api_key(effective_payload)
            if not api_key:
                raise OpenAIAdapterError(
                    "OpenAI API key missing. Set OPENAI_API_KEY or provide payload.api_key."
                )

            endpoint_hint = (
                base_url
                or effective_payload.get("base_url")
                or effective_payload.get("url")
                or effective_payload.get("endpoint")
                or config.OPENAI_BASE_URL
            )

            api_mode = self._resolve_api_mode(
                effective_payload,
                str(endpoint_hint),
            )
            endpoint = self._resolve_endpoint(
                str(endpoint_hint),
                api_mode,
            )

            model = self._resolve_model(effective_payload)
            messages, system_prompt = self._build_input_messages(effective_payload)

            if not messages:
                raise OpenAIAdapterError(
                    "OpenAI request contains no user/assistant input. "
                    "Expected task_description, task, prompt, input, messages, or history."
                )

            stream = self._resolve_bool(effective_payload.get("stream"), default=False)

            headers = self._build_headers(
                effective_payload,
                api_key=api_key,
            )

            request_body = (
                self._build_responses_payload(
                    payload=effective_payload,
                    model=model,
                    messages=messages,
                    system_prompt=system_prompt,
                    stream=stream,
                )
                if api_mode == "responses"
                else self._build_chat_payload(
                    payload=effective_payload,
                    model=model,
                    messages=messages,
                    stream=stream,
                )
            )

            if stream:
                response_json, response_headers = await self.call_with_retry(
                    self._stream_request,
                    endpoint,
                    headers,
                    request_body,
                    api_mode,
                    max_attempts=self.provider_retry_attempts(effective_payload, stream=True),
                    retry_codes=_RETRYABLE_STATUS_CODES,
                )
            else:
                response_json, response_headers = await self.call_with_retry(
                    self._post_json,
                    endpoint,
                    headers,
                    request_body,
                    max_attempts=self.provider_retry_attempts(effective_payload),
                    retry_codes=_RETRYABLE_STATUS_CODES,
                )

            if not isinstance(response_json, dict):
                raise OpenAIAdapterError(
                    f"OpenAI returned a non-object JSON response: {type(response_json).__name__}"
                )

            if api_mode == "responses":
                normalized = self._normalize_responses(response_json)
            else:
                normalized = self._normalize_chat_completion(response_json)

            usage = normalized.pop("_usage", {}) or {}
            provider_model = normalized.pop("_model", model) or model
            provider_status = normalized.pop("_provider_status", None)
            provider_response_id = normalized.pop("_response_id", None)
            finish_reason = normalized.pop("_finish_reason", None)
            incomplete_details = normalized.pop("_incomplete_details", None)
            raw_tool_calls = normalized.pop("_raw_tool_calls", [])

            if usage:
                self._emit_usage(usage)

            metadata = {
                "framework": "openai",
                "provider": "openai",
                "api_mode": api_mode,
                "model": provider_model,
                "endpoint": endpoint,
                "response_id": provider_response_id,
                "provider_status": provider_status,
                "finish_reason": finish_reason,
                "incomplete_details": incomplete_details,
                "usage": usage,
                "stream": stream,
                "request_id": response_headers.get("x-request-id"),
            }

            if raw_tool_calls:
                metadata["tool_call_count"] = len(raw_tool_calls)

            normalized["metadata"] = self._drop_none(metadata)
            normalized.setdefault("status", "success")

            return normalized

        except asyncio.CancelledError:
            raise

        except aiohttp.ClientResponseError as exc:
            return {
                "status": "error",
                "action": "error",
                "message": self._format_http_error(exc),
                "metadata": {
                    "framework": "openai",
                    "provider": "openai",
                    "status_code": exc.status,
                    "request_id": (exc.headers.get("x-request-id") if exc.headers else None),
                },
            }

        except Exception as exc:
            emit(
                "adapter_error",
                {
                    "adapter": "openai",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                },
            )

            return {
                "status": "error",
                "action": "error",
                "message": str(exc),
                "metadata": {
                    "framework": "openai",
                    "provider": "openai",
                    "error_type": type(exc).__name__,
                },
            }

    # ------------------------------------------------------------------
    # Payload / configuration resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_runtime_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Preserve compatibility with both the current lightweight runtime
        payload and richer TurnContext/input_payload representations.
        """
        if not isinstance(payload, dict):
            raise OpenAIAdapterError("OpenAI adapter payload must be an object.")

        merged = dict(payload)

        for nested_key in (
            "input_payload",
            "request",
            "agent_input",
        ):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                for key, value in nested.items():
                    merged.setdefault(key, value)

        turn_context = payload.get("turn_context")
        if isinstance(turn_context, dict):
            for key in (
                "history",
                "messages",
                "system_prompt",
                "input_payload",
                "metadata",
                "span_context",
            ):
                value = turn_context.get(key)
                if value is not None and key not in merged:
                    merged[key] = value

            nested_input = turn_context.get("input_payload")
            if isinstance(nested_input, dict):
                for key, value in nested_input.items():
                    merged.setdefault(key, value)

        return merged

    @staticmethod
    def _resolve_api_key(payload: dict[str, Any]) -> str | None:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        value = (
            payload.get("api_key")
            or metadata.get("api_key")
            or config.OPENAI_API_KEY
            or os.getenv("OPENAI_API_KEY")
        )

        if value is None:
            return None

        value = str(value).strip()
        return value or None

    @staticmethod
    def _resolve_model(payload: dict[str, Any]) -> str:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        model = payload.get("model") or metadata.get("model") or config.OPENAI_MODEL

        model = str(model).strip() if model is not None else ""
        if not model:
            raise OpenAIAdapterError("OpenAI model is missing.")

        return model

    @staticmethod
    def _resolve_api_mode(
        payload: dict[str, Any],
        endpoint_hint: str,
    ) -> str:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        explicit = (
            payload.get("api_mode")
            or metadata.get("api_mode")
            or payload.get("openai_api")
            or metadata.get("openai_api")
        )

        if explicit:
            normalized = str(explicit).strip().lower().replace("-", "_").replace(" ", "_")

            aliases = {
                "responses": "responses",
                "response": "responses",
                "responses_api": "responses",
                "chat": "chat_completions",
                "chat_completions": "chat_completions",
                "chat_completion": "chat_completions",
                "chatcompletions": "chat_completions",
            }

            if normalized not in aliases:
                raise OpenAIAdapterError(
                    f"Unsupported OpenAI api_mode '{explicit}'. "
                    "Use 'responses' or 'chat_completions'."
                )

            return aliases[normalized]

        lowered = str(endpoint_hint).lower()

        if "/chat/completions" in lowered:
            return "chat_completions"

        if "/responses" in lowered:
            return "responses"

        host = urlsplit(str(endpoint_hint)).netloc.lower()

        if host in {"api.openai.com", "api.openai.com:443"}:
            return "responses"

        return "chat_completions"

    @staticmethod
    def _resolve_endpoint(
        endpoint_hint: str,
        api_mode: str,
    ) -> str:
        endpoint = str(endpoint_hint).strip()

        if not endpoint:
            raise OpenAIAdapterError("OpenAI endpoint is empty.")

        parsed = urlsplit(endpoint)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise OpenAIAdapterError(
                f"Invalid OpenAI endpoint '{endpoint}'. Expected an absolute http(s) URL."
            )

        if parsed.fragment:
            raise OpenAIAdapterError("OpenAI endpoint must not contain a URL fragment.")

        path = parsed.path.rstrip("/")

        expected_suffix = "/responses" if api_mode == "responses" else "/chat/completions"

        if path.endswith(expected_suffix):
            return urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    path,
                    parsed.query,
                    "",
                )
            )

        opposite_suffix = "/chat/completions" if api_mode == "responses" else "/responses"

        if path.endswith(opposite_suffix):
            path = path[: -len(opposite_suffix)].rstrip("/")

        path = f"{path}{expected_suffix}" if path else expected_suffix

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                path,
                parsed.query,
                "",
            )
        )

    @staticmethod
    def _resolve_bool(
        value: Any,
        *,
        default: bool,
    ) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        normalized = str(value).strip().lower()

        if normalized in {"true", "1", "yes", "y", "on"}:
            return True

        if normalized in {"false", "0", "no", "n", "off"}:
            return False

        raise OpenAIAdapterError(f"Invalid boolean value '{value}'.")

    # ------------------------------------------------------------------
    # Input normalization
    # ------------------------------------------------------------------

    @classmethod
    def _build_input_messages(
        cls,
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        if raw_messages is None:
            raw_messages = (
                payload.get("input_payload", {}).get("messages")
                if isinstance(payload.get("input_payload"), dict)
                else None
            )

        messages: list[dict[str, Any]] = []

        if isinstance(raw_messages, list):
            for index, message in enumerate(raw_messages):
                messages.extend(
                    cls._normalize_input_message(
                        message,
                        index=index,
                    )
                )

        elif raw_messages is not None:
            raise OpenAIAdapterError("OpenAI messages/history must be an array.")

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        system_prompt = payload.get("system_prompt") or metadata.get("system_prompt")

        if system_prompt is not None:
            system_prompt = str(system_prompt).strip() or None

        if messages:
            has_system_message = any(
                message.get("role") in {"system", "developer"} for message in messages
            )

            if system_prompt and not has_system_message:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                )

            return messages, system_prompt

        current_input = (
            payload.get("task_description")
            if payload.get("task_description") is not None
            else payload.get("task")
        )

        if current_input is None:
            current_input = payload.get("prompt")

        if current_input is None:
            current_input = payload.get("input")

        if current_input is None:
            nested_input = payload.get("input_payload")
            if isinstance(nested_input, dict):
                current_input = nested_input.get("task_description")

                if current_input is None:
                    current_input = nested_input.get("prompt")

                if current_input is None:
                    current_input = nested_input.get("input")

        if current_input is None:
            return [], system_prompt

        content = cls._serialize_input(current_input)

        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": content,
            }
        )

        return messages, system_prompt

    @classmethod
    def _normalize_input_message(
        cls,
        message: Any,
        *,
        index: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(message, dict):
            raise OpenAIAdapterError(f"Invalid message at index {index}: expected an object.")

        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            raise OpenAIAdapterError(f"Invalid message at index {index}: missing role.")

        role = role.strip().lower()

        if role == "tool":
            return cls._normalize_tool_message(
                message,
                index=index,
            )

        if role not in {
            "system",
            "developer",
            "user",
            "assistant",
        }:
            raise OpenAIAdapterError(
                f"Invalid message at index {index}: unsupported role '{role}'."
            )

        normalized = dict(message)
        normalized["role"] = role

        if "content" not in normalized and role != "assistant":
            raise OpenAIAdapterError(f"Invalid message at index {index}: missing content.")

        if "content" in normalized:
            normalized["content"] = cls._normalize_message_content(normalized["content"])

        return [normalized]

    @classmethod
    def _normalize_tool_message(
        cls,
        message: dict[str, Any],
        *,
        index: int,
    ) -> list[dict[str, Any]]:
        tool_call_id = message.get("tool_call_id")

        if not tool_call_id:
            raise OpenAIAdapterError(
                f"Invalid tool message at index {index}: missing tool_call_id."
            )

        content = cls._serialize_input(message.get("content", ""))

        return [
            {
                "role": "tool",
                "tool_call_id": str(tool_call_id),
                "content": content,
            }
        ]

    @staticmethod
    def _normalize_message_content(content: Any) -> Any:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            return content

        if content is None:
            return ""

        return OpenAIAdapterPlugin._serialize_input(content)

    @staticmethod
    def _serialize_input(value: Any) -> str:
        if isinstance(value, str):
            return value

        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        except (TypeError, ValueError) as exc:
            raise OpenAIAdapterError(f"Unable to serialize OpenAI input: {exc}") from exc

    # ------------------------------------------------------------------
    # Request headers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_headers(
        payload: dict[str, Any],
        *,
        api_key: str,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        span_context = payload.get("span_context")
        if not isinstance(span_context, dict):
            turn_context = payload.get("turn_context")
            span_context = (
                turn_context.get("span_context") if isinstance(turn_context, dict) else None
            )

        if isinstance(span_context, dict):
            traceparent = span_context.get("traceparent")

            if isinstance(traceparent, str) and _TRACEPARENT_REGEX.fullmatch(traceparent):
                headers["traceparent"] = traceparent

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        organization = (
            payload.get("organization")
            or metadata.get("organization")
            or os.getenv("OPENAI_ORGANIZATION")
        )

        project = payload.get("project") or metadata.get("project") or os.getenv("OPENAI_PROJECT")

        client_request_id = payload.get("client_request_id") or metadata.get("client_request_id")

        if organization:
            headers["OpenAI-Organization"] = str(organization)

        if project:
            headers["OpenAI-Project"] = str(project)

        if client_request_id:
            headers["X-Client-Request-Id"] = str(client_request_id)

        extra_headers = payload.get("headers")

        if isinstance(extra_headers, dict):
            for key, value in extra_headers.items():
                if key is None or value is None:
                    continue

                key_str = str(key).strip()

                if not key_str:
                    continue

                lower_key = key_str.lower()

                if lower_key in {
                    "authorization",
                    "proxy-authorization",
                }:
                    continue

                headers[key_str] = str(value)

        return headers

    # ------------------------------------------------------------------
    # Request builders
    # ------------------------------------------------------------------

    @classmethod
    def _build_chat_payload(
        cls,
        *,
        payload: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": cls._messages_for_chat_api(messages),
            "stream": stream,
        }

        field_map = {
            "temperature": "temperature",
            "top_p": "top_p",
            "max_completion_tokens": "max_completion_tokens",
            "max_tokens": "max_tokens",
            "frequency_penalty": "frequency_penalty",
            "presence_penalty": "presence_penalty",
            "seed": "seed",
            "stop": "stop",
            "n": "n",
            "logprobs": "logprobs",
            "top_logprobs": "top_logprobs",
            "response_format": "response_format",
            "service_tier": "service_tier",
            "store": "store",
            "metadata": "metadata",
            "parallel_tool_calls": "parallel_tool_calls",
            "tool_choice": "tool_choice",
            "tools": "tools",
        }

        for source, target in field_map.items():
            if source in payload and payload[source] is not None:
                body[target] = payload[source]

        if (
            "max_output_tokens" in payload
            and "max_completion_tokens" not in body
            and "max_tokens" not in body
        ):
            body["max_completion_tokens"] = payload["max_output_tokens"]

        if stream:
            stream_options = payload.get("stream_options")

            if isinstance(stream_options, dict):
                body["stream_options"] = dict(stream_options)
            else:
                body["stream_options"] = {
                    "include_usage": True,
                }

        return body

    @staticmethod
    def _messages_for_chat_api(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role")

            if role == "developer":
                normalized.append(
                    {
                        **message,
                        "role": "developer",
                    }
                )
            else:
                normalized.append(dict(message))

        return normalized

    @classmethod
    def _build_responses_payload(
        cls,
        *,
        payload: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "input": cls._messages_for_responses_api(messages),
            "stream": stream,
        }

        if system_prompt:
            body["instructions"] = system_prompt

            body["input"] = [
                message
                for message in body["input"]
                if message.get("role") not in {"system", "developer"}
            ]

        field_map = {
            "temperature": "temperature",
            "top_p": "top_p",
            "max_output_tokens": "max_output_tokens",
            "parallel_tool_calls": "parallel_tool_calls",
            "tool_choice": "tool_choice",
            "tools": "tools",
            "reasoning": "reasoning",
            "text": "text",
            "service_tier": "service_tier",
            "store": "store",
            "metadata": "metadata",
            "truncation": "truncation",
            "include": "include",
            "prompt_cache_key": "prompt_cache_key",
            "previous_response_id": "previous_response_id",
        }

        for source, target in field_map.items():
            if source in payload and payload[source] is not None:
                body[target] = payload[source]

        if (
            "response_format" in payload
            and payload["response_format"] is not None
            and "text" not in body
        ):
            response_format = payload["response_format"]

            if isinstance(response_format, dict):
                body["text"] = {
                    "format": response_format,
                }

        return body

    @staticmethod
    def _messages_for_responses_api(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Convert Chat-style history into valid Responses input items.

        In particular, Chat Completions tool messages must become
        function_call_output items. Assistant tool_calls must become
        function_call items.
        """
        converted: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role")

            if role == "tool":
                converted.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(message["tool_call_id"]),
                        "output": OpenAIAdapterPlugin._serialize_input(message.get("content", "")),
                    }
                )
                continue

            tool_calls = message.get("tool_calls")

            if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
                assistant_copy = {
                    key: value for key, value in message.items() if key != "tool_calls"
                }

                if assistant_copy.get("content") not in {None, ""}:
                    converted.append(assistant_copy)

                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue

                    function = tool_call.get("function")

                    if not isinstance(function, dict):
                        continue

                    name = function.get("name")

                    if not name:
                        continue

                    arguments = function.get("arguments", "{}")

                    converted.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.get("id"),
                            "name": str(name),
                            "arguments": (
                                arguments
                                if isinstance(arguments, str)
                                else OpenAIAdapterPlugin._serialize_input(arguments)
                            ),
                        }
                    )

                continue

            converted.append(dict(message))

        return converted

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    async def _post_json(
        self,
        endpoint: str,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        session = await self.get_session()

        timeout = self._resolve_timeout(request_body)

        async with session.post(
            endpoint,
            json=request_body,
            headers=headers,
            timeout=timeout,
        ) as response:
            response_headers = dict(response.headers)
            data = await self._read_json_or_error(
                response,
            )

            if not 200 <= response.status < 300:
                self._raise_http_error(
                    response=response,
                    data=data,
                )

            if not isinstance(data, dict):
                raise OpenAIAdapterError(
                    f"OpenAI API returned unexpected JSON type: {type(data).__name__}"
                )

            return data, response_headers

    async def _stream_request(
        self,
        endpoint: str,
        headers: dict[str, str],
        request_body: dict[str, Any],
        api_mode: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        session = await self.get_session()

        timeout = self._resolve_timeout(request_body)

        async with session.post(
            endpoint,
            json=request_body,
            headers={
                **headers,
                "Accept": "text/event-stream",
            },
            timeout=timeout,
        ) as response:
            response_headers = dict(response.headers)

            if not 200 <= response.status < 300:
                data = await self._read_json_or_error(response)

                self._raise_http_error(
                    response=response,
                    data=data,
                )

            if api_mode == "responses":
                return await self._consume_responses_stream(
                    response,
                    response_headers,
                )

            return await self._consume_chat_stream(
                response,
                response_headers,
            )

    @staticmethod
    def _resolve_timeout(
        request_body: dict[str, Any],
    ) -> aiohttp.ClientTimeout:
        value = request_body.get("_agentv_timeout")

        if value is None:
            return aiohttp.ClientTimeout(
                total=float(config.DEFAULT_ADAPTER_TIMEOUT),
            )

        try:
            seconds = max(0.1, float(value))
        except (TypeError, ValueError):
            seconds = float(config.DEFAULT_ADAPTER_TIMEOUT)

        return aiohttp.ClientTimeout(total=seconds)

    @classmethod
    async def _read_json_or_error(
        cls,
        response: aiohttp.ClientResponse,
    ) -> Any:
        try:
            return await response.json(content_type=None)
        except (
            aiohttp.ContentTypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            try:
                body = await response.text()
            except Exception:
                body = ""

            return {
                "error": {
                    "message": body[:8000],
                }
            }

    @classmethod
    def _raise_http_error(
        cls,
        *,
        response: aiohttp.ClientResponse,
        data: Any,
    ) -> None:
        message = cls._extract_api_error_message(data)

        if response.status in _RETRYABLE_STATUS_CODES:
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=message,
                headers=response.headers,
            )

        raise OpenAIAdapterError(
            f"OpenAI API request failed with HTTP {response.status}: {message}"
        )

    # ------------------------------------------------------------------
    # SSE consumption
    # ------------------------------------------------------------------

    @staticmethod
    async def _iter_sse_events(
        response: aiohttp.ClientResponse,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Provider-specific SSE framing.

        Yields parsed JSON event objects. Non-JSON events are ignored except
        for explicit error events.
        """
        data_lines: list[str] = []

        async for raw_line in response.content:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

            if line == "":
                if data_lines:
                    data = "\n".join(data_lines)
                    data_lines.clear()

                    if data == _STREAM_SENTINEL:
                        yield {
                            "__done__": True,
                        }
                        continue

                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(parsed, dict):
                        yield parsed

                continue

            if line.startswith(":"):
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            data = "\n".join(data_lines)

            if data == _STREAM_SENTINEL:
                return

            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                return

            if isinstance(parsed, dict):
                yield parsed

    async def _consume_chat_stream(
        self,
        response: aiohttp.ClientResponse,
        response_headers: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        model: str | None = None
        response_id: str | None = None
        finish_reason: str | None = None
        final_choice: dict[str, Any] | None = None

        async for event in self._iter_sse_events(response):
            if event.get("__done__"):
                break

            response_id = event.get("id") or response_id
            model = event.get("model") or model

            event_usage = event.get("usage")
            if isinstance(event_usage, dict):
                usage = event_usage

            choices = event.get("choices")

            if not isinstance(choices, list) or not choices:
                continue

            choice = choices[0]

            if not isinstance(choice, dict):
                continue

            final_choice = choice

            finish_reason = choice.get("finish_reason") or finish_reason

            delta = choice.get("delta")

            if not isinstance(delta, dict):
                continue

            delta_content = delta.get("content")

            if isinstance(delta_content, str):
                text_parts.append(delta_content)

            delta_tool_calls = delta.get("tool_calls")

            if isinstance(delta_tool_calls, list):
                for delta_tool_call in delta_tool_calls:
                    if not isinstance(delta_tool_call, dict):
                        continue

                    index = delta_tool_call.get("index", 0)

                    try:
                        index = int(index)
                    except (TypeError, ValueError):
                        index = 0

                    accumulated = tool_calls.setdefault(
                        index,
                        {
                            "id": None,
                            "type": "function",
                            "function": {
                                "name": "",
                                "arguments": "",
                            },
                        },
                    )

                    call_id = delta_tool_call.get("id")
                    if call_id:
                        accumulated["id"] = call_id

                    function_delta = delta_tool_call.get("function")

                    if isinstance(function_delta, dict):
                        name = function_delta.get("name")

                        if name:
                            accumulated["function"]["name"] += str(name)

                        arguments = function_delta.get("arguments")

                        if arguments:
                            accumulated["function"]["arguments"] += str(arguments)

        assembled_choices: list[dict[str, Any]] = []

        for index in sorted(tool_calls):
            assembled_choices.append(
                {
                    "index": index,
                    "message": {
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": [
                            tool_calls[index],
                        ],
                    },
                    "finish_reason": finish_reason or "tool_calls",
                }
            )

        if not assembled_choices:
            assembled_choices = [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "".join(text_parts),
                    },
                    "finish_reason": finish_reason,
                }
            ]

        assembled: dict[str, Any] = {
            "id": response_id,
            "object": "chat.completion",
            "model": model,
            "choices": assembled_choices,
            "usage": usage,
        }

        if final_choice:
            assembled["finish_reason"] = final_choice.get("finish_reason")

        return assembled, response_headers

    async def _consume_responses_stream(
        self,
        response: aiohttp.ClientResponse,
        response_headers: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        text_parts: list[str] = []
        refusal_parts: list[str] = []

        function_calls: dict[str, dict[str, Any]] = {}

        response_id: str | None = None
        model: str | None = None
        response_status: str | None = None
        usage: dict[str, Any] = {}
        incomplete_details: Any = None

        final_response: dict[str, Any] | None = None

        async for event in self._iter_sse_events(response):
            if event.get("__done__"):
                break

            event_type = event.get("type")

            if event_type == "response.created":
                response_object = event.get("response")

                if isinstance(response_object, dict):
                    response_id = response_object.get("id") or response_id
                    model = response_object.get("model") or model
                    response_status = response_object.get("status") or response_status

                continue

            if event_type == "response.output_text.delta":
                delta = event.get("delta")

                if isinstance(delta, str):
                    text_parts.append(delta)

                continue

            if event_type == "response.refusal.delta":
                delta = event.get("delta")

                if isinstance(delta, str):
                    refusal_parts.append(delta)

                continue

            if event_type == "response.function_call_arguments.delta":
                item_id = str(event.get("item_id") or event.get("call_id") or "unknown")

                function_call = function_calls.setdefault(
                    item_id,
                    {
                        "type": "function_call",
                        "id": event.get("id"),
                        "call_id": event.get("call_id"),
                        "name": event.get("name"),
                        "arguments": "",
                    },
                )

                delta = event.get("delta")

                if isinstance(delta, str):
                    function_call["arguments"] += delta

                if event.get("name"):
                    function_call["name"] = event.get("name")

                if event.get("call_id"):
                    function_call["call_id"] = event.get("call_id")

                continue

            if event_type == "response.completed":
                response_object = event.get("response")

                if isinstance(response_object, dict):
                    final_response = response_object

                continue

            if event_type == "response.incomplete":
                response_object = event.get("response")

                if isinstance(response_object, dict):
                    final_response = response_object

                continue

            if event_type == "response.failed":
                response_object = event.get("response")

                if isinstance(response_object, dict):
                    final_response = response_object

                continue

            response_object = event.get("response")

            if (
                isinstance(response_object, dict)
                and response_object.get("status") in _TERMINAL_RESPONSES_STATUS
            ):
                final_response = response_object

        if final_response is not None:
            return final_response, response_headers

        output_items: list[dict[str, Any]] = []

        content = "".join(text_parts).strip()

        if content:
            output_items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": content,
                        }
                    ],
                }
            )

        for function_call in function_calls.values():
            output_items.append(
                {
                    "type": "function_call",
                    "id": function_call.get("id"),
                    "call_id": function_call.get("call_id"),
                    "name": function_call.get("name"),
                    "arguments": function_call.get("arguments", "{}"),
                }
            )

        if refusal_parts and not content:
            output_items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "refusal",
                            "refusal": "".join(refusal_parts),
                        }
                    ],
                }
            )

        return (
            {
                "id": response_id,
                "object": "response",
                "model": model,
                "status": response_status or "completed",
                "output": output_items,
                "usage": usage,
                "incomplete_details": incomplete_details,
            },
            response_headers,
        )

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_chat_completion(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        choices = data.get("choices")

        if not isinstance(choices, list) or not choices:
            raise OpenAIAdapterError(
                f"OpenAI Chat Completions response contains no choices: {data}"
            )

        choice = choices[0]

        if not isinstance(choice, dict):
            raise OpenAIAdapterError("OpenAI Chat Completions response contains an invalid choice.")

        message = choice.get("message") or {}

        if not isinstance(message, dict):
            raise OpenAIAdapterError(
                "OpenAI Chat Completions response contains an invalid message."
            )

        content = cls._extract_chat_content(message.get("content"))

        refusal = message.get("refusal")

        if refusal and not content:
            content = str(refusal).strip()

        tool_calls = cls._normalize_chat_tool_calls(message.get("tool_calls") or [])

        finish_reason = choice.get("finish_reason")
        usage = cls._normalize_usage(data.get("usage"))

        if tool_calls:
            if len(tool_calls) == 1:
                call = tool_calls[0]

                return {
                    "status": "success",
                    "action": "call_tool",
                    "output": content,
                    "content": content,
                    "tool_name": call["tool"],
                    "tool_params": call["params"],
                    "tool_call_id": call.get("call_id"),
                    "tool_calls": tool_calls,
                    "_raw_tool_calls": message.get("tool_calls") or [],
                    "_usage": usage,
                    "_model": data.get("model"),
                    "_response_id": data.get("id"),
                    "_finish_reason": finish_reason,
                }

            return {
                "status": "success",
                "action": "call_multiple_tools",
                "output": content,
                "content": content,
                "tool_calls": tool_calls,
                "_raw_tool_calls": message.get("tool_calls") or [],
                "_usage": usage,
                "_model": data.get("model"),
                "_response_id": data.get("id"),
                "_finish_reason": finish_reason,
            }

        if not content:
            if finish_reason == "length":
                raise OpenAIAdapterError(
                    "OpenAI response terminated because the output limit "
                    "was reached before producing usable content."
                )

            raise OpenAIAdapterError(
                "OpenAI Chat Completions returned no text content and no tool calls."
            )

        return {
            "status": "success",
            "output": content,
            "content": content,
            "action": DualNormalizationHub.normalize_text(content),
            "_usage": usage,
            "_model": data.get("model"),
            "_response_id": data.get("id"),
            "_finish_reason": finish_reason,
        }

    @classmethod
    def _normalize_responses(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        provider_status = data.get("status")
        response_id = data.get("id")
        model = data.get("model")

        usage = cls._normalize_usage(data.get("usage"))

        incomplete_details = data.get("incomplete_details")

        if provider_status == "failed":
            error = data.get("error") or {}

            message = (
                error.get("message") if isinstance(error, dict) else str(error)
            ) or "OpenAI Responses API returned status=failed."

            raise OpenAIAdapterError(message)

        output_items = data.get("output") or []

        if not isinstance(output_items, list):
            raise OpenAIAdapterError("OpenAI Responses API returned an invalid output array.")

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        refusals: list[str] = []

        for item in output_items:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")

            if item_type == "function_call":
                name = item.get("name")
                arguments = item.get("arguments")
                call_id = item.get("call_id")

                if not isinstance(name, str) or not name.strip():
                    raise OpenAIAdapterError(
                        "OpenAI Responses API returned a function call without a name."
                    )

                params = cls._parse_tool_arguments(arguments)

                tool_calls.append(
                    {
                        "tool": name,
                        "params": params,
                        "call_id": call_id,
                    }
                )

                continue

            if item_type == "message":
                content_blocks = item.get("content") or []

                if isinstance(content_blocks, str):
                    text_parts.append(content_blocks)
                    continue

                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue

                        block_type = block.get("type")

                        if block_type in {
                            "output_text",
                            "text",
                        }:
                            text = block.get("text")

                            if text is not None:
                                text_parts.append(str(text))

                        elif block_type == "refusal":
                            refusal = block.get("refusal")

                            if refusal:
                                refusals.append(str(refusal))

        output_text = data.get("output_text")

        if isinstance(output_text, str) and output_text:
            if not text_parts:
                text_parts.append(output_text)

        content = "".join(text_parts).strip()

        if not content and refusals:
            content = "\n".join(refusals).strip()

        raw_tool_calls = [
            item
            for item in output_items
            if (isinstance(item, dict) and item.get("type") == "function_call")
        ]

        if tool_calls:
            if len(tool_calls) == 1:
                call = tool_calls[0]

                return {
                    "status": "success",
                    "action": "call_tool",
                    "output": content,
                    "content": content,
                    "tool_name": call["tool"],
                    "tool_params": call["params"],
                    "tool_call_id": call.get("call_id"),
                    "tool_calls": tool_calls,
                    "_raw_tool_calls": raw_tool_calls,
                    "_usage": usage,
                    "_model": model,
                    "_provider_status": provider_status,
                    "_response_id": response_id,
                    "_incomplete_details": incomplete_details,
                }

            return {
                "status": "success",
                "action": "call_multiple_tools",
                "output": content,
                "content": content,
                "tool_calls": tool_calls,
                "_raw_tool_calls": raw_tool_calls,
                "_usage": usage,
                "_model": model,
                "_provider_status": provider_status,
                "_response_id": response_id,
                "_incomplete_details": incomplete_details,
            }

        if not content:
            if provider_status not in {
                None,
                "completed",
            }:
                raise OpenAIAdapterError(
                    f"OpenAI Responses API returned no usable content; status={provider_status!r}."
                )

            raise OpenAIAdapterError(
                "OpenAI Responses API returned neither text content nor function calls."
            )

        return {
            "status": "success",
            "output": content,
            "content": content,
            "action": DualNormalizationHub.normalize_text(content),
            "_usage": usage,
            "_model": model,
            "_provider_status": provider_status,
            "_response_id": response_id,
            "_incomplete_details": incomplete_details,
        }

    # ------------------------------------------------------------------
    # Tool-call normalization
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_chat_tool_calls(
        cls,
        raw_tool_calls: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_tool_calls, list):
            raise OpenAIAdapterError("OpenAI tool_calls must be an array.")

        normalized: list[dict[str, Any]] = []

        for index, call in enumerate(raw_tool_calls):
            if not isinstance(call, dict):
                raise OpenAIAdapterError(f"OpenAI tool call {index} is not an object.")

            function = call.get("function")

            if not isinstance(function, dict):
                raise OpenAIAdapterError(
                    f"OpenAI tool call {index} is missing its function object."
                )

            name = function.get("name")

            if not isinstance(name, str) or not name.strip():
                raise OpenAIAdapterError(f"OpenAI tool call {index} is missing a function name.")

            arguments = function.get(
                "arguments",
                "{}",
            )

            params = cls._parse_tool_arguments(arguments)

            normalized.append(
                {
                    "tool": name,
                    "params": params,
                    "call_id": call.get("id"),
                }
            )

        return normalized

    @staticmethod
    def _parse_tool_arguments(
        arguments: Any,
    ) -> dict[str, Any]:
        if arguments is None or arguments == "":
            return {}

        if isinstance(arguments, dict):
            return arguments

        if not isinstance(arguments, str):
            raise OpenAIAdapterError(
                "OpenAI tool arguments must be JSON text or an object, "
                f"got {type(arguments).__name__}."
            )

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise OpenAIAdapterError(
                f"OpenAI returned malformed JSON tool arguments: {exc.msg}."
            ) from exc

        if parsed is None:
            return {}

        if not isinstance(parsed, dict):
            raise OpenAIAdapterError("OpenAI tool arguments must decode to a JSON object.")

        return parsed

    # ------------------------------------------------------------------
    # Content / telemetry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_chat_content(
        content: Any,
    ) -> str:
        if content is None:
            return ""

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []

            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue

                if not isinstance(item, dict):
                    continue

                item_type = item.get("type")

                if item_type in {
                    "text",
                    "output_text",
                }:
                    text = item.get("text")

                    if text is not None:
                        parts.append(str(text))

                elif item_type == "refusal":
                    refusal = item.get("refusal")

                    if refusal is not None:
                        parts.append(str(refusal))

            return "".join(parts).strip()

        return str(content).strip()

    @staticmethod
    def _normalize_usage(
        usage: Any,
    ) -> dict[str, int]:
        if not isinstance(usage, dict):
            return {}

        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        if input_tokens is None:
            input_tokens = prompt_tokens

        if output_tokens is None:
            output_tokens = completion_tokens

        if total_tokens is None:
            if input_tokens is not None and output_tokens is not None:
                try:
                    total_tokens = int(input_tokens) + int(output_tokens)
                except (TypeError, ValueError):
                    total_tokens = None

        normalized: dict[str, int] = {}

        if input_tokens is not None:
            try:
                normalized["prompt_tokens"] = int(input_tokens)
            except (TypeError, ValueError):
                pass

        if output_tokens is not None:
            try:
                normalized["completion_tokens"] = int(output_tokens)
            except (TypeError, ValueError):
                pass

        if total_tokens is not None:
            try:
                normalized["total_tokens"] = int(total_tokens)
            except (TypeError, ValueError):
                pass

        return normalized

    @staticmethod
    def _emit_usage(
        usage: dict[str, int],
    ) -> None:
        emit(
            "metric_update",
            {
                "adapter": "openai",
                "provider": "openai",
                "tokens": usage.get("total_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    @staticmethod
    def _extract_api_error_message(
        data: Any,
    ) -> str:
        if isinstance(data, dict):
            error = data.get("error")

            if isinstance(error, dict):
                message = error.get("message")

                if message:
                    return str(message)

                error_type = error.get("type")
                error_code = error.get("code")

                if error_type or error_code:
                    return f"type={error_type or 'unknown'}, code={error_code or 'unknown'}"

            message = data.get("message")

            if message:
                return str(message)

        return "Unknown OpenAI API error."

    @staticmethod
    def _format_http_error(
        exc: aiohttp.ClientResponseError,
    ) -> str:
        message = exc.message or "OpenAI API request failed."

        return f"OpenAI API request failed with HTTP {exc.status}: {message}"

    @staticmethod
    def _drop_none(
        value: dict[str, Any],
    ) -> dict[str, Any]:
        return {key: item for key, item in value.items() if item is not None}
