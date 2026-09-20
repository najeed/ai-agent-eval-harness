# eval_runner/adapters/gemini.py
from __future__ import annotations

import asyncio
import os
import random
from copy import deepcopy
from typing import Any

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub


class GeminiAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production Gemini adapter using the official google-genai SDK.

    Supported capabilities:
      - Gemini Developer API and Vertex AI / Gemini Enterprise
      - Multi-turn contents/messages
      - System instructions
      - Generation controls
      - Structured JSON / JSON Schema output
      - Function/tool declarations
      - Safety settings
      - Thinking configuration
      - Multimodal/content parts passed through to the SDK
      - Usage and response metadata
      - Async execution
      - SDK error classification and retry with jitter
      - Explicit request timeout
      - Fail-closed handling of empty/invalid responses

    Wire contract accepted by the adapter is intentionally provider-neutral.
    """

    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BACKOFF_BASE = 1.0
    DEFAULT_BACKOFF_MAX = 30.0
    RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

    def __init__(self):
        BaseAdapter.__init__(self, name="gemini")

    def on_discover_adapters(self, registry: Any):
        """Register the gemini protocol."""
        print("      [Plugin] Registering Gemini adapter via on_discover_adapters hook.")
        registry.register("gemini", self.execute_gemini_query)

    # ------------------------------------------------------------------
    # Public execution API
    # ------------------------------------------------------------------

    async def execute_gemini_query(
        self,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute one Gemini request through google-genai.

        `url` is retained for the engine's adapter signature. It is used only
        for legacy Vertex-AI detection; the google-genai SDK remains the
        authoritative transport.
        """
        try:
            from google import genai
            from google.genai import errors as genai_errors, types
        except ImportError as exc:
            return {
                "status": "error",
                "action": "error",
                "message": (
                    "Gemini adapter requires the 'google-genai' package. "
                    "Install the provider-gemini extra."
                ),
                "metadata": {
                    "framework": "gemini",
                    "dependency_error": str(exc),
                },
            }

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        provider_config = metadata.get("gemini")
        if not isinstance(provider_config, dict):
            provider_config = {}

        merged = deepcopy(provider_config)
        for key, value in payload.items():
            if key != "metadata":
                merged[key] = value

        model = str(
            merged.get("model")
            or config.GEMINI_MODEL
            or os.getenv("GEMINI_MODEL")
            or "gemini-2.5-flash"
        ).strip()

        if not model:
            return self._error(
                "Gemini model is required.",
                metadata={"framework": "gemini"},
            )

        vertexai = self._resolve_vertex_mode(merged, url)

        api_key = (
            merged.get("api_key")
            or config.GOOGLE_API_KEY
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )

        project = (
            merged.get("project")
            or merged.get("google_cloud_project")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
        )

        location = (
            merged.get("location")
            or merged.get("google_cloud_location")
            or os.getenv("GOOGLE_CLOUD_LOCATION")
            or "us-central1"
        )

        credentials = merged.get("credentials")

        if not vertexai and not api_key:
            return self._error(
                "Gemini API key missing. Set GOOGLE_API_KEY/GEMINI_API_KEY or provide api_key.",
                metadata={"framework": "gemini", "model": model},
            )

        if vertexai and not credentials and not project:
            # google-genai can resolve Application Default Credentials from the environment,
            # so project may still be absent in some externally configured environments.
            # Do not reject the configuration here.
            pass

        client_kwargs: dict[str, Any] = {
            "vertexai": vertexai,
        }

        if api_key is not None:
            client_kwargs["api_key"] = api_key

        if vertexai:
            if project:
                client_kwargs["project"] = project
            if location:
                client_kwargs["location"] = location
            if credentials is not None:
                client_kwargs["credentials"] = credentials

        http_options = self._build_http_options(
            merged,
            types=types,
        )
        if http_options is not None:
            client_kwargs["http_options"] = http_options

        client = None

        try:
            client = genai.Client(**client_kwargs)

            contents, system_instruction = self._build_contents(
                merged,
                types=types,
            )

            if not contents:
                return self._error(
                    "Gemini request contains no user/model/tool contents.",
                    metadata={"framework": "gemini", "model": model},
                )

            generation_config = self._build_generation_config(
                merged,
                types=types,
                system_instruction=system_instruction,
            )

            timeout_seconds = self._resolve_timeout(merged)

            async def _call():
                request = {
                    "model": model,
                    "contents": contents,
                }

                if generation_config is not None:
                    request["config"] = generation_config

                async_call = client.aio.models.generate_content(**request)

                if timeout_seconds is not None and timeout_seconds > 0:
                    return await asyncio.wait_for(
                        async_call,
                        timeout=timeout_seconds,
                    )

                return await async_call

            response = await self._call_with_sdk_retry(
                _call,
                genai_errors=genai_errors,
                max_attempts=self._resolve_max_retries(merged),
                base_delay=self._resolve_backoff_base(merged),
                max_delay=self._resolve_backoff_max(merged),
            )

            result = self._normalize_response(
                response=response,
                model=model,
                vertexai=vertexai,
                project=project,
                location=location,
            )

            if result["status"] == "success":
                self._emit_usage(result["metadata"])

            return result

        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._error(
                f"Gemini request timed out after {self._resolve_timeout(merged):g}s.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "vertexai": vertexai,
                },
            )
        except Exception as exc:
            status_code = self._extract_status_code(exc)

            metadata = {
                "framework": "gemini",
                "model": model,
                "vertexai": vertexai,
                "error_type": type(exc).__name__,
            }

            if status_code is not None:
                metadata["status_code"] = status_code

            return self._error(
                self._safe_error_message(exc),
                metadata=metadata,
            )

        finally:
            if client is not None:
                try:
                    await client.aio.aclose()
                except Exception as exc:
                    # Cleanup failure must not replace the actual evaluation result.
                    print(f"      [Gemini] Client cleanup warning: {exc}")

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_vertex_mode(payload: dict[str, Any], url: str | None) -> bool:
        explicit = payload.get("vertexai")
        if explicit is not None:
            return bool(explicit)

        explicit = payload.get("vertex_ai")
        if explicit is not None:
            return bool(explicit)

        if str(payload.get("deployment", "")).lower() == "vertex":
            return True

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("vertexai") is not None:
                return bool(metadata["vertexai"])
            if metadata.get("vertex_ai") is not None:
                return bool(metadata["vertex_ai"])

        return "vertex" in str(url or "").lower()

    @staticmethod
    def _build_contents(
        payload: dict[str, Any],
        *,
        types: Any,
    ) -> tuple[Any, str | None]:
        """
        Build SDK-compatible contents.

        Priority:
          1. Explicit `contents`
          2. Provider-neutral `messages`
          3. `task_description`
          4. `task` / `prompt` / `input`
        """
        system_instruction = payload.get("system_instruction") or payload.get("system_prompt")

        explicit_contents = payload.get("contents")
        if explicit_contents is not None:
            contents = deepcopy(explicit_contents)

            if system_instruction is None:
                system_instruction = payload.get("system")

            return contents, system_instruction

        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise TypeError("Gemini 'messages' must be a list.")

            normalized_messages: list[Any] = []

            for message in messages:
                if isinstance(message, str):
                    normalized_messages.append(
                        {
                            "role": "user",
                            "parts": [{"text": message}],
                        }
                    )
                    continue

                if not isinstance(message, dict):
                    raise TypeError("Each Gemini message must be a string or object.")

                role = str(message.get("role", "user")).lower().strip()

                if role == "system":
                    if system_instruction is None:
                        system_instruction = GeminiAdapterPlugin._extract_message_text(
                            message.get("content")
                        )
                    continue

                gemini_role = {
                    "assistant": "model",
                    "ai": "model",
                    "model": "model",
                    "user": "user",
                    "human": "user",
                    "tool": "tool",
                    "function": "tool",
                }.get(role, "user")

                parts = GeminiAdapterPlugin._normalize_message_parts(
                    message.get("content"),
                    message=message,
                )

                if not parts:
                    continue

                normalized_messages.append(
                    {
                        "role": gemini_role,
                        "parts": parts,
                    }
                )

            return normalized_messages, system_instruction

        task = (
            payload.get("task_description")
            or payload.get("task")
            or payload.get("prompt")
            or payload.get("input")
        )

        if task is None:
            return [], system_instruction

        if isinstance(task, str):
            return (
                [
                    {
                        "role": "user",
                        "parts": [{"text": task}],
                    }
                ],
                system_instruction,
            )

        if isinstance(task, list):
            return task, system_instruction

        return (
            [
                {
                    "role": "user",
                    "parts": [{"text": str(task)}],
                }
            ],
            system_instruction,
        )

    @staticmethod
    def _normalize_message_parts(
        content: Any,
        *,
        message: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if content is None:
            # Some agent protocols represent function/tool responses separately.
            for key in (
                "parts",
                "tool_response",
                "function_response",
                "function_call",
            ):
                if key in message:
                    return GeminiAdapterPlugin._normalize_message_parts(
                        message[key],
                        message={},
                    )
            return []

        if isinstance(content, str):
            return [{"text": content}]

        if isinstance(content, dict):
            return GeminiAdapterPlugin._normalize_single_part(content)

        if not isinstance(content, list):
            return [{"text": str(content)}]

        parts: list[dict[str, Any]] = []

        for item in content:
            if isinstance(item, str):
                parts.append({"text": item})
                continue

            if isinstance(item, dict):
                parts.extend(GeminiAdapterPlugin._normalize_single_part(item))
                continue

            parts.append({"text": str(item)})

        return parts

    @staticmethod
    def _normalize_single_part(part: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Accept native Gemini parts and common provider-neutral representations.
        """
        if not part:
            return []

        # Already-native Gemini part forms.
        native_keys = {
            "text",
            "inline_data",
            "file_data",
            "function_call",
            "function_response",
            "executable_code",
            "code_execution_result",
            "video_metadata",
            "thought_signature",
        }

        if any(key in part for key in native_keys):
            return [deepcopy(part)]

        part_type = str(part.get("type", "")).lower()

        if part_type == "text":
            text = part.get("text", "")
            return [{"text": str(text)}] if text is not None else []

        if part_type in {"image", "image_url"}:
            image = part.get("image_url") or part.get("image")
            if isinstance(image, str):
                return [{"file_data": {"file_uri": image}}]
            if isinstance(image, dict):
                uri = image.get("url") or image.get("uri")
                mime_type = image.get("mime_type") or image.get("mimeType")
                if uri:
                    file_data = {"file_uri": uri}
                    if mime_type:
                        file_data["mime_type"] = mime_type
                    return [{"file_data": file_data}]

        if "url" in part and len(part) <= 4:
            file_data = {"file_uri": part["url"]}
            mime_type = part.get("mime_type") or part.get("mimeType")
            if mime_type:
                file_data["mime_type"] = mime_type
            return [{"file_data": file_data}]

        if "data" in part and "mime_type" in part:
            return [
                {
                    "inline_data": {
                        "data": part["data"],
                        "mime_type": part["mime_type"],
                    }
                }
            ]

        # Function/tool representations.
        if part_type in {"function_call", "tool_call"}:
            name = part.get("name")
            args = part.get("args", part.get("arguments", {}))
            return [
                {
                    "function_call": {
                        "name": name,
                        "args": args,
                    }
                }
            ]

        if part_type in {"function_response", "tool_response"}:
            name = part.get("name")
            response = part.get("response", part.get("content", {}))
            return [
                {
                    "function_response": {
                        "name": name,
                        "response": response,
                    }
                }
            ]

        # Last-resort handling preserves custom structured content rather
        # than silently dropping it.
        return [deepcopy(part)]

    @staticmethod
    def _extract_message_text(content: Any) -> str | None:
        if content is None:
            return None

        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            if "text" in content:
                return str(content["text"])
            if "parts" in content:
                return GeminiAdapterPlugin._extract_message_text(content["parts"])
            return None

        if isinstance(content, list):
            values: list[str] = []
            for item in content:
                text = GeminiAdapterPlugin._extract_message_text(item)
                if text:
                    values.append(text)
            return "\n".join(values) if values else None

        return str(content)

    @staticmethod
    def _build_generation_config(
        payload: dict[str, Any],
        *,
        types: Any,
        system_instruction: str | None,
    ) -> Any | None:
        config_values: dict[str, Any] = {}

        mapping = {
            "temperature": "temperature",
            "top_p": "top_p",
            "top_k": "top_k",
            "candidate_count": "candidate_count",
            "max_output_tokens": "max_output_tokens",
            "stop_sequences": "stop_sequences",
            "seed": "seed",
            "presence_penalty": "presence_penalty",
            "frequency_penalty": "frequency_penalty",
            "response_mime_type": "response_mime_type",
            "response_modalities": "response_modalities",
            "response_logprobs": "response_logprobs",
            "logprobs": "logprobs",
            "tools": "tools",
            "tool_config": "tool_config",
            "safety_settings": "safety_settings",
            "thinking_config": "thinking_config",
            "automatic_function_calling": "automatic_function_calling",
            "cached_content": "cached_content",
            "labels": "labels",
            "audio_timestamp": "audio_timestamp",
            "response_schema": "response_schema",
            "response_json_schema": "response_json_schema",
            "service_tier": "service_tier",
        }

        for source_key, config_key in mapping.items():
            value = payload.get(source_key)
            if value is not None:
                config_values[config_key] = deepcopy(value)

        if system_instruction:
            config_values["system_instruction"] = system_instruction

        # The SDK supports dicts and typed GenerateContentConfig instances.
        if not config_values:
            return None

        return types.GenerateContentConfig(**config_values)

    @staticmethod
    def _build_http_options(
        payload: dict[str, Any],
        *,
        types: Any,
    ) -> Any | None:
        options: dict[str, Any] = {}

        api_version = payload.get("api_version") or payload.get("google_api_version")
        if api_version:
            options["api_version"] = str(api_version)

        timeout_ms = payload.get("http_timeout_ms")
        if timeout_ms is not None:
            options["timeout"] = int(timeout_ms)

        extra_headers = payload.get("extra_headers")
        if isinstance(extra_headers, dict):
            options["headers"] = {str(k): str(v) for k, v in extra_headers.items()}

        extra_query = payload.get("extra_query")
        if isinstance(extra_query, dict):
            options["extra_query"] = deepcopy(extra_query)

        extra_body = payload.get("extra_body")
        if isinstance(extra_body, dict):
            options["extra_body"] = deepcopy(extra_body)

        if not options:
            return None

        return types.HttpOptions(**options)

    # ------------------------------------------------------------------
    # Retry / resilience
    # ------------------------------------------------------------------

    async def _call_with_sdk_retry(
        self,
        func,
        *,
        genai_errors: Any,
        max_attempts: int,
        base_delay: float,
        max_delay: float,
    ) -> Any:
        attempts = max(1, int(max_attempts))

        for attempt in range(attempts):
            try:
                return await func()

            except asyncio.CancelledError:
                raise

            except TimeoutError:
                if attempt >= attempts - 1:
                    raise

                await asyncio.sleep(
                    self._jittered_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                    )
                )

            except genai_errors.APIError as exc:
                status_code = self._extract_status_code(exc)

                if status_code not in self.RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                    raise

                retry_after = self._extract_retry_after(exc)

                delay = (
                    retry_after
                    if retry_after is not None
                    else self._jittered_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                    )
                )

                await asyncio.sleep(delay)

    @staticmethod
    def _jittered_delay(
        *,
        attempt: int,
        base_delay: float,
        max_delay: float,
    ) -> float:
        exponential = min(
            max_delay,
            base_delay * (2**attempt),
        )
        return random.uniform(0.5 * exponential, exponential)

    @staticmethod
    def _extract_retry_after(exc: Exception) -> float | None:
        raw_response = getattr(exc, "raw_response", None)

        if raw_response is not None:
            try:
                headers = getattr(raw_response, "headers", None)
                if headers:
                    value = headers.get("Retry-After")
                    if value is not None:
                        return max(0.0, float(value))
            except (TypeError, ValueError, AttributeError):
                pass

        headers = getattr(exc, "headers", None)
        if headers:
            try:
                value = headers.get("Retry-After")
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError, AttributeError):
                pass

        return None

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    def _normalize_response(
        self,
        *,
        response: Any,
        model: str,
        vertexai: bool,
        project: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        if response is None:
            return self._error(
                "Gemini returned no response.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "vertexai": vertexai,
                },
            )

        text = self._extract_response_text(response)
        function_calls = self._extract_function_calls(response)
        usage = self._serialize(self._get_attr(response, "usage_metadata"))
        candidates = self._extract_candidates(response)

        finish_reasons = [
            item.get("finish_reason")
            for item in candidates
            if item.get("finish_reason") is not None
        ]

        if not text and not function_calls:
            safety_blocked = self._looks_safety_blocked(
                response=response,
                candidates=candidates,
            )

            reason = (
                "Gemini response contained no usable text or tool call."
                if not safety_blocked
                else "Gemini response was blocked or contained no usable output."
            )

            return self._error(
                reason,
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "vertexai": vertexai,
                    "usage": usage,
                    "candidates": candidates,
                    "finish_reasons": finish_reasons,
                },
            )

        if function_calls and not text:
            action = "processing"
        else:
            action = DualNormalizationHub.normalize_text(text)

        metadata = {
            "framework": "gemini",
            "model": model,
            "vertexai": vertexai,
            "project": project if vertexai else None,
            "location": location if vertexai else None,
            "usage": usage,
            "finish_reasons": finish_reasons,
            "candidates": candidates,
        }

        model_version = self._get_attr(response, "model_version")
        if model_version:
            metadata["model_version"] = model_version

        response_id = self._get_attr(response, "response_id") or self._get_attr(response, "id")
        if response_id:
            metadata["response_id"] = response_id

        if function_calls:
            metadata["function_calls"] = function_calls

        parsed = self._get_attr(response, "parsed")
        if parsed is not None:
            metadata["parsed"] = self._serialize(parsed)

        return {
            "status": "success",
            "output": text,
            "action": action,
            "metadata": metadata,
        }

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        text = getattr(response, "text", None)

        if isinstance(text, str) and text.strip():
            return text.strip()

        parts = getattr(response, "parts", None)
        if parts:
            chunks: list[str] = []

            for part in parts:
                part_text = getattr(part, "text", None)

                if isinstance(part_text, str) and part_text:
                    chunks.append(part_text)

                elif isinstance(part, dict):
                    candidate = part.get("text")
                    if isinstance(candidate, str) and candidate:
                        chunks.append(candidate)

            if chunks:
                return "\n".join(chunks).strip()

        candidates = getattr(response, "candidates", None)
        if candidates:
            chunks = []

            for candidate in candidates:
                content = (
                    getattr(candidate, "content", None)
                    if not isinstance(candidate, dict)
                    else candidate.get("content")
                )

                parts = (
                    getattr(content, "parts", None)
                    if content is not None and not isinstance(content, dict)
                    else (content or {}).get("parts")
                )

                if not parts:
                    continue

                for part in parts:
                    part_text = (
                        getattr(part, "text", None)
                        if not isinstance(part, dict)
                        else part.get("text")
                    )

                    if isinstance(part_text, str) and part_text:
                        chunks.append(part_text)

            if chunks:
                return "\n".join(chunks).strip()

        return ""

    @staticmethod
    def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
        calls = getattr(response, "function_calls", None)

        if calls is not None:
            serialized = GeminiAdapterPlugin._serialize(calls)
            if isinstance(serialized, list):
                return serialized

        candidates = getattr(response, "candidates", None)
        result: list[dict[str, Any]] = []

        if not candidates:
            return result

        for candidate in candidates:
            content = getattr(candidate, "content", None)

            if content is None and isinstance(candidate, dict):
                content = candidate.get("content")

            parts = getattr(content, "parts", None)

            if parts is None and isinstance(content, dict):
                parts = content.get("parts")

            if not parts:
                continue

            for part in parts:
                function_call = getattr(part, "function_call", None)

                if function_call is None and isinstance(part, dict):
                    function_call = part.get("function_call")

                if function_call is not None:
                    serialized = GeminiAdapterPlugin._serialize(function_call)
                    if isinstance(serialized, dict):
                        result.append(serialized)

        return result

    @staticmethod
    def _extract_candidates(response: Any) -> list[dict[str, Any]]:
        candidates = getattr(response, "candidates", None)

        if not candidates:
            return []

        result: list[dict[str, Any]] = []

        for candidate in candidates:
            if isinstance(candidate, dict):
                finish_reason = candidate.get("finish_reason")
                safety_ratings = candidate.get("safety_ratings")
            else:
                finish_reason = getattr(candidate, "finish_reason", None)
                safety_ratings = getattr(candidate, "safety_ratings", None)

            result.append(
                {
                    "finish_reason": (str(finish_reason) if finish_reason is not None else None),
                    "safety_ratings": GeminiAdapterPlugin._serialize(safety_ratings),
                }
            )

        return result

    @staticmethod
    def _looks_safety_blocked(
        *,
        response: Any,
        candidates: list[dict[str, Any]],
    ) -> bool:
        prompt_feedback = getattr(response, "prompt_feedback", None)

        if prompt_feedback is not None:
            block_reason = getattr(prompt_feedback, "block_reason", None)
            if block_reason is None and isinstance(prompt_feedback, dict):
                block_reason = prompt_feedback.get("block_reason")

            if block_reason not in (None, "", "BLOCK_REASON_UNSPECIFIED"):
                return True

        for candidate in candidates:
            finish_reason = str(candidate.get("finish_reason") or "").upper()
            if "SAFETY" in finish_reason or "BLOCK" in finish_reason:
                return True

        return False

    # ------------------------------------------------------------------
    # Telemetry / errors
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_usage(metadata: dict[str, Any]) -> None:
        usage = metadata.get("usage") or {}

        if not isinstance(usage, dict):
            return

        prompt_tokens = usage.get("prompt_token_count") or usage.get("prompt_tokens") or 0
        completion_tokens = (
            usage.get("candidates_token_count") or usage.get("completion_tokens") or 0
        )
        total_tokens = (
            usage.get("total_token_count")
            or usage.get("total_tokens")
            or (prompt_tokens + completion_tokens)
        )

        if not any((prompt_tokens, completion_tokens, total_tokens)):
            return

        emit(
            "metric_update",
            {
                "adapter": "gemini",
                "tokens": total_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        )

    @staticmethod
    def _error(
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        final_metadata = {
            "framework": "gemini",
        }
        if metadata:
            final_metadata.update(metadata)

        emit(
            CoreEvents.ERROR,
            {
                "adapter": "gemini",
                "message": message,
            },
        )

        return {
            "status": "error",
            "action": "error",
            "message": message,
            "metadata": final_metadata,
        }

    # ------------------------------------------------------------------
    # Serialization / configuration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, dict):
            return {str(key): GeminiAdapterPlugin._serialize(val) for key, val in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [GeminiAdapterPlugin._serialize(item) for item in value]

        for method_name in ("to_json_dict", "model_dump", "dict"):
            method = getattr(value, method_name, None)
            if callable(method):
                try:
                    return GeminiAdapterPlugin._serialize(method())
                except Exception:
                    pass

        try:
            return {
                str(key): GeminiAdapterPlugin._serialize(val)
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
        except Exception:
            return str(value)

    @staticmethod
    def _get_attr(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    @staticmethod
    def _resolve_timeout(payload: dict[str, Any]) -> float:
        value = (
            payload.get("timeout")
            or payload.get("timeout_seconds")
            or config.DEFAULT_ADAPTER_TIMEOUT
        )

        try:
            return max(0.1, float(value))
        except (TypeError, ValueError):
            return 30.0

    def _resolve_max_retries(self, payload: dict[str, Any]) -> int:
        value = payload.get(
            "max_retries",
            getattr(config, "ADAPTER_MAX_RETRIES", self.DEFAULT_MAX_RETRIES),
        )

        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return self.DEFAULT_MAX_RETRIES

    def _resolve_backoff_base(self, payload: dict[str, Any]) -> float:
        value = payload.get(
            "retry_delay",
            getattr(config, "ADAPTER_RETRY_DELAY", self.DEFAULT_BACKOFF_BASE),
        )

        try:
            return max(0.01, float(value))
        except (TypeError, ValueError):
            return self.DEFAULT_BACKOFF_BASE

    @staticmethod
    def _resolve_backoff_max(payload: dict[str, Any]) -> float:
        value = payload.get(
            "max_retry_delay",
            GeminiAdapterPlugin.DEFAULT_BACKOFF_MAX,
        )

        try:
            return max(0.1, float(value))
        except (TypeError, ValueError):
            return GeminiAdapterPlugin.DEFAULT_BACKOFF_MAX

    @staticmethod
    def _extract_status_code(exc: Exception) -> int | None:
        for attr in ("code", "status_code", "status"):
            value = getattr(exc, attr, None)
            if isinstance(value, int):
                return value

            if isinstance(value, str) and value.isdigit():
                return int(value)

        return None

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = getattr(exc, "message", None)

        if not isinstance(message, str) or not message.strip():
            message = str(exc)

        # Avoid leaking credential material if an SDK/provider error
        # happens to echo request metadata.
        redactions = (
            "api_key",
            "access_token",
            "Authorization",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
        )

        for marker in redactions:
            if marker in message:
                return "Gemini request failed; provider returned a credential-sensitive error."

        return f"Gemini SDK Error: {message}"


__all__ = ["GeminiAdapterPlugin"]
