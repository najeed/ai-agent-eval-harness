# eval_runner/adapters/grok.py
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class GrokAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production xAI/Grok adapter.

    Supports:
      - xAI Responses API (primary)
      - xAI Chat Completions API (compatibility)
      - text + multimodal input
      - conversation continuation via previous_response_id
      - server-side and custom tools
      - reasoning parameters
      - structured request passthrough for supported xAI fields
      - response/tool/citation/usage normalization
      - shared connection pooling and transient retry handling

    The dispatcher normally supplies `task_description`; legacy `task`,
    `messages`, and `input` payloads are also accepted.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="grok")

    def on_discover_adapters(self, registry: Any):
        """Register the Grok protocol."""
        registry.register("grok", self.execute_grok_query)

    async def execute_grok_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute an xAI request using the Responses API by default.

        The caller may explicitly select Chat Completions with:
            payload["api_mode"] = "chat_completions"

        A full endpoint URL may also be supplied through `url`.
        """
        api_key = payload.get("api_key") or config.XAI_API_KEY or os.getenv("XAI_API_KEY")

        if not api_key:
            return {
                "status": "error",
                "action": "error",
                "message": "xAI API key missing.",
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "error_type": "authentication",
                },
            }

        api_mode = (
            str(
                payload.get("api_mode")
                or payload.get("mode")
                or self._infer_api_mode(url)
                or "responses"
            )
            .strip()
            .lower()
        )

        if api_mode in {"chat", "chat-completions", "chat_completion"}:
            api_mode = "chat_completions"

        if api_mode not in {"responses", "chat_completions"}:
            return {
                "status": "error",
                "action": "error",
                "message": f"Unsupported Grok API mode: {api_mode}",
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "error_type": "configuration",
                },
            }

        model = str(payload.get("model") or config.XAI_MODEL)

        endpoint = self._resolve_endpoint(
            url=url,
            api_mode=api_mode,
            base_url=(payload.get("base_url") or config.XAI_BASE_URL or "https://api.x.ai/v1"),
        )

        try:
            request_body = (
                self._build_responses_payload(payload, model)
                if api_mode == "responses"
                else self._build_chat_payload(payload, model)
            )
        except ValueError as exc:
            return {
                "status": "error",
                "action": "error",
                "message": str(exc),
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "model": model,
                    "api_mode": api_mode,
                    "error_type": "invalid_request",
                },
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # xAI documents prompt-cache affinity for Responses and conversation
        # affinity for Chat Completions. Only send these when explicitly supplied.
        prompt_cache_key = payload.get("prompt_cache_key")
        conversation_id = payload.get("conversation_id") or payload.get("x_grok_conv_id")

        if api_mode == "responses" and prompt_cache_key:
            headers["X-Prompt-Cache-Key"] = str(prompt_cache_key)

        if api_mode == "chat_completions" and conversation_id:
            headers["x-grok-conv-id"] = str(conversation_id)

        traceparent = self._extract_traceparent(payload)
        if traceparent:
            headers["traceparent"] = traceparent

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(
                endpoint,
                headers=headers,
                json=request_body,
            ) as response:
                response_json = await self._read_json_or_error(response)

                if response.status >= 400:
                    from aiohttp import ClientResponseError

                    raise ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=self._extract_error_message(response_json),
                        headers=response.headers,
                    )

                return response_json

        try:
            data = await self.call_with_retry(_call)

            normalized = self._normalize_response(
                data=data,
                model=model,
                api_mode=api_mode,
                endpoint=endpoint,
            )

            emit(
                "metric_update",
                {
                    "adapter": "grok",
                    "model": model,
                    "api_mode": api_mode,
                    "tokens": normalized["metadata"]["usage"].get("total_tokens"),
                    "prompt_tokens": normalized["metadata"]["usage"].get("input_tokens"),
                    "completion_tokens": normalized["metadata"]["usage"].get("output_tokens"),
                },
            )

            return normalized

        except Exception as exc:
            return {
                "status": "error",
                "action": "error",
                "message": f"Grok request failed: {self._sanitize_exception(exc)}",
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "model": model,
                    "api_mode": api_mode,
                    "endpoint": endpoint,
                    "error_type": type(exc).__name__,
                },
            }

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

    @staticmethod
    def _resolve_endpoint(
        *,
        url: str | None,
        api_mode: str,
        base_url: str,
    ) -> str:
        if url:
            candidate = str(url).strip().rstrip("/")
            parsed = urlparse(candidate)

            # A full API endpoint is used verbatim.
            if parsed.path and parsed.path not in {"", "/"}:
                return candidate

            # A bare origin/base URL receives the selected API path.
            if api_mode == "responses":
                return f"{candidate}/responses"
            return f"{candidate}/chat/completions"

        base = str(base_url).strip().rstrip("/")

        # Avoid accidental double /v1 when callers provide the xAI origin.
        if base.endswith("/v1"):
            versioned_base = base
        else:
            versioned_base = f"{base}/v1"

        if api_mode == "responses":
            return f"{versioned_base}/responses"

        return f"{versioned_base}/chat/completions"

    @staticmethod
    def _build_responses_payload(
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "input": GrokAdapterPlugin._build_responses_input(payload),
        }

        GrokAdapterPlugin._copy_if_present(
            payload,
            request,
            "previous_response_id",
            "conversation",
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
        )

        # Keep common generation controls only when explicitly provided.
        for key in (
            "temperature",
            "top_p",
            "max_output_tokens",
            "frequency_penalty",
            "presence_penalty",
        ):
            if key in payload and payload[key] is not None:
                request[key] = payload[key]

        # Prevent the harness's internal execution metadata from becoming
        # provider request metadata when `metadata` is not intentionally used.
        if isinstance(request.get("metadata"), dict):
            request["metadata"] = dict(request["metadata"])

        return request

    @staticmethod
    def _build_chat_payload(
        payload: dict[str, Any],
        model: str,
    ) -> dict[str, Any]:
        messages = GrokAdapterPlugin._build_chat_messages(payload)

        if not messages:
            raise ValueError(
                "Grok request requires non-empty `task_description`, `task`, `input`, "
                "or `messages`."
            )

        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        for key in (
            "temperature",
            "top_p",
            "max_tokens",
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
        ):
            if key in payload and payload[key] is not None:
                request[key] = payload[key]

        return request

    @staticmethod
    def _build_responses_input(payload: dict[str, Any]) -> str | list[Any]:
        input_value = payload.get("input")

        if input_value is not None:
            if isinstance(input_value, (str, list)):
                return input_value
            return str(input_value)

        messages = payload.get("messages")
        if messages:
            if not isinstance(messages, list):
                raise ValueError("`messages` must be a list when supplied.")
            return messages

        task = payload.get("task_description") or payload.get("task") or payload.get("prompt")

        if not task:
            raise ValueError(
                "Grok request requires non-empty `task_description`, `task`, "
                "`prompt`, `input`, or `messages`."
            )

        return str(task)

    @staticmethod
    def _build_chat_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise ValueError("`messages` must be a list when supplied.")

            normalized: list[dict[str, Any]] = []
            for message in messages:
                if not isinstance(message, dict):
                    raise ValueError("Every `messages` item must be an object.")

                role = message.get("role")
                if not role:
                    raise ValueError("Every Grok chat message requires a `role`.")

                if "content" not in message:
                    raise ValueError("Every Grok chat message requires `content`.")

                normalized.append(dict(message))

            return normalized

        task = payload.get("task_description") or payload.get("task") or payload.get("prompt")

        if not task:
            return []

        messages = []

        system_prompt = payload.get("system_prompt")
        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": str(system_prompt),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": str(task),
            }
        )

        return messages

    @staticmethod
    async def _read_json_or_error(response: Any) -> dict[str, Any]:
        try:
            data = await response.json(content_type=None)
        except Exception:
            text = await response.text()
            return {
                "_non_json_response": text[:4000],
            }

        if isinstance(data, dict):
            return data

        return {
            "_response_body": data,
        }

    @staticmethod
    def _extract_error_message(data: dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return "Unknown xAI API error."

        error = data.get("error")

        if isinstance(error, dict):
            message = error.get("message") or error.get("detail")
            if message:
                return str(message)

        if error:
            return str(error)

        for key in ("message", "detail", "description"):
            if data.get(key):
                return str(data[key])

        if data.get("_non_json_response"):
            return str(data["_non_json_response"])

        return "Unknown xAI API error."

    @classmethod
    def _normalize_response(
        cls,
        *,
        data: dict[str, Any],
        model: str,
        api_mode: str,
        endpoint: str,
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("xAI returned a non-object response.")

        if "_non_json_response" in data:
            raise ValueError(f"xAI returned non-JSON response: {data['_non_json_response'][:1000]}")

        if api_mode == "responses":
            output = cls._extract_responses_text(data)
            tool_calls = cls._extract_responses_tool_calls(data)
            citations = cls._extract_citations(data)
            response_id = data.get("id")
            status = data.get("status")
            usage = cls._normalize_usage(
                data.get("usage"),
                responses=True,
            )

            action = (
                "processing"
                if tool_calls and not output
                else DualNormalizationHub.normalize_text(output)
                if output
                else "error"
            )

            if action == "error" and status in {"completed", "succeeded"} and not output:
                message = "xAI completed the request without textual output."
            else:
                message = ""

            return {
                "status": "success" if action != "error" else "error",
                "output": output,
                "action": action,
                "message": message,
                "metadata": {
                    "framework": "grok",
                    "provider": "xai",
                    "model": data.get("model") or model,
                    "api_mode": api_mode,
                    "endpoint": endpoint,
                    "response_id": response_id,
                    "response_status": status,
                    "usage": usage,
                    "tool_calls": tool_calls,
                    "citations": citations,
                    "finish_reason": cls._extract_finish_reason(data),
                },
            }

        output = cls._extract_chat_text(data)
        tool_calls = cls._extract_chat_tool_calls(data)
        citations = cls._extract_citations(data)
        usage = cls._normalize_usage(
            data.get("usage"),
            responses=False,
        )

        action = (
            "processing"
            if tool_calls and not output
            else DualNormalizationHub.normalize_text(output)
            if output
            else "error"
        )

        return {
            "status": "success" if action != "error" else "error",
            "output": output,
            "action": action,
            "message": ("xAI returned no textual output." if action == "error" else ""),
            "metadata": {
                "framework": "grok",
                "provider": "xai",
                "model": data.get("model") or model,
                "api_mode": api_mode,
                "endpoint": endpoint,
                "response_id": data.get("id"),
                "usage": usage,
                "tool_calls": tool_calls,
                "citations": citations,
                "finish_reason": cls._extract_finish_reason(data),
            },
        }

    @staticmethod
    def _extract_responses_text(data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        chunks: list[str] = []

        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "message":
                continue

            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue

                if content.get("type") in {"output_text", "text"}:
                    text_value = content.get("text")
                    if isinstance(text_value, str):
                        chunks.append(text_value)

        return "".join(chunks).strip()

    @staticmethod
    def _extract_chat_text(data: dict[str, Any]) -> str:
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
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        chunks.append(text_value)

            return "".join(chunks).strip()

        return ""

    @staticmethod
    def _extract_responses_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("type", ""))

            if "call" not in item_type:
                continue

            calls.append(
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "name": item.get("name"),
                    "call_id": item.get("call_id"),
                    "arguments": item.get("arguments"),
                }
            )

        return calls

    @staticmethod
    def _extract_chat_tool_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
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
                    "type": call.get("type"),
                    "name": function.get("name"),
                    "arguments": function.get("arguments"),
                }
            )

        return normalized

    @staticmethod
    def _extract_citations(data: dict[str, Any]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    key_l = str(key).lower()

                    if key_l in {"url", "source_url"} and isinstance(child, str):
                        if child.startswith(("http://", "https://")):
                            citations.append({"url": child})

                    if key_l in {"citations", "sources", "annotations"}:
                        if isinstance(child, list):
                            for entry in child:
                                if isinstance(entry, dict):
                                    url = entry.get("url") or entry.get("source_url")
                                    if isinstance(url, str) and url.startswith(
                                        ("http://", "https://")
                                    ):
                                        citations.append(
                                            {
                                                "url": url,
                                                "title": entry.get("title"),
                                            }
                                        )

                    walk(child)

            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)

        # Stable deduplication.
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()

        for citation in citations:
            url = citation.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(citation)

        return deduped

    @staticmethod
    def _extract_finish_reason(data: dict[str, Any]) -> str | None:
        choices = data.get("choices") or []

        if choices and isinstance(choices[0], dict):
            reason = choices[0].get("finish_reason")
            if reason:
                return str(reason)

        status = data.get("status")
        return str(status) if status else None

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
            }

        if responses:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            total_tokens = usage.get("total_tokens")
        else:
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "raw": usage,
        }

    @staticmethod
    def _copy_if_present(
        source: dict[str, Any],
        target: dict[str, Any],
        *keys: str,
    ) -> None:
        for key in keys:
            value = source.get(key)
            if value is not None:
                target[key] = value

    @staticmethod
    def _extract_traceparent(payload: dict[str, Any]) -> str | None:
        span_context = payload.get("span_context")

        if not isinstance(span_context, dict):
            return None

        traceparent = span_context.get("traceparent")

        if not isinstance(traceparent, str):
            return None

        return traceparent

    @staticmethod
    def _sanitize_exception(exc: Exception) -> str:
        message = str(exc)

        # Avoid accidentally returning credentials or authorization material
        # embedded in third-party exception messages.
        for secret in (os.getenv("XAI_API_KEY"),):
            if secret:
                message = message.replace(secret, "[REDACTED]")

        return message
