# eval_runner/adapters/grok.py
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import AdapterSessionPool, BaseAdapter, DualNormalizationHub


class GrokAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production xAI/Grok adapter.

    Supports:
      - xAI Responses API as the primary interface
      - xAI Chat Completions API for compatibility
      - text and multimodal inputs
      - Responses continuation via previous_response_id
      - xAI cache affinity via prompt_cache_key / x-grok-conv-id
      - built-in and custom tools passed through unchanged
      - reasoning controls
      - structured outputs and other supported provider fields
      - streaming SSE for both supported APIs
      - response/tool/citation/usage normalization
      - lifecycle-scoped connection pooling and bounded retries

    The dispatcher normally supplies `task_description`; richer callers may
    provide `input`, `messages`, model controls, tools, history, and provider
    options explicitly.
    """

    _TRACEPARENT_RE = re.compile(
        r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
        re.IGNORECASE,
    )
    _MAX_ERROR_BODY = 64 * 1024
    _MAX_STREAM_CHUNKS = 100_000
    _MAX_STREAM_TEXT = 16 * 1024 * 1024

    def __init__(self, session_pool: AdapterSessionPool | None = None) -> None:
        BaseAdapter.__init__(self, name="grok")
        self.session_pool = session_pool or AdapterSessionPool()

    async def close(self) -> None:
        """Release the adapter-owned HTTP pool."""
        await self.session_pool.close()

    def on_discover_adapters(self, registry: Any) -> None:
        """Register the Grok protocol."""
        registry.register("grok", self.execute_grok_query)

    async def execute_grok_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> dict[str, Any]:
        """Execute one xAI inference request and return an AgentV response."""
        if not isinstance(payload, dict):
            return self._error_response(
                "Grok adapter payload must be an object.",
                error_type="invalid_request",
            )

        api_key = self._resolve_api_key(payload)
        if not api_key:
            return self._error_response(
                "xAI API key missing.",
                error_type="authentication",
            )

        api_mode = self._resolve_api_mode(payload, url)
        if api_mode not in {"responses", "chat_completions"}:
            return self._error_response(
                f"Unsupported Grok API mode: {api_mode}",
                error_type="configuration",
                api_mode=api_mode,
            )

        try:
            model = self._resolve_model(payload)
            endpoint = self._resolve_endpoint(
                url=url,
                api_mode=api_mode,
                base_url=str(
                    payload.get("base_url") or config.XAI_BASE_URL or "https://api.x.ai/v1"
                ),
            )
            request_body = self._build_request(
                payload=payload,
                model=model,
                api_mode=api_mode,
            )
            headers = self._build_headers(payload, api_key, api_mode)
        except ValueError as exc:
            return self._error_response(
                str(exc),
                error_type="invalid_request",
                api_mode=api_mode,
                model=payload.get("model") or payload.get("grok_model"),
            )

        stream = bool(request_body.get("stream", False))
        timeout_seconds = self._resolve_timeout(payload)
        deadline = self._resolve_retry_deadline(payload)

        async def _call() -> dict[str, Any]:
            return await self._request(
                endpoint=endpoint,
                headers=headers,
                body=request_body,
                stream=stream,
                timeout_seconds=timeout_seconds,
                api_mode=api_mode,
            )

        try:
            data = await self.call_with_retry(
                _call,
                deadline=deadline,
            )

            normalized = self._normalize_response(
                data=data,
                model=model,
                api_mode=api_mode,
                endpoint=endpoint,
                streamed=stream,
                request_body=request_body,
            )

            usage = normalized.get("metadata", {}).get("usage", {})
            emit(
                "metric_update",
                {
                    "adapter": "grok",
                    "provider": "xai",
                    "model": model,
                    "api_mode": api_mode,
                    "tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                    "reasoning_tokens": usage.get("reasoning_tokens"),
                    "cached_tokens": usage.get("cached_tokens"),
                    "cost_in_usd_ticks": usage.get("cost_in_usd_ticks"),
                },
            )

            return normalized

        except aiohttp.ClientResponseError as exc:
            return self._error_response(
                self._format_http_error(exc),
                error_type="provider_http",
                status_code=exc.status,
                request_id=self._header_value(exc.headers, "request-id"),
                api_mode=api_mode,
                model=model,
                endpoint=endpoint,
            )
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            return self._error_response(
                f"Grok transport error: {self._sanitize_exception(exc)}",
                error_type="transport",
                api_mode=api_mode,
                model=model,
                endpoint=endpoint,
            )
        except Exception as exc:
            return self._error_response(
                f"Grok request failed: {self._sanitize_exception(exc)}",
                error_type=type(exc).__name__,
                api_mode=api_mode,
                model=model,
                endpoint=endpoint,
            )

    async def _request(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        body: dict[str, Any],
        stream: bool,
        timeout_seconds: float,
        api_mode: str,
    ) -> dict[str, Any]:
        session = await self.session_pool.get_session()
        timeout = aiohttp.ClientTimeout(total=max(1.0, timeout_seconds))

        async with session.post(
            endpoint,
            headers=headers,
            json=body,
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                raw = await response.content.read(self._MAX_ERROR_BODY)
                text = raw.decode("utf-8", errors="replace")
                error_data = self._parse_json_text(text)
                message = self._extract_error_message(error_data, fallback=text)
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=response.status,
                    message=message,
                    headers=response.headers,
                )

            if stream:
                return await self._read_stream(response, api_mode=api_mode)

            raw = await response.content.read(self._MAX_ERROR_BODY)
            if not raw:
                raise ValueError("xAI returned an empty response body.")

            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise ValueError("xAI returned a non-JSON response body.") from exc

            if not isinstance(data, dict):
                raise ValueError("xAI returned a non-object JSON response.")

            return data

    async def _read_stream(
        self,
        response: aiohttp.ClientResponse,
        *,
        api_mode: str,
    ) -> dict[str, Any]:
        """Aggregate an xAI SSE stream into the same shape as a non-stream response."""
        if api_mode == "responses":
            return await self._read_responses_stream(response)
        return await self._read_chat_stream(response)

    async def _read_responses_stream(
        self,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        final_response: dict[str, Any] | None = None
        output_items: dict[str, dict[str, Any]] = {}
        text_parts: list[str] = []
        function_argument_parts: dict[str, list[str]] = {}
        function_call_meta: dict[str, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        event_count = 0
        text_size = 0

        async for event_type, event_data in self._iter_sse_events(response):
            event_count += 1
            if event_count > self._MAX_STREAM_CHUNKS:
                raise ValueError("xAI streaming response exceeded the event limit.")

            if event_data.get("error") and event_type != "response.error":
                error = event_data.get("error")
                raise ValueError(self._extract_error_message({"error": error}))

            if event_type == "response.completed":
                candidate = event_data.get("response")
                if isinstance(candidate, dict):
                    final_response = candidate
                else:
                    final_response = event_data
                continue

            if event_type == "response.failed":
                error = event_data.get("response", event_data)
                raise ValueError(self._extract_error_message(error))

            if event_type == "response.error" or event_type == "error":
                raise ValueError(self._extract_error_message(event_data))

            if event_type == "response.output_item.done":
                item = event_data.get("item")
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("call_id")
                    if item_id:
                        output_items[str(item_id)] = dict(item)
                continue

            if event_type in {
                "response.output_text.delta",
                "response.text.delta",
            }:
                delta = event_data.get("delta")
                if isinstance(delta, str):
                    text_parts.append(delta)
                    text_size += len(delta)
                    if text_size > self._MAX_STREAM_TEXT:
                        raise ValueError("xAI streaming response exceeded the text limit.")
                continue

            if event_type == "response.output_text.done":
                text = event_data.get("text")
                if isinstance(text, str) and not text_parts:
                    text_parts.append(text)
                continue

            if event_type in {
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
            }:
                call_id = event_data.get("item_id") or event_data.get("call_id")
                if call_id:
                    key = str(call_id)
                    function_call_meta.setdefault(
                        key,
                        {
                            "id": event_data.get("item_id"),
                            "call_id": event_data.get("call_id"),
                            "name": event_data.get("name"),
                        },
                    )

                    if event_type.endswith(".delta"):
                        delta = event_data.get("delta")
                        if isinstance(delta, str):
                            function_argument_parts.setdefault(key, []).append(delta)
                    else:
                        arguments = event_data.get("arguments")
                        if isinstance(arguments, str):
                            function_argument_parts[key] = [arguments]
                continue

            if event_type in {
                "response.usage",
                "response.in_progress",
                "response.done",
            }:
                candidate_usage = event_data.get("usage")
                if isinstance(candidate_usage, dict):
                    usage = dict(candidate_usage)

                response_obj = event_data.get("response")
                if isinstance(response_obj, dict):
                    candidate_usage = response_obj.get("usage")
                    if isinstance(candidate_usage, dict):
                        usage = dict(candidate_usage)

        if final_response is None:
            final_response = {
                "object": "response",
                "status": "completed",
                "output": [],
                "usage": usage,
            }

            if text_parts:
                final_response["output"].append(
                    {
                        "type": "message",
                        "id": "msg_stream",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "".join(text_parts),
                                "annotations": [],
                            }
                        ],
                    }
                )

            for key, meta in function_call_meta.items():
                arguments = "".join(function_argument_parts.get(key, []))
                final_response["output"].append(
                    {
                        "type": "function_call",
                        "id": meta.get("id"),
                        "call_id": meta.get("call_id"),
                        "name": meta.get("name"),
                        "arguments": arguments,
                    }
                )

        if usage and not final_response.get("usage"):
            final_response["usage"] = usage

        if output_items:
            existing = {
                str(item.get("id")): item
                for item in final_response.get("output", [])
                if isinstance(item, dict) and item.get("id")
            }

            for item_id, item in output_items.items():
                if item_id not in existing:
                    final_response.setdefault("output", []).append(item)

        return final_response

    async def _read_chat_stream(
        self,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        model: str | None = None
        response_id: str | None = None
        finish_reason: str | None = None
        event_count = 0
        text_size = 0
        role = "assistant"

        async for _event_type, event_data in self._iter_sse_events(response):
            event_count += 1
            if event_count > self._MAX_STREAM_CHUNKS:
                raise ValueError("xAI streaming response exceeded the event limit.")

            if event_data.get("error"):
                raise ValueError(self._extract_error_message(event_data))

            if event_data.get("id"):
                response_id = str(event_data["id"])

            if event_data.get("model"):
                model = str(event_data["model"])

            chunk_usage = event_data.get("usage")
            if isinstance(chunk_usage, dict):
                usage = dict(chunk_usage)

            choices = event_data.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            if not isinstance(choice, dict):
                continue

            if choice.get("finish_reason") is not None:
                finish_reason = str(choice["finish_reason"])

            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue

            if delta.get("role"):
                role = str(delta["role"])

            content = delta.get("content")
            if isinstance(content, str):
                content_parts.append(content)
                text_size += len(content)
                if text_size > self._MAX_STREAM_TEXT:
                    raise ValueError("xAI streaming response exceeded the text limit.")
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        content_parts.append(item["text"])
                        text_size += len(item["text"])
                        if text_size > self._MAX_STREAM_TEXT:
                            raise ValueError("xAI streaming response exceeded the text limit.")

            incoming_tools = delta.get("tool_calls") or []
            if isinstance(incoming_tools, list):
                for tool_delta in incoming_tools:
                    if not isinstance(tool_delta, dict):
                        continue

                    index = tool_delta.get("index")
                    if not isinstance(index, int):
                        index = len(tool_calls)

                    current = tool_calls.setdefault(
                        index,
                        {
                            "id": None,
                            "type": tool_delta.get("type") or "function",
                            "function": {
                                "name": "",
                                "arguments": "",
                            },
                        },
                    )

                    if tool_delta.get("id"):
                        current["id"] = tool_delta["id"]

                    function_delta = tool_delta.get("function") or {}
                    if isinstance(function_delta, dict):
                        name = function_delta.get("name")
                        arguments = function_delta.get("arguments")

                        if isinstance(name, str):
                            current["function"]["name"] = name

                        if isinstance(arguments, str):
                            current["function"]["arguments"] += arguments

        message: dict[str, Any] = {
            "role": role,
            "content": "".join(content_parts),
        }

        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]

        return {
            "id": response_id,
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
                }
            ],
            "usage": usage,
        }

    async def _iter_sse_events(
        self,
        response: aiohttp.ClientResponse,
    ):
        """Yield complete SSE events as (event_type, JSON object)."""
        event_type: str | None = None
        data_lines: list[str] = []

        async for raw_line in response.content:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

            if not line:
                if data_lines:
                    raw_data = "\n".join(data_lines)
                    data_lines = []

                    if raw_data == "[DONE]":
                        yield event_type, {"_done": True}
                    else:
                        try:
                            parsed = json.loads(raw_data)
                        except json.JSONDecodeError as exc:
                            raise ValueError("xAI SSE stream contained invalid JSON.") from exc

                        if isinstance(parsed, dict):
                            yield event_type, parsed

                event_type = None
                continue

            if line.startswith(":"):
                continue

            if line.startswith("event:"):
                event_type = line[6:].strip()
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
                    raise ValueError("xAI SSE stream contained invalid trailing JSON.") from exc

                if isinstance(parsed, dict):
                    yield event_type, parsed

    @staticmethod
    def _resolve_api_key(payload: dict[str, Any]) -> str | None:
        value = payload.get("api_key") or config.XAI_API_KEY or os.getenv("XAI_API_KEY")
        return str(value).strip() if value else None

    @classmethod
    def _resolve_api_mode(
        cls,
        payload: dict[str, Any],
        url: str | None,
    ) -> str:
        raw = payload.get("api_mode") or payload.get("mode")

        if raw:
            normalized = str(raw).strip().lower()
        else:
            normalized = cls._infer_api_mode(url) or "responses"

        aliases = {
            "response": "responses",
            "responses_api": "responses",
            "chat": "chat_completions",
            "chat-completions": "chat_completions",
            "chat_completion": "chat_completions",
            "chat_completions_api": "chat_completions",
        }

        return aliases.get(normalized, normalized)

    @staticmethod
    def _resolve_model(payload: dict[str, Any]) -> str:
        model = payload.get("model") or payload.get("grok_model") or config.XAI_MODEL
        model = str(model).strip()

        if not model:
            raise ValueError("xAI model is required.")

        return model

    @staticmethod
    def _resolve_timeout(payload: dict[str, Any]) -> float:
        value = payload.get("timeout", config.DEFAULT_ADAPTER_TIMEOUT)

        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(config.DEFAULT_ADAPTER_TIMEOUT)

        return max(1.0, value)

    @staticmethod
    def _resolve_retry_deadline(payload: dict[str, Any]) -> float | None:
        value = payload.get("retry_deadline")

        if value is None:
            return None

        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("retry_deadline must be numeric.") from exc

        if result <= 0:
            raise ValueError("retry_deadline must be greater than zero.")

        return result

    @staticmethod
    def _infer_api_mode(url: str | None) -> str | None:
        if not url:
            return None

        path = urlparse(str(url)).path.rstrip("/").lower()

        if path.endswith("/responses"):
            return "responses"

        if path.endswith("/chat/completions"):
            return "chat_completions"

        return None

    @classmethod
    def _resolve_endpoint(
        cls,
        *,
        url: str | None,
        api_mode: str,
        base_url: str,
    ) -> str:
        candidate = str(url or base_url).strip().rstrip("/")
        parsed = urlparse(candidate)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("xAI endpoint must be an absolute HTTP(S) URL.")

        selected_path = "/responses" if api_mode == "responses" else "/chat/completions"
        path = parsed.path.rstrip("/")

        if not path:
            path = "/v1" + selected_path
        elif path == "/v1":
            path = "/v1" + selected_path
        elif path.endswith("/responses") and api_mode == "responses":
            pass
        elif path.endswith("/chat/completions") and api_mode == "chat_completions":
            pass
        elif not url:
            if path.endswith("/v1"):
                path = path + selected_path
            else:
                path = path + "/v1" + selected_path
        else:
            raise ValueError(
                "Explicit xAI URL must target /responses, "
                "/chat/completions, or be a base/origin URL."
            )

        return f"{parsed.scheme}://{parsed.netloc}{path}"

    @classmethod
    def _build_headers(
        cls,
        payload: dict[str, Any],
        api_key: str,
        api_mode: str,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": ("text/event-stream" if payload.get("stream") else "application/json"),
        }

        traceparent = cls._extract_traceparent(payload)
        if traceparent:
            headers["traceparent"] = traceparent

        conversation_id = payload.get("conversation_id") or payload.get("x_grok_conv_id")

        if api_mode == "chat_completions" and conversation_id:
            headers["x-grok-conv-id"] = str(conversation_id)

        return headers

    @classmethod
    def _build_request(
        cls,
        *,
        payload: dict[str, Any],
        model: str,
        api_mode: str,
    ) -> dict[str, Any]:
        if api_mode == "responses":
            return cls._build_responses_request(payload, model)

        return cls._build_chat_request(payload, model)

    @classmethod
    def _build_responses_request(
        cls,
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "input": cls._build_responses_input(payload),
        }

        supported_fields = {
            "previous_response_id",
            "instructions",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "include",
            "reasoning",
            "store",
            "stream",
            "background",
            "truncation",
            "metadata",
            "prompt_cache_key",
            "text",
            "top_logprobs",
            "user",
            "safety_identifier",
            "service_tier",
            "max_output_tokens",
            "top_p",
            "temperature",
            "max_tool_calls",
        }

        for key in supported_fields:
            value = payload.get(key)
            if value is not None:
                request[key] = value

        reasoning = payload.get("reasoning")
        reasoning_effort = payload.get("reasoning_effort")

        if reasoning_effort is not None:
            if isinstance(reasoning, dict):
                reasoning = dict(reasoning)
                reasoning["effort"] = reasoning_effort
            else:
                reasoning = {"effort": str(reasoning_effort)}

            request["reasoning"] = reasoning

        elif isinstance(reasoning, str):
            request["reasoning"] = {"effort": reasoning}

        request.pop("frequency_penalty", None)
        request.pop("presence_penalty", None)

        return request

    @classmethod
    def _build_chat_request(
        cls,
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        messages = cls._build_chat_messages(payload)

        if not messages:
            raise ValueError(
                "Grok Chat Completions requires non-empty `messages`, "
                "`task_description`, `task`, or `prompt`."
            )

        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        supported_fields = {
            "temperature",
            "top_p",
            "max_tokens",
            "max_completion_tokens",
            "frequency_penalty",
            "presence_penalty",
            "n",
            "stream",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "response_format",
            "stop",
            "seed",
            "user",
            "logprobs",
            "top_logprobs",
            "reasoning_effort",
            "service_tier",
        }

        for key in supported_fields:
            value = payload.get(key)

            if value is not None:
                request[key] = value

        reasoning = payload.get("reasoning")

        if reasoning is not None:
            if isinstance(reasoning, dict):
                effort = reasoning.get("effort")
            else:
                effort = reasoning

            if effort is not None and "reasoning_effort" not in request:
                request["reasoning_effort"] = effort

        if request.get("stream") and "stream_options" not in request:
            request["stream_options"] = {"include_usage": True}
        elif payload.get("stream_options") is not None:
            request["stream_options"] = payload["stream_options"]

        return request

    @staticmethod
    def _build_responses_input(
        payload: dict[str, Any],
    ) -> str | list[Any]:
        input_value = payload.get("input")

        if input_value is not None:
            if isinstance(input_value, (str, list)):
                return input_value

            raise ValueError("Grok Responses `input` must be a string or array.")

        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise ValueError("`messages` must be a list when supplied.")

            return messages

        history = payload.get("history")
        task = payload.get("task_description") or payload.get("task") or payload.get("prompt")

        if history:
            if not isinstance(history, list):
                raise ValueError("`history` must be a list when supplied.")

            if task:
                return [
                    *history,
                    {
                        "role": "user",
                        "content": str(task),
                    },
                ]

            return history

        if not task:
            raise ValueError(
                "Grok request requires `task_description`, "
                "`task`, `prompt`, `input`, or `messages`."
            )

        system_prompt = payload.get("system_prompt")

        if system_prompt:
            return [
                {
                    "role": "system",
                    "content": str(system_prompt),
                },
                {
                    "role": "user",
                    "content": str(task),
                },
            ]

        return str(task)

    @staticmethod
    def _build_chat_messages(
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise ValueError("`messages` must be a list when supplied.")

            normalized: list[dict[str, Any]] = []

            for message in messages:
                if not isinstance(message, dict):
                    raise ValueError("Every Grok chat message must be an object.")

                role = message.get("role")

                if not role:
                    raise ValueError("Every Grok chat message requires a `role`.")

                if "content" not in message and not message.get("tool_calls"):
                    raise ValueError("Every Grok chat message requires `content` or `tool_calls`.")

                normalized.append(dict(message))

            return normalized

        history = payload.get("history")
        task = payload.get("task_description") or payload.get("task") or payload.get("prompt")

        normalized = []

        if history:
            if not isinstance(history, list):
                raise ValueError("`history` must be a list when supplied.")

            for message in history:
                if not isinstance(message, dict) or not message.get("role"):
                    raise ValueError("Every Grok history message must be an object with a `role`.")

                normalized.append(dict(message))

        system_prompt = payload.get("system_prompt")

        if system_prompt and not any(message.get("role") == "system" for message in normalized):
            normalized.insert(
                0,
                {
                    "role": "system",
                    "content": str(system_prompt),
                },
            )

        if task:
            normalized.append(
                {
                    "role": "user",
                    "content": str(task),
                }
            )

        return normalized

    @classmethod
    def _normalize_response(
        cls,
        *,
        data: dict[str, Any],
        model: str,
        api_mode: str,
        endpoint: str,
        streamed: bool,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        if api_mode == "responses":
            output = cls._extract_responses_text(data)
            tool_calls = cls._extract_responses_tool_calls(data)
            citations = cls._extract_responses_citations(data)
            usage = cls._normalize_usage(
                data.get("usage"),
                responses=True,
            )
            response_id = data.get("id")
            response_status = data.get("status")
            finish_reason = cls._extract_finish_reason(
                data,
                responses=True,
            )

            if tool_calls:
                action = "processing"
            elif output:
                action = DualNormalizationHub.normalize_text(output)
            elif response_status == "in_progress":
                action = "processing"
            elif response_status in {
                "completed",
                "succeeded",
            }:
                action = "error"
            else:
                action = "error"

            message = ""

            if action == "error":
                message = (
                    "xAI completed the request without usable text or tool output."
                    if response_status
                    in {
                        "completed",
                        "succeeded",
                    }
                    else "xAI returned no usable output."
                )

            return {
                "status": ("success" if action != "error" else "error"),
                "output": output,
                "action": action,
                "message": message,
                "tool_calls": tool_calls,
                "citations": citations,
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "model": data.get("model") or model,
                    "api_mode": api_mode,
                    "endpoint": endpoint,
                    "response_id": response_id,
                    "response_status": response_status,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "reasoning": data.get("reasoning"),
                    "incomplete_details": data.get("incomplete_details"),
                    "server_side_tool_usage": (cls._extract_server_side_tool_usage(data)),
                    "request": cls._safe_request_metadata(request_body),
                    "streamed": streamed,
                },
            }

        output = cls._extract_chat_text(data)
        tool_calls = cls._extract_chat_tool_calls(data)
        usage = cls._normalize_usage(
            data.get("usage"),
            responses=False,
        )
        citations = cls._extract_chat_citations(data)
        finish_reason = cls._extract_finish_reason(
            data,
            responses=False,
        )

        if tool_calls:
            action = "processing"
        elif output:
            action = DualNormalizationHub.normalize_text(output)
        else:
            action = "error"

        return {
            "status": ("success" if action != "error" else "error"),
            "output": output,
            "action": action,
            "message": ("" if action != "error" else "xAI returned no usable output."),
            "tool_calls": tool_calls,
            "citations": citations,
            "metadata": {
                "framework": "grok",
                "provider": "xai",
                "model": data.get("model") or model,
                "api_mode": api_mode,
                "endpoint": endpoint,
                "response_id": data.get("id"),
                "finish_reason": finish_reason,
                "usage": usage,
                "request": cls._safe_request_metadata(request_body),
                "streamed": streamed,
            },
        }

    @staticmethod
    def _extract_responses_text(
        data: dict[str, Any],
    ) -> str:
        output_text = data.get("output_text")

        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        chunks: list[str] = []

        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue

            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue

                if content.get("type") in {
                    "output_text",
                    "text",
                }:
                    text_value = content.get("text")

                    if isinstance(text_value, str):
                        chunks.append(text_value)

        return "".join(chunks).strip()

    @staticmethod
    def _extract_chat_text(
        data: dict[str, Any],
    ) -> str:
        choices = data.get("choices") or []

        if not choices or not isinstance(choices[0], dict):
            return ""

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            chunks: list[str] = []

            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunks.append(item["text"])

            return "".join(chunks).strip()

        return ""

    @staticmethod
    def _extract_responses_tool_calls(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue

            calls.append(
                {
                    "id": item.get("id"),
                    "type": "function",
                    "name": item.get("name"),
                    "call_id": item.get("call_id"),
                    "arguments": item.get("arguments"),
                    "status": item.get("status"),
                }
            )

        return calls

    @staticmethod
    def _extract_chat_tool_calls(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        choices = data.get("choices") or []

        if not choices or not isinstance(choices[0], dict):
            return []

        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if not isinstance(tool_calls, list):
            return []

        normalized: list[dict[str, Any]] = []

        for call in tool_calls:
            if not isinstance(call, dict):
                continue

            function = call.get("function") or {}

            normalized.append(
                {
                    "id": call.get("id"),
                    "type": call.get("type") or "function",
                    "name": function.get("name"),
                    "arguments": function.get("arguments"),
                }
            )

        return normalized

    @staticmethod
    def _extract_responses_citations(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(
            url: Any,
            title: Any = None,
            source: Any = None,
        ) -> None:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                return

            if url in seen:
                return

            seen.add(url)

            item: dict[str, Any] = {"url": url}

            if title is not None:
                item["title"] = title

            if source is not None:
                item["source"] = source

            citations.append(item)

        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue

            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue

                for annotation in content.get("annotations") or []:
                    if not isinstance(annotation, dict):
                        continue

                    add(
                        annotation.get("url") or annotation.get("source_url"),
                        annotation.get("title"),
                        annotation.get("type"),
                    )

        top_level = data.get("citations") or data.get("sources")

        if isinstance(top_level, list):
            for entry in top_level:
                if isinstance(entry, dict):
                    add(
                        entry.get("url") or entry.get("source_url"),
                        entry.get("title"),
                        entry.get("type"),
                    )

        return citations

    @staticmethod
    def _extract_chat_citations(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        top_level = data.get("citations") or data.get("sources")

        if not isinstance(top_level, list):
            return []

        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in top_level:
            if not isinstance(entry, dict):
                continue

            url = entry.get("url") or entry.get("source_url")

            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue

            if url in seen:
                continue

            seen.add(url)

            citations.append(
                {
                    "url": url,
                    "title": entry.get("title"),
                    "type": entry.get("type"),
                }
            )

        return citations

    @staticmethod
    def _extract_finish_reason(
        data: dict[str, Any],
        *,
        responses: bool,
    ) -> str | None:
        if not responses:
            choices = data.get("choices") or []

            if choices and isinstance(choices[0], dict):
                reason = choices[0].get("finish_reason")

                if reason is not None:
                    return str(reason)

            return None

        status = data.get("status")

        return str(status) if status is not None else None

    @staticmethod
    def _normalize_usage(
        usage: Any,
        *,
        responses: bool,
    ) -> dict[str, Any]:
        if not isinstance(usage, dict):
            return {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "reasoning_tokens": None,
                "cached_tokens": None,
                "cost_in_usd_ticks": None,
            }

        if responses:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            total_tokens = usage.get("total_tokens")

            input_details = usage.get("input_tokens_details") or {}

            output_details = usage.get("output_tokens_details") or {}
        else:
            input_tokens = usage.get(
                "prompt_tokens",
                usage.get("input_tokens"),
            )

            output_tokens = usage.get(
                "completion_tokens",
                usage.get("output_tokens"),
            )

            total_tokens = usage.get("total_tokens")

            input_details = (
                usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
            )

            output_details = (
                usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
            )

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": output_details.get("reasoning_tokens"),
            "cached_tokens": input_details.get("cached_tokens"),
            "cost_in_usd_ticks": usage.get("cost_in_usd_ticks"),
            "num_sources_used": usage.get("num_sources_used"),
            "num_server_side_tools_used": usage.get("num_server_side_tools_used"),
            "raw": usage,
        }

    @staticmethod
    def _extract_server_side_tool_usage(
        data: dict[str, Any],
    ) -> Any:
        usage = data.get("usage")

        if isinstance(usage, dict):
            return {
                "num_sources_used": usage.get("num_sources_used"),
                "num_server_side_tools_used": usage.get("num_server_side_tools_used"),
            }

        return None

    @staticmethod
    def _safe_request_metadata(
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Retain a forensic request envelope while bounding large values."""
        redacted_keys = {
            "api_key",
            "authorization",
            "access_token",
            "refresh_token",
            "client_secret",
            "password",
            "private_key",
            "token",
            "secret",
        }

        def sanitize(
            value: Any,
            key: str | None = None,
        ) -> Any:
            if key and any(marker in key.lower() for marker in redacted_keys):
                return "[REDACTED]"

            if isinstance(value, dict):
                return {str(k): sanitize(v, str(k)) for k, v in value.items()}

            if isinstance(value, list):
                return [sanitize(v) for v in value[:100]]

            if isinstance(value, str):
                if len(value) <= 16_384:
                    return value

                return value[:16_384] + "...[TRUNCATED]"

            return value

        return sanitize(request)  # type: ignore[return-value]

    @classmethod
    def _extract_traceparent(
        cls,
        payload: dict[str, Any],
    ) -> str | None:
        span_context = payload.get("span_context")

        if not isinstance(span_context, dict):
            return None

        traceparent = span_context.get("traceparent")

        if not isinstance(traceparent, str):
            return None

        traceparent = traceparent.strip()

        if not cls._TRACEPARENT_RE.fullmatch(traceparent):
            return None

        return traceparent

    @classmethod
    def _extract_error_message(
        cls,
        data: Any,
        *,
        fallback: str = "Unknown xAI API error.",
    ) -> str:
        if isinstance(data, dict):
            error = data.get("error")

            if isinstance(error, dict):
                for key in (
                    "message",
                    "detail",
                    "description",
                    "type",
                    "code",
                ):
                    value = error.get(key)

                    if value:
                        return str(value)

            elif error:
                return str(error)

            for key in (
                "message",
                "detail",
                "description",
            ):
                value = data.get(key)

                if value:
                    return str(value)

        text = str(fallback).strip()

        return text[:4000] if text else "Unknown xAI API error."

    @staticmethod
    def _parse_json_text(
        text: str,
    ) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except (
            TypeError,
            json.JSONDecodeError,
        ):
            return {"_non_json_response": text[:4000]}

        if isinstance(parsed, dict):
            return parsed

        return {"_response_body": parsed}

    @classmethod
    def _format_http_error(
        cls,
        exc: aiohttp.ClientResponseError,
    ) -> str:
        message = exc.message or "request failed"

        return f"Grok API error {exc.status}: {message}"

    @staticmethod
    def _header_value(
        headers: Any,
        name: str,
    ) -> str | None:
        if not headers:
            return None

        try:
            value = headers.get(name)
        except AttributeError:
            return None

        return str(value) if value else None

    @staticmethod
    def _sanitize_exception(
        exc: Exception,
    ) -> str:
        message = str(exc)

        secrets = {
            os.getenv("XAI_API_KEY"),
            os.getenv("OPENAI_API_KEY"),
        }

        for secret in secrets:
            if secret:
                message = message.replace(
                    secret,
                    "[REDACTED]",
                )

        return message[:4000]

    @staticmethod
    def _error_response(
        message: str,
        *,
        error_type: str,
        status_code: int | None = None,
        request_id: str | None = None,
        api_mode: str | None = None,
        model: Any = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "framework": "grok",
            "provider": "xai",
            "error_type": error_type,
        }

        if status_code is not None:
            metadata["status_code"] = status_code

        if request_id:
            metadata["request_id"] = request_id

        if api_mode:
            metadata["api_mode"] = api_mode

        if model:
            metadata["model"] = model

        if endpoint:
            metadata["endpoint"] = endpoint

        return {
            "status": "error",
            "action": "error",
            "message": message,
            "metadata": metadata,
        }
