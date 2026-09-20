# eval_runner/adapters/ollama.py

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import (
    BaseAdapter,
    DualNormalizationHub,
    bounded_text,
    coerce_timeout,
    json_safe,
    validate_http_endpoint,
)


class OllamaAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native Ollama adapter.

    Responsibilities:
      - Ollama /api/chat execution
      - normalized conversation/message construction
      - native tool calls
      - JSON / JSON-schema output formats
      - thinking
      - generation options
      - NDJSON streaming and non-streaming responses
      - keep_alive
      - logprobs / top_logprobs
      - lifecycle-scoped connection pooling through BaseAdapter
      - shared retry/backoff through BaseAdapter
      - normalized AgentV action envelopes
      - bounded telemetry/evidence metadata
    """

    _DEFAULT_RETRY_CODES = frozenset({408, 429, 500, 502, 503, 504})

    _OPTION_KEYS = frozenset(
        {
            "num_keep",
            "seed",
            "num_predict",
            "top_k",
            "top_p",
            "min_p",
            "typical_p",
            "repeat_last_n",
            "repeat_penalty",
            "presence_penalty",
            "frequency_penalty",
            "temperature",
            "mirostat",
            "mirostat_eta",
            "mirostat_tau",
            "tfs_z",
            "stop",
            "num_ctx",
            "num_batch",
            "num_gpu",
            "main_gpu",
            "low_vram",
            "vocab_only",
            "use_mmap",
            "use_mlock",
            "num_thread",
            "numa",
        }
    )

    _MAX_STREAM_LINE_BYTES = 2 * 1024 * 1024
    _MAX_ERROR_BODY_CHARS = 8_192
    _MAX_RAW_RESPONSE_CHARS = 64 * 1024

    def __init__(self, session_pool: Any | None = None) -> None:
        BaseAdapter.__init__(
            self,
            name="ollama",
            session_pool=session_pool,
        )

    def on_discover_adapters(self, registry: Any) -> None:
        registry.register("ollama", self.execute_ollama_query)

    async def execute_ollama_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute one Ollama chat turn.

        Transport/session lifecycle and retry behavior are delegated to the
        shared BaseAdapter/common.py implementation. Provider-specific logic
        remains limited to request construction and Ollama response handling.
        """
        started = time.perf_counter()

        try:
            request_payload = self._build_request_payload(payload)
            endpoint = self._resolve_endpoint(payload, url)

            timeout_seconds = coerce_timeout(
                payload.get("timeout", payload.get("adapter_timeout")),
                default=float(config.DEFAULT_ADAPTER_TIMEOUT),
            )

            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            headers = self._build_headers(payload)

            async def _call() -> dict[str, Any]:
                # BaseAdapter.get_session() is lifecycle-aware and resolves
                # the session against the active event loop.
                async with self.get_session() as session:
                    async with session.post(
                        endpoint,
                        json=request_payload,
                        headers=headers,
                        timeout=timeout,
                    ) as response:
                        if response.status >= 400:
                            body = await self._safe_response_text(response)

                            raise aiohttp.ClientResponseError(
                                response.request_info,
                                response.history,
                                status=response.status,
                                message=body,
                                headers=response.headers,
                            )

                        if request_payload["stream"]:
                            return await self._read_streaming_response(response)

                        return await self._read_json_response(response)

            response_data = await self.call_with_retry(
                _call,
                retry_codes=self._DEFAULT_RETRY_CODES,
            )

            result = self._normalize_response(
                response_data=response_data,
                payload=payload,
            )

            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            metadata = result.setdefault("metadata", {})

            metadata.update(
                self._build_response_metadata(
                    response_data=response_data,
                    request_payload=request_payload,
                    endpoint=endpoint,
                    latency_ms=latency_ms,
                )
            )

            self._emit_usage_metrics(
                response_data=response_data,
                metadata=metadata,
            )

            return result

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

            endpoint = self._safe_endpoint_for_metadata(
                self._resolve_endpoint_candidate(payload, url)
            )

            emit(
                "metric_update",
                {
                    "adapter": "ollama",
                    "status": "error",
                    "latency_ms": latency_ms,
                },
            )

            return {
                "status": "error",
                "action": "error",
                "message": f"Ollama request failed: {bounded_text(str(exc), 2_000)}",
                "metadata": {
                    "framework": "ollama",
                    "endpoint": endpoint,
                    "model": payload.get("model")
                    or payload.get("ollama_model")
                    or config.OLLAMA_MODEL,
                    "latency_ms": latency_ms,
                    "error_type": type(exc).__name__,
                },
            }

    # ------------------------------------------------------------------
    # Endpoint / request construction
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_endpoint(
        cls,
        payload: dict[str, Any],
        url: str | None,
    ) -> str:
        endpoint = cls._resolve_endpoint_candidate(payload, url)

        endpoint = cls._normalize_chat_endpoint(
            endpoint,
            source_was_explicit_url=url is not None,
        )

        validate_http_endpoint(endpoint)
        return endpoint

    @staticmethod
    def _resolve_endpoint_candidate(
        payload: dict[str, Any],
        url: str | None,
    ) -> str:
        endpoint = (
            url or payload.get("ollama_url") or payload.get("base_url") or config.OLLAMA_API_URL
        )

        endpoint = str(endpoint).strip()

        if not endpoint:
            raise ValueError("Ollama endpoint is required.")

        return endpoint

    @staticmethod
    def _normalize_chat_endpoint(
        endpoint: str,
        *,
        source_was_explicit_url: bool,
    ) -> str:
        """
        Preserve explicit endpoint URLs while allowing base_url style inputs.

        Examples:
          http://localhost:11434
          -> http://localhost:11434/api/chat

          http://localhost:11434/api
          -> http://localhost:11434/api/chat

          http://localhost:11434/api/chat
          -> unchanged
        """
        parsed = urlsplit(endpoint)

        path = parsed.path.rstrip("/")

        if source_was_explicit_url:
            return endpoint

        if path in {"", "/"}:
            path = "/api/chat"
        elif path == "/api":
            path = "/api/chat"
        elif not path.endswith("/api/chat"):
            # ollama_url/base_url may be supplied as a fully qualified native
            # endpoint. Preserve nonstandard paths rather than silently
            # rewriting them.
            pass

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                path,
                parsed.query,
                parsed.fragment,
            )
        )

    @staticmethod
    def _safe_endpoint_for_metadata(endpoint: str) -> str:
        try:
            parsed = urlsplit(str(endpoint))
            return urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    "",
                    "",
                )
            )
        except Exception:
            return "<invalid-endpoint>"

    @staticmethod
    def _build_headers(payload: dict[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        raw_headers = payload.get("headers")
        if raw_headers is not None:
            if not isinstance(raw_headers, dict):
                raise TypeError("Ollama 'headers' must be an object.")

            for key, value in raw_headers.items():
                if value is None:
                    continue

                key_str = str(key).strip()
                value_str = str(value)

                if key_str:
                    headers[key_str] = value_str

        authorization = payload.get("api_key") or payload.get("ollama_api_key")
        if authorization:
            headers.setdefault(
                "Authorization",
                f"Bearer {str(authorization).strip()}",
            )

        traceparent = payload.get("traceparent")
        if traceparent:
            headers.setdefault("traceparent", str(traceparent))

        return headers

    def _build_request_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        model = str(
            payload.get("model") or payload.get("ollama_model") or config.OLLAMA_MODEL
        ).strip()

        if not model:
            raise ValueError("Ollama model is required.")

        messages = self._normalize_messages(payload)

        if not messages:
            raise ValueError("Ollama request requires at least one message.")

        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": self._coerce_bool(payload.get("stream", False)),
        }

        for key in (
            "tools",
            "format",
            "think",
            "keep_alive",
            "logprobs",
            "top_logprobs",
        ):
            value = payload.get(key)

            if value is not None:
                request[key] = value

        options = payload.get("options")

        if options is not None:
            if not isinstance(options, dict):
                raise TypeError("Ollama 'options' must be an object.")

            request["options"] = dict(options)
        else:
            extracted_options = self._extract_options(payload)

            if extracted_options:
                request["options"] = extracted_options

        return request

    @classmethod
    def _normalize_messages(
        cls,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        messages: list[dict[str, Any]] = []

        if raw_messages is not None:
            if not isinstance(raw_messages, list):
                raise TypeError("Ollama 'messages'/'history' must be a list.")

            for raw in raw_messages:
                normalized = cls._normalize_message(raw)

                if normalized is not None:
                    messages.append(normalized)

        if not messages:
            content = (
                payload.get("task_description")
                or payload.get("task")
                or payload.get("prompt")
                or payload.get("message")
                or payload.get("input")
            )

            if content is not None:
                if isinstance(content, (dict, list)):
                    content = json.dumps(
                        content,
                        ensure_ascii=False,
                        sort_keys=True,
                    )

                messages.append(
                    {
                        "role": "user",
                        "content": str(content),
                    }
                )

        system_prompt = payload.get("system_prompt") or payload.get("system")

        if system_prompt:
            if isinstance(system_prompt, (dict, list)):
                system_prompt = json.dumps(
                    system_prompt,
                    ensure_ascii=False,
                    sort_keys=True,
                )

            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = str(system_prompt)
            else:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": str(system_prompt),
                    },
                )

        images = payload.get("images")

        if images is not None:
            if not isinstance(images, list):
                raise TypeError("Ollama 'images' must be a list.")

            target = next(
                (message for message in reversed(messages) if message.get("role") == "user"),
                None,
            )

            if target is None:
                raise ValueError("Ollama images require a user message.")

            target["images"] = list(images)

        return messages

    @staticmethod
    def _normalize_message(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None

        role = str(raw.get("role") or "").strip().lower()

        if role == "agent":
            role = "assistant"
        elif role == "human":
            role = "user"

        if role not in {"system", "user", "assistant", "tool"}:
            return None

        message: dict[str, Any] = {
            "role": role,
            "content": raw.get("content", ""),
        }

        for field in (
            "tool_name",
            "tool_call_id",
            "thinking",
            "images",
            "tool_calls",
        ):
            if field in raw and raw[field] is not None:
                message[field] = raw[field]

        return message

    @classmethod
    def _extract_options(
        cls,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        options: dict[str, Any] = {}

        for key in cls._OPTION_KEYS:
            if key in payload and payload[key] is not None:
                options[key] = payload[key]

        if "max_tokens" in payload and "num_predict" not in options:
            options["num_predict"] = payload["max_tokens"]

        return options

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {"1", "true", "yes", "on"}:
                return True

            if normalized in {"0", "false", "no", "off", ""}:
                return False

        return bool(value)

    # ------------------------------------------------------------------
    # HTTP response handling
    # ------------------------------------------------------------------

    @classmethod
    async def _read_json_response(
        cls,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        try:
            data = await response.json(content_type=None)
        except (
            aiohttp.ContentTypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            body = await cls._safe_response_text(response)

            raise ValueError(
                f"Ollama returned invalid JSON: {bounded_text(body, cls._MAX_ERROR_BODY_CHARS)}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(f"Ollama returned an unexpected response type: {type(data).__name__}")

        return data

    @classmethod
    async def _read_streaming_response(
        cls,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        """
        Consume Ollama's NDJSON response and reconstruct one canonical
        response object.

        Invalid non-empty NDJSON is treated as a transport/protocol failure.
        The adapter does not silently convert malformed streams into successful
        partial results.
        """
        final_response: dict[str, Any] = {}
        final_message: dict[str, Any] = {}

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        images: list[str] = []

        buffer = bytearray()
        done_seen = False

        async for chunk in response.content.iter_any():
            if not chunk:
                continue

            buffer.extend(chunk)

            if len(buffer) > cls._MAX_STREAM_LINE_BYTES:
                raise ValueError(
                    "Ollama streaming response exceeded the maximum NDJSON line buffer size."
                )

            while True:
                newline_index = buffer.find(b"\n")

                if newline_index < 0:
                    break

                raw_line = bytes(buffer[:newline_index])
                del buffer[: newline_index + 1]

                line = raw_line.strip()

                if not line:
                    continue

                partial = cls._parse_stream_line(line)

                cls._merge_stream_chunk(
                    final_response,
                    final_message,
                    content_parts,
                    thinking_parts,
                    tool_calls,
                    images,
                    partial,
                )

                if partial.get("done") is True:
                    done_seen = True
                    break

            if done_seen:
                break

            if len(buffer) > cls._MAX_STREAM_LINE_BYTES:
                raise ValueError("Ollama streaming response contains an oversized NDJSON line.")

        trailing = bytes(buffer).strip()

        if trailing:
            partial = cls._parse_stream_line(trailing)

            cls._merge_stream_chunk(
                final_response,
                final_message,
                content_parts,
                thinking_parts,
                tool_calls,
                images,
                partial,
            )

        if content_parts:
            final_message["content"] = "".join(content_parts)

        if thinking_parts:
            final_message["thinking"] = "".join(thinking_parts)

        if tool_calls:
            final_message["tool_calls"] = tool_calls

        if images:
            final_message["images"] = images

        final_response["message"] = final_message

        if done_seen:
            final_response["done"] = True
        else:
            final_response.setdefault("done", True)

        return final_response

    @staticmethod
    def _parse_stream_line(
        line: bytes,
    ) -> dict[str, Any]:
        try:
            value = json.loads(line.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("Ollama returned malformed NDJSON during streaming.") from exc

        if not isinstance(value, dict):
            raise ValueError("Ollama streaming response contained a non-object JSON value.")

        return value

    @staticmethod
    def _merge_stream_chunk(
        final_response: dict[str, Any],
        final_message: dict[str, Any],
        content_parts: list[str],
        thinking_parts: list[str],
        tool_calls: list[dict[str, Any]],
        images: list[str],
        chunk: dict[str, Any],
    ) -> None:
        message = chunk.get("message")

        if isinstance(message, dict):
            role = message.get("role")

            if role is not None:
                final_message.setdefault("role", str(role))

            content = message.get("content")

            if content:
                content_parts.append(str(content))

            thinking = message.get("thinking")

            if thinking:
                thinking_parts.append(str(thinking))

            chunk_tool_calls = message.get("tool_calls")

            if isinstance(chunk_tool_calls, list):
                for tool_call in chunk_tool_calls:
                    if isinstance(tool_call, dict):
                        tool_calls.append(tool_call)

            chunk_images = message.get("images")

            if isinstance(chunk_images, list):
                images.extend(str(image) for image in chunk_images)

            for nested_key, nested_value in message.items():
                if nested_key not in {
                    "role",
                    "content",
                    "thinking",
                    "tool_calls",
                    "images",
                }:
                    final_message[nested_key] = nested_value

        for key, value in chunk.items():
            if key != "message":
                final_response[key] = value

    @classmethod
    async def _safe_response_text(
        cls,
        response: aiohttp.ClientResponse,
    ) -> str:
        try:
            return await response.text()
        except Exception:
            return "<unavailable>"

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    def _normalize_response(
        self,
        response_data: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        message = response_data.get("message")

        if not isinstance(message, dict):
            raise ValueError("Ollama response is missing a valid 'message' object.")

        content = message.get("content", "")

        if content is None:
            content = ""

        if not isinstance(content, str):
            content = str(content)

        thinking = message.get("thinking")
        tool_calls = message.get("tool_calls") or []
        images = message.get("images") or []

        if not isinstance(tool_calls, list):
            raise ValueError("Ollama response 'tool_calls' must be a list.")

        if tool_calls:
            action_envelope = self._build_tool_action(
                tool_calls=tool_calls,
                content=content,
                thinking=thinking,
                images=images,
                response_data=response_data,
            )
        else:
            action_envelope = self._build_text_action(
                content=content,
                response_data=response_data,
            )

        action_envelope.setdefault("metadata", {})

        action_envelope["metadata"].update(
            {
                "thinking": thinking,
                "images": images,
                "response_model": response_data.get("model"),
                "done": response_data.get("done"),
                "done_reason": response_data.get("done_reason"),
                "prompt_eval_count": response_data.get("prompt_eval_count"),
                "eval_count": response_data.get("eval_count"),
            }
        )

        return action_envelope

    @staticmethod
    def _build_tool_action(
        tool_calls: list[Any],
        content: str,
        thinking: Any,
        images: list[Any],
        response_data: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_calls: list[dict[str, Any]] = []

        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue

            function = raw_call.get("function")

            if not isinstance(function, dict):
                continue

            name = function.get("name")
            arguments = function.get("arguments", {})

            if not name:
                continue

            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {
                        "raw_arguments": arguments,
                    }

            if not isinstance(arguments, dict):
                arguments = {
                    "value": arguments,
                }

            normalized_call: dict[str, Any] = {
                "tool": str(name),
                "params": arguments,
            }

            call_id = raw_call.get("id")

            if call_id:
                normalized_call["call_id"] = str(call_id)

            normalized_calls.append(normalized_call)

        if not normalized_calls:
            return {
                "status": "error",
                "action": "error",
                "message": "Ollama returned malformed tool calls.",
                "metadata": {
                    "raw_response": OllamaAdapterPlugin._safe_raw_response(response_data),
                },
            }

        if len(normalized_calls) == 1:
            call = normalized_calls[0]

            return {
                "status": "success",
                "action": "call_tool",
                "tool_name": call["tool"],
                "tool_params": call["params"],
                "summary": content,
                "thinking": thinking,
                "images": images,
                "metadata": {
                    "tool_calls": normalized_calls,
                },
            }

        return {
            "status": "success",
            "action": "call_multiple_tools",
            "tool_calls": normalized_calls,
            "summary": content,
            "thinking": thinking,
            "images": images,
            "metadata": {
                "tool_calls": normalized_calls,
            },
        }

    @staticmethod
    def _build_text_action(
        content: str,
        response_data: dict[str, Any],
    ) -> dict[str, Any]:
        if not content.strip():
            return {
                "status": "error",
                "action": "error",
                "message": "Ollama returned an empty assistant message.",
                "metadata": {
                    "raw_response": OllamaAdapterPlugin._safe_raw_response(response_data),
                },
            }

        action = DualNormalizationHub.normalize_text(content)

        return {
            "status": "success",
            "action": action,
            "output": content,
            "summary": content,
            "content": content,
        }

    # ------------------------------------------------------------------
    # Metadata / telemetry
    # ------------------------------------------------------------------

    @classmethod
    def _build_response_metadata(
        cls,
        response_data: dict[str, Any],
        request_payload: dict[str, Any],
        endpoint: str,
        latency_ms: float,
    ) -> dict[str, Any]:
        return {
            "framework": "ollama",
            "endpoint": cls._safe_endpoint_for_metadata(endpoint),
            "model": response_data.get("model") or request_payload.get("model"),
            "stream": bool(request_payload.get("stream")),
            "latency_ms": latency_ms,
            "done": response_data.get("done"),
            "done_reason": response_data.get("done_reason"),
            "created_at": response_data.get("created_at"),
            "total_duration_ns": response_data.get("total_duration"),
            "load_duration_ns": response_data.get("load_duration"),
            "prompt_eval_duration_ns": response_data.get("prompt_eval_duration"),
            "eval_duration_ns": response_data.get("eval_duration"),
            "prompt_eval_cached_count": response_data.get("prompt_eval_cached_count"),
            "raw_response": cls._safe_raw_response(response_data),
        }

    @classmethod
    def _safe_raw_response(
        cls,
        response_data: Any,
    ) -> dict[str, Any] | str:
        try:
            safe = json_safe(response_data)
        except Exception:
            return "<unserializable-response>"

        try:
            encoded = json.dumps(
                safe,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except Exception:
            return "<unserializable-response>"

        if len(encoded) <= cls._MAX_RAW_RESPONSE_CHARS:
            return safe if isinstance(safe, dict) else encoded

        return {
            "truncated": True,
            "content": bounded_text(
                encoded,
                cls._MAX_RAW_RESPONSE_CHARS,
            ),
        }

    @staticmethod
    def _emit_usage_metrics(
        response_data: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        prompt_tokens = response_data.get("prompt_eval_count")
        completion_tokens = response_data.get("eval_count")

        try:
            numeric_prompt = int(prompt_tokens or 0)
        except (TypeError, ValueError):
            numeric_prompt = 0

        try:
            numeric_completion = int(completion_tokens or 0)
        except (TypeError, ValueError):
            numeric_completion = 0

        total_tokens = numeric_prompt + numeric_completion

        metadata["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        emit(
            "metric_update",
            {
                "adapter": "ollama",
                "tokens": total_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": metadata.get("latency_ms"),
                "total_duration_ns": response_data.get("total_duration"),
                "load_duration_ns": response_data.get("load_duration"),
                "prompt_eval_duration_ns": response_data.get("prompt_eval_duration"),
                "eval_duration_ns": response_data.get("eval_duration"),
            },
        )


__all__ = ["OllamaAdapterPlugin"]
