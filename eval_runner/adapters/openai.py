# eval_runner/adapters/openai.py
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager

_TRACEPARENT_REGEX = re.compile(r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class OpenAIAdapterError(RuntimeError):
    """Adapter-local error used for deterministic OpenAI transport/response failures."""


class OpenAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production OpenAI adapter.

    Supports:
      - OpenAI Responses API
      - OpenAI Chat Completions API
      - OpenAI-compatible Chat Completions endpoints
      - AgentV task_description / messages / history input contracts
      - Function/tool call normalization into AgentV's tool-call contract
      - Token telemetry
      - W3C traceparent propagation
      - Shared HTTP connection pooling
      - Retry handling through BaseAdapter
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="openai")

    def on_discover_adapters(self, registry: Any):
        """Register the OpenAI provider adapter."""
        registry.register("openai", self.execute_openai_query)

    async def execute_openai_query(
        self,
        payload: dict[str, Any],
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute an OpenAI request and normalize the result to the AgentV adapter contract.

        Payloads may contain:
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
          response_format / text
          seed
          service_tier
        """
        try:
            api_key = self._resolve_api_key(payload)
            if not api_key:
                raise OpenAIAdapterError(
                    "OpenAI API key missing. Set OPENAI_API_KEY or provide payload.api_key."
                )

            endpoint_hint = (
                base_url
                or payload.get("base_url")
                or payload.get("url")
                or payload.get("endpoint")
                or config.OPENAI_BASE_URL
            )

            api_mode = self._resolve_api_mode(payload, endpoint_hint)
            endpoint = self._resolve_endpoint(endpoint_hint, api_mode)

            model = str(
                payload.get("model")
                or (payload.get("metadata") or {}).get("model")
                or config.OPENAI_MODEL
            ).strip()
            if not model:
                raise OpenAIAdapterError("OpenAI model is missing.")

            messages = self._build_messages(payload)
            if not messages:
                raise OpenAIAdapterError(
                    "OpenAI request contains no user/assistant input. "
                    "Expected task_description, task, prompt, input, messages, or history."
                )

            headers = self._build_headers(api_key, payload)

            if api_mode == "responses":
                request_body = self._build_responses_payload(
                    payload=payload,
                    model=model,
                    messages=messages,
                )
            else:
                request_body = self._build_chat_payload(
                    payload=payload,
                    model=model,
                    messages=messages,
                )

            async def _call():
                return await self._post_json(
                    endpoint=endpoint,
                    headers=headers,
                    request_body=request_body,
                )

            response_json, response_headers = await self.call_with_retry(
                _call,
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
            provider_model = normalized.pop("_model", model)
            provider_status = normalized.pop("_provider_status", None)
            provider_response_id = normalized.pop("_response_id", None)
            finish_reason = normalized.pop("_finish_reason", None)
            raw_tool_calls = normalized.pop("_raw_tool_calls", [])

            if usage:
                self._emit_usage(usage)

            metadata = {
                "framework": "openai",
                "api_mode": api_mode,
                "model": provider_model,
                "endpoint": endpoint,
                "response_id": provider_response_id,
                "provider_status": provider_status,
                "finish_reason": finish_reason,
                "usage": usage,
                "request_id": response_headers.get("x-request-id"),
            }

            if raw_tool_calls:
                metadata["tool_call_count"] = len(raw_tool_calls)

            normalized["metadata"] = metadata
            normalized.setdefault("status", "success")

            return normalized

        except aiohttp.ClientResponseError as exc:
            return {
                "status": "error",
                "action": "error",
                "message": self._format_http_error(exc),
                "metadata": {
                    "framework": "openai",
                    "status_code": exc.status,
                },
            }
        except asyncio_cancelled_error_types() as exc:
            raise exc
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
                },
            }

    @staticmethod
    def _resolve_api_key(payload: dict[str, Any]) -> str | None:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return (
            payload.get("api_key")
            or metadata.get("api_key")
            or config.OPENAI_API_KEY
            or os.getenv("OPENAI_API_KEY")
        )

    @staticmethod
    def _resolve_api_mode(payload: dict[str, Any], endpoint_hint: str) -> str:
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

        # The repository's configured default is OpenAI's official base URL.
        # Use Responses API by default for the official OpenAI service while
        # preserving broad OpenAI-compatible endpoint compatibility.
        host = urlsplit(str(endpoint_hint)).netloc.lower()
        if host in {"api.openai.com", "api.openai.com:443"}:
            return "responses"

        return "chat_completions"

    @staticmethod
    def _resolve_endpoint(endpoint_hint: str, api_mode: str) -> str:
        endpoint = str(endpoint_hint).strip()
        if not endpoint:
            raise OpenAIAdapterError("OpenAI endpoint is empty.")

        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise OpenAIAdapterError(
                f"Invalid OpenAI endpoint '{endpoint}'. Expected an absolute http(s) URL."
            )

        path = parsed.path.rstrip("/")

        expected_suffix = "/responses" if api_mode == "responses" else "/chat/completions"

        if path.endswith(expected_suffix):
            return endpoint

        other_suffix = "/chat/completions" if api_mode == "responses" else "/responses"
        if path.endswith(other_suffix):
            path = path[: -len(other_suffix)].rstrip("/")

        if path:
            path = f"{path}{expected_suffix}"
        else:
            path = expected_suffix

        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    @staticmethod
    def _build_headers(payload: dict[str, Any], api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        span_context = payload.get("span_context")
        if isinstance(span_context, dict):
            traceparent = span_context.get("traceparent")
            if isinstance(traceparent, str) and _TRACEPARENT_REGEX.fullmatch(traceparent):
                headers["traceparent"] = traceparent

        organization = (
            payload.get("organization")
            or (payload.get("metadata") or {}).get("organization")
            or os.getenv("OPENAI_ORGANIZATION")
        )
        project = (
            payload.get("project")
            or (payload.get("metadata") or {}).get("project")
            or os.getenv("OPENAI_PROJECT")
        )

        if organization:
            headers["OpenAI-Organization"] = str(organization)
        if project:
            headers["OpenAI-Project"] = str(project)

        return headers

    @classmethod
    def _build_messages(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        messages: list[dict[str, Any]] = []

        if isinstance(raw_messages, list):
            for index, message in enumerate(raw_messages):
                if not isinstance(message, dict):
                    raise OpenAIAdapterError(
                        f"Invalid message at index {index}: expected an object."
                    )

                role = message.get("role")
                if not isinstance(role, str) or not role.strip():
                    raise OpenAIAdapterError(f"Invalid message at index {index}: missing role.")

                content = message.get("content")

                normalized = dict(message)
                normalized["role"] = role.strip()

                if content is None and normalized["role"] not in {
                    "assistant",
                    "tool",
                }:
                    raise OpenAIAdapterError(f"Invalid message at index {index}: missing content.")

                messages.append(normalized)

        system_prompt = payload.get("system_prompt") or (payload.get("metadata") or {}).get(
            "system_prompt"
        )

        if system_prompt:
            has_system = any(m.get("role") == "system" for m in messages)
            if not has_system:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": str(system_prompt),
                    },
                )

        if messages:
            return messages

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
            return []

        if isinstance(current_input, str):
            content: Any = current_input
        else:
            try:
                content = json.dumps(
                    current_input,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            except (TypeError, ValueError) as exc:
                raise OpenAIAdapterError(f"Unable to serialize OpenAI input: {exc}") from exc

        return [{"role": "user", "content": content}]

    @staticmethod
    def _build_chat_payload(
        payload: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
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

        if "max_output_tokens" in payload and "max_completion_tokens" not in body:
            body["max_completion_tokens"] = payload["max_output_tokens"]

        return body

    @staticmethod
    def _build_responses_payload(
        payload: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "input": messages,
        }

        system_prompt = payload.get("system_prompt")
        if system_prompt:
            body["instructions"] = str(system_prompt)

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
        }

        for source, target in field_map.items():
            if source in payload and payload[source] is not None:
                body[target] = payload[source]

        # Accept the common AgentV/OpenAI-neutral alias.
        if "response_format" in payload and "text" not in body:
            response_format = payload["response_format"]
            if isinstance(response_format, dict):
                body["text"] = {"format": response_format}

        return body

    async def _post_json(
        self,
        endpoint: str,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        session = await SessionManager.get_session()

        async with session.post(
            endpoint,
            json=request_body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
        ) as response:
            response_headers = dict(response.headers)

            try:
                data = await response.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError):
                body_text = await response.text()
                data = {"error": {"message": body_text[:4000]}}

            if not 200 <= response.status < 300:
                message = self._extract_api_error_message(data)

                if response.status in _RETRYABLE_STATUS_CODES:
                    raise aiohttp.ClientResponseError(
                        request_info=getattr(response, "request_info", None),
                        history=getattr(response, "history", ()),
                        status=response.status,
                        message=message,
                        headers=response_headers,
                    )

                raise OpenAIAdapterError(
                    f"OpenAI API request failed with HTTP {response.status}: {message}"
                )

            if not isinstance(data, dict):
                raise OpenAIAdapterError(
                    f"OpenAI API returned unexpected JSON type: {type(data).__name__}"
                )

            return data, response_headers

    @classmethod
    def _normalize_chat_completion(cls, data: dict[str, Any]) -> dict[str, Any]:
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
            content = str(refusal)

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
                    "OpenAI response terminated because the output limit was reached "
                    "before producing usable content."
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
    def _normalize_responses(cls, data: dict[str, Any]) -> dict[str, Any]:
        provider_status = data.get("status")
        response_id = data.get("id")
        model = data.get("model")
        usage = cls._normalize_usage(data.get("usage"))

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

                if not isinstance(name, str) or not name.strip():
                    raise OpenAIAdapterError(
                        "OpenAI Responses API returned a function call without a name."
                    )

                params = cls._parse_tool_arguments(arguments)
                tool_calls.append(
                    {
                        "tool": name,
                        "params": params,
                        "call_id": item.get("call_id"),
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

                        if block_type in {"output_text", "text"}:
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
            content = "\n".join(refusals)

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
                    "tool_calls": tool_calls,
                    "_raw_tool_calls": [
                        item
                        for item in output_items
                        if isinstance(item, dict) and item.get("type") == "function_call"
                    ],
                    "_usage": usage,
                    "_model": model,
                    "_provider_status": provider_status,
                    "_response_id": response_id,
                }

            return {
                "status": "success",
                "action": "call_multiple_tools",
                "output": content,
                "content": content,
                "tool_calls": tool_calls,
                "_raw_tool_calls": [
                    item
                    for item in output_items
                    if isinstance(item, dict) and item.get("type") == "function_call"
                ],
                "_usage": usage,
                "_model": model,
                "_provider_status": provider_status,
                "_response_id": response_id,
            }

        if not content:
            if provider_status not in {None, "completed"}:
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
        }

    @classmethod
    def _normalize_chat_tool_calls(cls, raw_tool_calls: Any) -> list[dict[str, Any]]:
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

            arguments = function.get("arguments", "{}")
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
    def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
        if arguments is None or arguments == "":
            return {}

        if isinstance(arguments, dict):
            return arguments

        if not isinstance(arguments, str):
            raise OpenAIAdapterError(
                f"OpenAI tool arguments must be JSON text or an object, "
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

    @staticmethod
    def _extract_chat_content(content: Any) -> str:
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
                if item_type in {"text", "output_text"} and item.get("text") is not None:
                    parts.append(str(item["text"]))
                elif item_type == "refusal" and item.get("refusal") is not None:
                    parts.append(str(item["refusal"]))

            return "".join(parts).strip()

        return str(content).strip()

    @staticmethod
    def _normalize_usage(usage: Any) -> dict[str, int]:
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

        if total_tokens is None and input_tokens is not None and output_tokens is not None:
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
    def _emit_usage(usage: dict[str, int]) -> None:
        emit(
            "metric_update",
            {
                "adapter": "openai",
                "tokens": usage.get("total_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    @staticmethod
    def _extract_api_error_message(data: Any) -> str:
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
    def _format_http_error(exc: aiohttp.ClientResponseError) -> str:
        message = exc.message or "OpenAI API request failed."
        return f"OpenAI API request failed with HTTP {exc.status}: {message}"


def asyncio_cancelled_error_types() -> tuple[type[BaseException], ...]:
    """
    Return cancellation exceptions without importing asyncio solely for isinstance
    checks in the broad exception handler.

    asyncio.CancelledError subclasses BaseException, so it would not normally be
    caught by `except Exception`; this helper keeps the intent explicit.
    """
    import asyncio

    return (asyncio.CancelledError,)
