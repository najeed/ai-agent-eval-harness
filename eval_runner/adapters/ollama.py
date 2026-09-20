# eval_runner/adapters/ollama.py

from __future__ import annotations

import json
import time
from typing import Any

import aiohttp

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class OllamaAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native Ollama adapter.

    Supports:
      - /api/chat
      - chat history / task_description normalization
      - tools / tool calls
      - JSON / JSON-schema output formats
      - thinking
      - generation options
      - streaming and non-streaming responses
      - keep_alive
      - logprobs / top_logprobs
      - retry / connection pooling
      - normalized AgentV action envelopes
      - token / latency telemetry
    """

    _DEFAULT_RETRY_CODES = {408, 429, 500, 502, 503, 504}

    _OPTION_KEYS = {
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

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="ollama")

    def on_discover_adapters(self, registry: Any) -> None:
        """Register the Ollama protocol."""
        registry.register("ollama", self.execute_ollama_query)

    async def execute_ollama_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute one Ollama chat turn and normalize the result to AgentV's
        runtime action contract.
        """
        started = time.perf_counter()
        import asyncio

        try:
            request_payload = self._build_request_payload(payload)

            endpoint = (
                url or payload.get("ollama_url") or payload.get("base_url") or config.OLLAMA_API_URL
            )

            timeout_seconds = self._resolve_timeout(payload)
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)

            async def _call() -> dict[str, Any]:
                session = await SessionManager.get_session()

                async with session.post(
                    endpoint,
                    json=request_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout,
                ) as response:
                    status_code = response.status

                    if status_code >= 400:
                        body = await self._safe_response_text(response)
                        response.raise_for_status()
                        raise RuntimeError(
                            f"Ollama request failed with HTTP {status_code}: {body[:1000]}"
                        )

                    if request_payload["stream"]:
                        return await self._read_streaming_response(response)

                    try:
                        data = await response.json()
                    except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
                        body = await self._safe_response_text(response)
                        raise RuntimeError(f"Ollama returned invalid JSON: {body[:1000]}") from exc

                    if not isinstance(data, dict):
                        raise RuntimeError(
                            f"Ollama returned unexpected response type: {type(data).__name__}"
                        )

                    return data

            response_data = await self.call_with_retry(
                _call,
                retry_codes=self._DEFAULT_RETRY_CODES,
            )

            result = self._normalize_response(response_data, payload)

            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            metadata = result.setdefault("metadata", {})

            metadata.update(
                {
                    "framework": "ollama",
                    "endpoint": endpoint,
                    "model": response_data.get("model") or request_payload.get("model"),
                    "stream": request_payload["stream"],
                    "latency_ms": latency_ms,
                    "done": response_data.get("done"),
                    "done_reason": response_data.get("done_reason"),
                    "created_at": response_data.get("created_at"),
                    "total_duration_ns": response_data.get("total_duration"),
                    "load_duration_ns": response_data.get("load_duration"),
                    "prompt_eval_duration_ns": response_data.get("prompt_eval_duration"),
                    "eval_duration_ns": response_data.get("eval_duration"),
                    "prompt_eval_cached_count": response_data.get("prompt_eval_cached_count"),
                    "raw_response": response_data,
                }
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
                "message": f"Ollama request failed: {exc}",
                "metadata": {
                    "framework": "ollama",
                    "endpoint": url
                    or payload.get("ollama_url")
                    or payload.get("base_url")
                    or config.OLLAMA_API_URL,
                    "model": payload.get("model", config.OLLAMA_MODEL),
                    "latency_ms": latency_ms,
                },
            }

    def _build_request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Build the canonical Ollama /api/chat request.

        AgentV's dispatcher supplies task_description as the primary message;
        legacy task/prompt/input forms remain supported.
        """
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
            "stream": bool(payload.get("stream", False)),
        }

        # Optional first-class Ollama request fields.
        for key in ("tools", "format", "think", "keep_alive", "logprobs", "top_logprobs"):
            if key in payload and payload[key] is not None:
                request[key] = payload[key]

        # Explicit options mapping takes precedence.
        options = payload.get("options")
        if options is not None:
            if not isinstance(options, dict):
                raise TypeError("Ollama 'options' must be an object.")
            request["options"] = dict(options)
        else:
            options = self._extract_options(payload)
            if options:
                request["options"] = options

        return request

    @classmethod
    def _normalize_messages(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = payload.get("messages")

        if raw_messages is None:
            raw_messages = payload.get("history")

        messages: list[dict[str, Any]] = []

        if isinstance(raw_messages, list):
            for raw in raw_messages:
                if not isinstance(raw, dict):
                    continue

                role = str(raw.get("role") or "").strip().lower()
                if role == "agent":
                    role = "assistant"
                elif role == "human":
                    role = "user"

                if role not in {"system", "user", "assistant", "tool"}:
                    continue

                message: dict[str, Any] = {
                    "role": role,
                    "content": raw.get("content", ""),
                }

                for field in ("tool_name", "tool_call_id", "thinking", "images", "tool_calls"):
                    if field in raw and raw[field] is not None:
                        message[field] = raw[field]

                messages.append(message)

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
                    content = json.dumps(content, ensure_ascii=False, sort_keys=True)
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

        # Convenience for image-capable models when images are supplied at the
        # envelope level rather than directly on a message.
        images = payload.get("images")
        if images:
            if not isinstance(images, list):
                raise TypeError("Ollama 'images' must be a list.")
            target = next(
                (m for m in reversed(messages) if m.get("role") == "user"),
                None,
            )
            if target is None:
                raise ValueError("Ollama images require a user message.")
            target["images"] = list(images)

        return messages

    @classmethod
    def _extract_options(cls, payload: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {}

        for key in cls._OPTION_KEYS:
            if key in payload and payload[key] is not None:
                options[key] = payload[key]

        # Backward-compatible aliases used by common AgentV payloads.
        if "max_tokens" in payload and "num_predict" not in options:
            options["num_predict"] = payload["max_tokens"]

        return options

    @staticmethod
    def _resolve_timeout(payload: dict[str, Any]) -> float:
        raw = payload.get("timeout", payload.get("adapter_timeout"))
        if raw is None:
            return float(config.DEFAULT_ADAPTER_TIMEOUT)

        timeout = float(raw)
        if timeout <= 0:
            raise ValueError("Ollama timeout must be greater than zero.")
        return timeout

    @classmethod
    async def _read_streaming_response(
        cls,
        response: aiohttp.ClientResponse,
    ) -> dict[str, Any]:
        """
        Read Ollama's newline-delimited JSON stream.

        Ollama /api/chat streams JSON objects separated by newlines rather than
        Server-Sent Events.
        """
        final_response: dict[str, Any] = {}
        final_message: dict[str, Any] = {}
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        images: list[str] = []

        buffer = ""

        async for chunk in response.content.iter_any():
            if not chunk:
                continue

            buffer += chunk.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if not line:
                    continue

                partial = cls._parse_stream_line(line)
                if partial is None:
                    continue

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
                    buffer = buffer.strip()
                    if buffer:
                        trailing = cls._parse_stream_line(buffer)
                        if trailing is not None:
                            cls._merge_stream_chunk(
                                final_response,
                                final_message,
                                content_parts,
                                thinking_parts,
                                tool_calls,
                                images,
                                trailing,
                            )
                        buffer = ""
                    break

        if buffer.strip():
            trailing = cls._parse_stream_line(buffer.strip())
            if trailing is not None:
                cls._merge_stream_chunk(
                    final_response,
                    final_message,
                    content_parts,
                    thinking_parts,
                    tool_calls,
                    images,
                    trailing,
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
        final_response.setdefault("done", True)

        return final_response

    @staticmethod
    def _parse_stream_line(line: str) -> dict[str, Any] | None:
        if not line:
            return None

        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None

        return value if isinstance(value, dict) else None

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
        for key, value in chunk.items():
            if key == "message":
                message = value if isinstance(value, dict) else {}
                if "role" in message:
                    final_message.setdefault("role", message["role"])

                content = message.get("content")
                if content:
                    content_parts.append(str(content))

                thinking = message.get("thinking")
                if thinking:
                    thinking_parts.append(str(thinking))

                chunk_tool_calls = message.get("tool_calls")
                if isinstance(chunk_tool_calls, list):
                    tool_calls.extend(chunk_tool_calls)

                chunk_images = message.get("images")
                if isinstance(chunk_images, list):
                    images.extend(str(img) for img in chunk_images)

                for nested_key in message:
                    if nested_key not in {
                        "role",
                        "content",
                        "thinking",
                        "tool_calls",
                        "images",
                    }:
                        final_message[nested_key] = message[nested_key]
            elif key not in {"message"}:
                final_response[key] = value

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
                    arguments = {"raw_arguments": arguments}

            if not isinstance(arguments, dict):
                arguments = {"value": arguments}

            normalized_calls.append(
                {
                    "tool": str(name),
                    "params": arguments,
                }
            )

        if not normalized_calls:
            return {
                "status": "error",
                "action": "error",
                "message": "Ollama returned malformed tool calls.",
                "metadata": {
                    "raw_response": response_data,
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
                    "raw_response": response_data,
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

    @staticmethod
    def _emit_usage_metrics(
        response_data: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        prompt_tokens = response_data.get("prompt_eval_count")
        completion_tokens = response_data.get("eval_count")

        numeric_prompt = int(prompt_tokens or 0)
        numeric_completion = int(completion_tokens or 0)
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

    @staticmethod
    async def _safe_response_text(response: aiohttp.ClientResponse) -> str:
        try:
            return await response.text()
        except Exception:
            return "<unavailable>"
