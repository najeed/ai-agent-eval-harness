# eval_runner/adapters/gemini.py
from __future__ import annotations

import asyncio
import os
import random
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from typing import Any

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub


class GeminiAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production Gemini adapter using the official google-genai SDK.

    Primary interface:
      - Gemini Interactions API
      - Gemini Developer API
      - Vertex AI
      - Managed Gemini agents

    Capabilities:
      - single-turn and multi-turn execution
      - server-side conversation state via previous_interaction_id
      - streaming
      - system instructions
      - structured JSON / JSON Schema output
      - function/tool declarations
      - safety settings
      - thinking configuration
      - multimodal input
      - model and managed-agent invocation
      - background interactions
      - usage / response metadata
      - provider error classification
      - bounded retry with jitter
      - explicit request timeout
      - fail-closed empty/invalid response handling

    generateContent is retained only as an explicit legacy compatibility mode.
    New execution defaults to the Interactions API.
    """

    DEFAULT_MODEL = "gemini-3.8-flash"
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BACKOFF_BASE = 1.0
    DEFAULT_BACKOFF_MAX = 30.0

    RETRYABLE_STATUS_CODES = frozenset(
        {
            408,
            409,
            425,
            429,
            500,
            502,
            503,
            504,
        }
    )

    INTERACTION_CONFIG_KEYS = (
        "temperature",
        "top_p",
        "top_k",
        "max_output_tokens",
        "candidate_count",
        "stop_sequences",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "thinking_level",
        "thinking_summaries",
        "response_logprobs",
        "logprobs",
        "include_thoughts",
    )

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="gemini")

    def on_discover_adapters(self, registry: Any) -> None:
        """Register the Gemini adapter."""
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
        Execute one Gemini interaction.

        Normal runtime path:
            Interactions API

        Explicit compatibility path:
            generateContent via api_mode="generate_content"
        """
        try:
            from google import genai
            from google.genai import errors as genai_errors, types
        except ImportError as exc:
            return self._error(
                (
                    "Gemini adapter requires the 'google-genai' package. "
                    "Install the provider-gemini extra."
                ),
                metadata={
                    "framework": "gemini",
                    "dependency_error": str(exc),
                },
            )

        payload = deepcopy(payload or {})
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

        model = self._resolve_model(merged)
        agent = self._resolve_agent(merged)

        if not model and not agent:
            return self._error(
                "Gemini requires either 'model' or 'agent'.",
                metadata={"framework": "gemini"},
            )

        api_mode = self._resolve_api_mode(merged)
        vertexai = self._resolve_vertex_mode(merged, url)

        credentials = merged.get("credentials")

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

        if not vertexai and not api_key:
            return self._error(
                "Gemini API key missing. Set GOOGLE_API_KEY/GEMINI_API_KEY or provide api_key.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "agent": agent,
                },
            )

        client_kwargs: dict[str, Any] = {
            "vertexai": vertexai,
        }

        if api_key:
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

            timeout_seconds = self._resolve_timeout(merged)

            if api_mode == "generate_content":
                result = await self._execute_generate_content(
                    client=client,
                    genai_errors=genai_errors,
                    types=types,
                    payload=merged,
                    model=model,
                    vertexai=vertexai,
                    project=project,
                    location=location,
                    timeout_seconds=timeout_seconds,
                )
            else:
                result = await self._execute_interaction(
                    client=client,
                    genai_errors=genai_errors,
                    types=types,
                    payload=merged,
                    model=model,
                    agent=agent,
                    vertexai=vertexai,
                    project=project,
                    location=location,
                    timeout_seconds=timeout_seconds,
                )

            if result.get("status") == "success":
                self._emit_usage(result.get("metadata") or {})

            return result

        except asyncio.CancelledError:
            raise

        except TimeoutError:
            return self._error(
                f"Gemini request timed out after {self._resolve_timeout(merged):g}s.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "agent": agent,
                    "api_mode": api_mode,
                    "vertexai": vertexai,
                },
            )

        except Exception as exc:
            status_code = self._extract_status_code(exc)

            error_metadata = {
                "framework": "gemini",
                "model": model,
                "agent": agent,
                "api_mode": api_mode,
                "vertexai": vertexai,
                "error_type": type(exc).__name__,
            }

            if status_code is not None:
                error_metadata["status_code"] = status_code

            return self._error(
                self._safe_error_message(exc),
                metadata=error_metadata,
            )

        finally:
            if client is not None:
                try:
                    await client.aio.aclose()
                except Exception as exc:
                    print(f"      [Gemini] Client cleanup warning: {exc}")

    # ------------------------------------------------------------------
    # Interactions API
    # ------------------------------------------------------------------

    async def _execute_interaction(
        self,
        *,
        client: Any,
        genai_errors: Any,
        types: Any,
        payload: dict[str, Any],
        model: str | None,
        agent: str | None,
        vertexai: bool,
        project: str | None,
        location: str | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        interaction_request = self._build_interaction_request(
            payload=payload,
            model=model,
            agent=agent,
        )

        stream = self._resolve_stream(payload)

        if stream:
            response = await self._call_interaction_stream_with_retry(
                client=client,
                genai_errors=genai_errors,
                request=interaction_request,
                timeout_seconds=timeout_seconds,
                payload=payload,
            )

            result = self._normalize_streamed_interaction(
                response=response,
                model=model,
                agent=agent,
                vertexai=vertexai,
                project=project,
                location=location,
            )
        else:
            response = await self._call_interaction_with_retry(
                client=client,
                genai_errors=genai_errors,
                request=interaction_request,
                timeout_seconds=timeout_seconds,
                payload=payload,
            )

            result = self._normalize_interaction(
                response=response,
                model=model,
                agent=agent,
                vertexai=vertexai,
                project=project,
                location=location,
            )

        return result

    async def _call_interaction_with_retry(
        self,
        *,
        client: Any,
        genai_errors: Any,
        request: dict[str, Any],
        timeout_seconds: float,
        payload: dict[str, Any],
    ) -> Any:
        attempts = self._resolve_max_attempts(payload)

        async def _invoke() -> Any:
            async_call = client.aio.interactions.create(**request)

            if timeout_seconds > 0:
                return await asyncio.wait_for(
                    async_call,
                    timeout=timeout_seconds,
                )

            return await async_call

        for attempt in range(attempts):
            try:
                return await _invoke()

            except asyncio.CancelledError:
                raise

            except TimeoutError:
                if attempt >= attempts - 1:
                    raise

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                )

            except genai_errors.APIError as exc:
                status_code = self._extract_status_code(exc)

                if status_code not in self.RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                    raise

                retry_after = self._extract_retry_after(exc)

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                    retry_after=retry_after,
                )

        raise AssertionError("Unreachable Gemini interaction retry state.")

    async def _call_interaction_stream_with_retry(
        self,
        *,
        client: Any,
        genai_errors: Any,
        request: dict[str, Any],
        timeout_seconds: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Consume an Interaction stream and materialize a normalized stream result.

        The SDK's streaming API is intentionally consumed here rather than
        exposing provider-specific event objects to the runtime.
        """
        attempts = self._resolve_max_attempts(payload)

        for attempt in range(attempts):
            try:
                return await self._consume_interaction_stream(
                    client=client,
                    request=request,
                    timeout_seconds=timeout_seconds,
                )

            except asyncio.CancelledError:
                raise

            except TimeoutError:
                if attempt >= attempts - 1:
                    raise

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                )

            except genai_errors.APIError as exc:
                status_code = self._extract_status_code(exc)

                if status_code not in self.RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                    raise

                retry_after = self._extract_retry_after(exc)

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                    retry_after=retry_after,
                )

        raise AssertionError("Unreachable Gemini interaction stream retry state.")

    async def _consume_interaction_stream(
        self,
        *,
        client: Any,
        request: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        async def _consume() -> dict[str, Any]:
            stream = await client.aio.interactions.create(
                **request,
                stream=True,
            )

            text_chunks: list[str] = []
            function_calls: list[dict[str, Any]] = []
            event_summaries: list[dict[str, Any]] = []
            interaction_id: str | None = None
            model_version: str | None = None
            final_interaction: Any = None
            finish_reasons: list[str] = []
            usage: dict[str, Any] | None = None

            async for event in self._as_async_iterator(stream):
                event_type = self._value(event, "event_type") or self._value(
                    event,
                    "type",
                )

                if event_type:
                    event_type = str(event_type)

                interaction = self._value(event, "interaction")

                if interaction is not None:
                    final_interaction = interaction

                    event_id = self._value(interaction, "id")
                    if event_id:
                        interaction_id = str(event_id)

                    interaction_model = self._value(
                        interaction,
                        "model",
                    )
                    if interaction_model:
                        model_version = str(interaction_model)

                    interaction_usage = self._value(
                        interaction,
                        "usage",
                    )
                    if interaction_usage is not None:
                        usage = self._serialize(interaction_usage)

                delta = self._value(event, "delta")

                if delta is not None:
                    delta_type = self._value(delta, "type")

                    if delta_type == "text":
                        text = self._value(delta, "text")
                        if isinstance(text, str) and text:
                            text_chunks.append(text)

                    elif delta_type == "function_call":
                        function_call = self._normalize_function_call(delta)
                        if function_call:
                            function_calls.append(function_call)

                    elif delta_type in {
                        "thought_summary",
                        "thought_signature",
                    }:
                        event_summaries.append(
                            {
                                "event_type": event_type,
                                "delta_type": str(delta_type),
                            }
                        )

                event_summary = self._summarize_stream_event(event)

                if event_summary is not None:
                    event_summaries.append(event_summary)

                status = self._value(event, "status")

                if status:
                    finish_reasons.append(str(status))

            if final_interaction is not None:
                final_functions = self._extract_function_calls_from_interaction(final_interaction)

                if final_functions:
                    function_calls = final_functions

                final_text = self._extract_interaction_text(final_interaction)

                if final_text:
                    text_chunks = [final_text]

                final_usage = self._extract_interaction_usage(final_interaction)

                if final_usage:
                    usage = final_usage

                final_id = self._value(final_interaction, "id")
                if final_id:
                    interaction_id = str(final_id)

            return {
                "text": "".join(text_chunks).strip(),
                "function_calls": function_calls,
                "interaction_id": interaction_id,
                "model_version": model_version,
                "usage": usage or {},
                "finish_reasons": finish_reasons,
                "event_summaries": event_summaries,
            }

        if timeout_seconds > 0:
            return await asyncio.wait_for(
                _consume(),
                timeout=timeout_seconds,
            )

        return await _consume()

    @staticmethod
    async def _as_async_iterator(value: Any) -> AsyncIterator[Any]:
        if hasattr(value, "__aiter__"):
            async for item in value:
                yield item
            return

        if hasattr(value, "__iter__"):
            for item in value:
                yield item
            return

        raise TypeError("Gemini interaction stream did not return an iterable.")

    def _build_interaction_request(
        self,
        *,
        payload: dict[str, Any],
        model: str | None,
        agent: str | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {}

        if agent:
            request["agent"] = agent
        elif model:
            request["model"] = model

        interaction_input = self._build_interaction_input(payload)

        if interaction_input is None:
            raise ValueError("Gemini interaction contains no input.")

        request["input"] = interaction_input

        previous_interaction_id = (
            payload.get("previous_interaction_id")
            or payload.get("interaction_id")
            or payload.get("conversation_id")
        )

        if previous_interaction_id:
            request["previous_interaction_id"] = str(previous_interaction_id)

        system_instruction = payload.get("system_instruction") or payload.get("system_prompt")

        if system_instruction:
            request["system_instruction"] = system_instruction

        tools = payload.get("tools")
        if tools is not None:
            request["tools"] = self._normalize_tools(tools)

        environment = payload.get("environment")
        if environment is not None:
            request["environment"] = deepcopy(environment)

        agent_config = payload.get("agent_config")
        if agent_config is not None:
            request["agent_config"] = deepcopy(agent_config)

        response_format = self._resolve_response_format(payload)

        if response_format is not None:
            request["response_format"] = response_format

            response_mime_type = (
                payload.get("response_mime_type") or payload.get("mime_type") or "application/json"
            )

            request["response_mime_type"] = response_mime_type

        response_modalities = payload.get("response_modalities")
        if response_modalities is not None:
            request["response_modalities"] = deepcopy(response_modalities)

        safety_settings = payload.get("safety_settings")
        if safety_settings is not None:
            request["safety_settings"] = deepcopy(safety_settings)

        generation_config = self._build_generation_config(payload)

        if generation_config:
            request["generation_config"] = generation_config

        store = payload.get("store")
        if store is not None:
            request["store"] = bool(store)

        background = payload.get("background")
        if background is not None:
            request["background"] = bool(background)

        service_tier = payload.get("service_tier")
        if service_tier is not None:
            request["service_tier"] = service_tier

        labels = payload.get("labels")
        if labels is not None:
            request["labels"] = deepcopy(labels)

        webhook_config = payload.get("webhook_config")
        if webhook_config is not None:
            request["webhook_config"] = deepcopy(webhook_config)

        extra_headers = payload.get("extra_headers")
        if isinstance(extra_headers, Mapping):
            request["extra_headers"] = {
                str(key): str(value) for key, value in extra_headers.items()
            }

        extra_query = payload.get("extra_query")
        if isinstance(extra_query, Mapping):
            request["extra_query"] = deepcopy(extra_query)

        extra_body = payload.get("extra_body")
        if isinstance(extra_body, Mapping):
            request["extra_body"] = deepcopy(extra_body)

        api_version = payload.get("api_version") or payload.get("google_api_version")

        if api_version:
            request["api_version"] = str(api_version)

        if payload.get("timeout") is not None:
            request["timeout"] = self._resolve_timeout(payload)

        return request

    @staticmethod
    def _build_interaction_input(
        payload: dict[str, Any],
    ) -> Any:
        explicit_input = payload.get("input")

        if explicit_input is not None:
            return deepcopy(explicit_input)

        explicit_contents = payload.get("contents")

        if explicit_contents is not None:
            return deepcopy(explicit_contents)

        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise TypeError("Gemini 'messages' must be a list.")

            # A supplied previous_interaction_id means the server already
            # owns conversation state. Send only the newest user turn.
            if (
                payload.get("previous_interaction_id")
                or payload.get("interaction_id")
                or payload.get("conversation_id")
            ):
                latest = GeminiAdapterPlugin._latest_user_input(messages)

                if latest is not None:
                    return latest

            return GeminiAdapterPlugin._messages_to_interaction_input(messages)

        task = payload.get("task_description") or payload.get("task") or payload.get("prompt")

        if task is None:
            return None

        return GeminiAdapterPlugin._coerce_interaction_input(task)

    @staticmethod
    def _latest_user_input(messages: list[Any]) -> Any:
        for message in reversed(messages):
            if isinstance(message, str):
                return message

            if not isinstance(message, Mapping):
                continue

            role = str(message.get("role", "user")).strip().lower()

            if role not in {"user", "human"}:
                continue

            if "content" in message:
                return GeminiAdapterPlugin._coerce_interaction_input(message["content"])

            if "parts" in message:
                return deepcopy(message["parts"])

        if messages:
            latest = messages[-1]

            if isinstance(latest, Mapping):
                return GeminiAdapterPlugin._coerce_interaction_input(latest.get("content", latest))

            return GeminiAdapterPlugin._coerce_interaction_input(latest)

        return None

    @staticmethod
    def _messages_to_interaction_input(
        messages: list[Any],
    ) -> Any:
        """
        Convert provider-neutral messages into stateless Interactions input.

        Interactions is conversation-state oriented. When no previous interaction
        ID is supplied, role semantics are retained in textual boundaries so the
        complete evaluation history can still be represented deterministically.
        Native interaction input objects are preserved.
        """
        normalized: list[dict[str, Any]] = []

        for message in messages:
            if isinstance(message, str):
                normalized.append(
                    {
                        "type": "text",
                        "text": message,
                    }
                )
                continue

            if not isinstance(message, Mapping):
                normalized.append(
                    {
                        "type": "text",
                        "text": str(message),
                    }
                )
                continue

            if "type" in message and ("text" in message or "data" in message or "uri" in message):
                normalized.append(deepcopy(dict(message)))
                continue

            role = str(message.get("role", "user")).strip().lower()

            content = message.get(
                "content",
                message.get("parts"),
            )

            parts = GeminiAdapterPlugin._content_to_text_parts(content)

            if not parts:
                continue

            role_label = {
                "system": "SYSTEM",
                "assistant": "ASSISTANT",
                "ai": "ASSISTANT",
                "model": "ASSISTANT",
                "tool": "TOOL",
                "function": "TOOL",
                "user": "USER",
                "human": "USER",
            }.get(role, role.upper())

            for part in parts:
                text = part.get("text")

                if isinstance(text, str):
                    normalized.append(
                        {
                            "type": "text",
                            "text": f"[{role_label}]\n{text}",
                        }
                    )
                else:
                    normalized.append(part)

        return normalized

    @staticmethod
    def _content_to_text_parts(
        content: Any,
    ) -> list[dict[str, Any]]:
        if content is None:
            return []

        if isinstance(content, str):
            return [{"type": "text", "text": content}]

        if isinstance(content, Mapping):
            normalized = GeminiAdapterPlugin._normalize_interaction_part(content)
            return [normalized] if normalized else []

        if isinstance(content, list):
            parts: list[dict[str, Any]] = []

            for item in content:
                if isinstance(item, str):
                    parts.append(
                        {
                            "type": "text",
                            "text": item,
                        }
                    )
                elif isinstance(item, Mapping):
                    normalized = GeminiAdapterPlugin._normalize_interaction_part(item)
                    if normalized:
                        parts.append(normalized)
                else:
                    parts.append(
                        {
                            "type": "text",
                            "text": str(item),
                        }
                    )

            return parts

        return [
            {
                "type": "text",
                "text": str(content),
            }
        ]

    @staticmethod
    def _normalize_interaction_part(
        part: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not part:
            return None

        if "type" in part:
            return deepcopy(dict(part))

        if "text" in part:
            return {
                "type": "text",
                "text": str(part["text"]),
            }

        if "inline_data" in part:
            inline = part["inline_data"]

            if isinstance(inline, Mapping):
                result = {
                    "type": "image",
                    "data": inline.get("data"),
                }

                mime_type = inline.get("mime_type") or inline.get("mimeType")

                if mime_type:
                    result["mime_type"] = mime_type

                return result

        if "file_data" in part:
            file_data = part["file_data"]

            if isinstance(file_data, Mapping):
                result = {
                    "type": "file",
                    "uri": (file_data.get("file_uri") or file_data.get("uri")),
                }

                mime_type = file_data.get("mime_type") or file_data.get("mimeType")

                if mime_type:
                    result["mime_type"] = mime_type

                return result

        if "function_response" in part:
            value = part["function_response"]

            if isinstance(value, Mapping):
                return {
                    "type": "function_result",
                    "name": value.get("name"),
                    "call_id": value.get("call_id"),
                    "result": deepcopy(value.get("response", {})),
                }

        if "function_call" in part:
            value = part["function_call"]

            if isinstance(value, Mapping):
                return {
                    "type": "function_call",
                    "name": value.get("name"),
                    "arguments": deepcopy(value.get("args", {})),
                    "id": value.get("id"),
                }

        if "url" in part:
            result = {
                "type": "image",
                "uri": part["url"],
            }

            mime_type = part.get("mime_type") or part.get("mimeType")

            if mime_type:
                result["mime_type"] = mime_type

            return result

        return {
            "type": "text",
            "text": str(dict(part)),
        }

    @staticmethod
    def _coerce_interaction_input(
        value: Any,
    ) -> Any:
        if isinstance(value, str):
            return value

        if isinstance(value, Mapping):
            if "type" in value:
                return deepcopy(dict(value))

            return GeminiAdapterPlugin._normalize_interaction_part(value)

        if isinstance(value, list):
            if all(isinstance(item, Mapping) and "type" in item for item in value):
                return deepcopy(value)

            return GeminiAdapterPlugin._content_to_text_parts(value)

        return str(value)

    # ------------------------------------------------------------------
    # Legacy generateContent compatibility
    # ------------------------------------------------------------------

    async def _execute_generate_content(
        self,
        *,
        client: Any,
        genai_errors: Any,
        types: Any,
        payload: dict[str, Any],
        model: str | None,
        vertexai: bool,
        project: str | None,
        location: str | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not model:
            return self._error(
                "generateContent compatibility mode requires a model.",
                metadata={"framework": "gemini"},
            )

        contents, system_instruction = self._build_generate_content_contents(payload)

        generation_config = self._build_generate_content_config(
            payload=payload,
            types=types,
            system_instruction=system_instruction,
        )

        stream = self._resolve_stream(payload)

        request: dict[str, Any] = {
            "model": model,
            "contents": contents,
        }

        if generation_config is not None:
            request["config"] = generation_config

        if stream:
            response = await self._call_generate_content_stream_with_retry(
                client=client,
                genai_errors=genai_errors,
                request=request,
                timeout_seconds=timeout_seconds,
                payload=payload,
            )
        else:
            response = await self._call_generate_content_with_retry(
                client=client,
                genai_errors=genai_errors,
                request=request,
                timeout_seconds=timeout_seconds,
                payload=payload,
            )

        return self._normalize_generate_content_response(
            response=response,
            model=model,
            vertexai=vertexai,
            project=project,
            location=location,
        )

    async def _call_generate_content_with_retry(
        self,
        *,
        client: Any,
        genai_errors: Any,
        request: dict[str, Any],
        timeout_seconds: float,
        payload: dict[str, Any],
    ) -> Any:
        attempts = self._resolve_max_attempts(payload)

        async def _invoke() -> Any:
            async_call = client.aio.models.generate_content(**request)

            if timeout_seconds > 0:
                return await asyncio.wait_for(
                    async_call,
                    timeout=timeout_seconds,
                )

            return await async_call

        for attempt in range(attempts):
            try:
                return await _invoke()

            except asyncio.CancelledError:
                raise

            except TimeoutError:
                if attempt >= attempts - 1:
                    raise

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                )

            except genai_errors.APIError as exc:
                status_code = self._extract_status_code(exc)

                if status_code not in self.RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                    raise

                retry_after = self._extract_retry_after(exc)

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                    retry_after=retry_after,
                )

        raise AssertionError("Unreachable Gemini generateContent retry state.")

    async def _call_generate_content_stream_with_retry(
        self,
        *,
        client: Any,
        genai_errors: Any,
        request: dict[str, Any],
        timeout_seconds: float,
        payload: dict[str, Any],
    ) -> list[Any]:
        attempts = self._resolve_max_attempts(payload)

        async def _consume() -> list[Any]:
            stream = await client.aio.models.generate_content_stream(**request)

            chunks: list[Any] = []

            async for chunk in self._as_async_iterator(stream):
                chunks.append(chunk)

            return chunks

        for attempt in range(attempts):
            try:
                if timeout_seconds > 0:
                    return await asyncio.wait_for(
                        _consume(),
                        timeout=timeout_seconds,
                    )

                return await _consume()

            except asyncio.CancelledError:
                raise

            except TimeoutError:
                if attempt >= attempts - 1:
                    raise

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                )

            except genai_errors.APIError as exc:
                status_code = self._extract_status_code(exc)

                if status_code not in self.RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                    raise

                retry_after = self._extract_retry_after(exc)

                await self._retry_sleep(
                    attempt=attempt,
                    payload=payload,
                    retry_after=retry_after,
                )

        raise AssertionError("Unreachable Gemini generateContent streaming state.")

    @staticmethod
    def _build_generate_content_contents(
        payload: dict[str, Any],
    ) -> tuple[Any, str | None]:
        system_instruction = payload.get("system_instruction") or payload.get("system_prompt")

        messages = payload.get("messages")

        if messages is not None:
            if not isinstance(messages, list):
                raise TypeError("Gemini 'messages' must be a list.")

            contents: list[dict[str, Any]] = []

            for message in messages:
                if isinstance(message, str):
                    contents.append(
                        {
                            "role": "user",
                            "parts": [{"text": message}],
                        }
                    )
                    continue

                if not isinstance(message, Mapping):
                    raise TypeError("Each Gemini message must be a string or object.")

                role = str(message.get("role", "user")).strip().lower()

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
                    "tool": "tool",
                    "function": "tool",
                }.get(role, "user")

                parts = GeminiAdapterPlugin._normalize_generate_content_parts(
                    message.get("content"),
                    message=message,
                )

                if parts:
                    contents.append(
                        {
                            "role": gemini_role,
                            "parts": parts,
                        }
                    )

            return contents, system_instruction

        task = (
            payload.get("task_description")
            or payload.get("task")
            or payload.get("prompt")
            or payload.get("input")
        )

        if task is None:
            return [], system_instruction

        if isinstance(task, list):
            return deepcopy(task), system_instruction

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
    def _normalize_generate_content_parts(
        content: Any,
        *,
        message: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if content is None:
            for key in (
                "parts",
                "tool_response",
                "function_response",
                "function_call",
            ):
                if key in message:
                    return GeminiAdapterPlugin._normalize_generate_content_parts(
                        message[key],
                        message={},
                    )

            return []

        if isinstance(content, str):
            return [{"text": content}]

        if isinstance(content, Mapping):
            return GeminiAdapterPlugin._normalize_generate_content_part(content)

        if isinstance(content, list):
            result: list[dict[str, Any]] = []

            for item in content:
                if isinstance(item, str):
                    result.append({"text": item})
                elif isinstance(item, Mapping):
                    result.extend(GeminiAdapterPlugin._normalize_generate_content_part(item))
                else:
                    result.append({"text": str(item)})

            return result

        return [{"text": str(content)}]

    @staticmethod
    def _normalize_generate_content_part(
        part: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if not part:
            return []

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
            return [deepcopy(dict(part))]

        part_type = str(part.get("type", "")).lower()

        if part_type == "text":
            return [{"text": str(part.get("text", ""))}]

        if part_type in {"image", "image_url"}:
            image = part.get("image_url") or part.get("image")

            if isinstance(image, str):
                return [
                    {
                        "file_data": {
                            "file_uri": image,
                        }
                    }
                ]

            if isinstance(image, Mapping):
                uri = image.get("url") or image.get("uri")

                if uri:
                    file_data = {
                        "file_uri": uri,
                    }

                    mime_type = image.get("mime_type") or image.get("mimeType")

                    if mime_type:
                        file_data["mime_type"] = mime_type

                    return [{"file_data": file_data}]

        if "url" in part:
            file_data = {
                "file_uri": part["url"],
            }

            mime_type = part.get("mime_type") or part.get("mimeType")

            if mime_type:
                file_data["mime_type"] = mime_type

            return [{"file_data": file_data}]

        if "data" in part:
            mime_type = part.get("mime_type") or part.get("mimeType")

            if mime_type:
                return [
                    {
                        "inline_data": {
                            "data": part["data"],
                            "mime_type": mime_type,
                        }
                    }
                ]

        if part_type in {"function_call", "tool_call"}:
            return [
                {
                    "function_call": {
                        "name": part.get("name"),
                        "args": deepcopy(
                            part.get(
                                "args",
                                part.get(
                                    "arguments",
                                    {},
                                ),
                            )
                        ),
                    }
                }
            ]

        if part_type in {"function_response", "tool_response"}:
            return [
                {
                    "function_response": {
                        "name": part.get("name"),
                        "response": deepcopy(
                            part.get(
                                "response",
                                part.get(
                                    "content",
                                    {},
                                ),
                            )
                        ),
                    }
                }
            ]

        return [deepcopy(dict(part))]

    # ------------------------------------------------------------------
    # Interactions response normalization
    # ------------------------------------------------------------------

    def _normalize_interaction(
        self,
        *,
        response: Any,
        model: str | None,
        agent: str | None,
        vertexai: bool,
        project: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        if response is None:
            return self._error(
                "Gemini returned no interaction response.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "agent": agent,
                    "vertexai": vertexai,
                },
            )

        text = self._extract_interaction_text(response)
        function_calls = self._extract_function_calls_from_interaction(response)

        usage = self._extract_interaction_usage(response)
        interaction_id = self._value(response, "id")
        status = self._value(response, "status")
        model_version = self._value(response, "model_version")

        steps = self._serialize(self._value(response, "steps"))

        if not text and not function_calls:
            return self._error(
                "Gemini interaction contained no usable text or tool call.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "agent": agent,
                    "vertexai": vertexai,
                    "usage": usage,
                    "interaction_id": interaction_id,
                    "status": status,
                    "steps": steps,
                },
            )

        if function_calls and not text:
            if len(function_calls) == 1:
                action = "call_tool"
            else:
                action = "call_multiple_tools"
        else:
            action = DualNormalizationHub.normalize_text(text)

        metadata = {
            "framework": "gemini",
            "model": model,
            "agent": agent,
            "vertexai": vertexai,
            "project": project if vertexai else None,
            "location": location if vertexai else None,
            "usage": usage,
            "interaction_id": interaction_id,
            "status": status,
            "steps": steps,
        }

        if model_version:
            metadata["model_version"] = model_version

        if function_calls:
            metadata["function_calls"] = function_calls

        parsed = self._value(response, "parsed")

        if parsed is not None:
            metadata["parsed"] = self._serialize(parsed)

        return {
            "status": "success",
            "output": text,
            "action": action,
            "metadata": metadata,
        }

    @staticmethod
    def _normalize_streamed_interaction(
        *,
        response: dict[str, Any],
        model: str | None,
        agent: str | None,
        vertexai: bool,
        project: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        text = str(response.get("text") or "").strip()

        function_calls = response.get("function_calls") or []

        if not text and not function_calls:
            return GeminiAdapterPlugin._error(
                "Gemini interaction stream contained no usable output.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "agent": agent,
                    "vertexai": vertexai,
                    "usage": response.get("usage") or {},
                    "interaction_id": response.get("interaction_id"),
                    "finish_reasons": response.get("finish_reasons") or [],
                    "stream_events": response.get("event_summaries") or [],
                },
            )

        if function_calls and not text:
            if len(function_calls) == 1:
                action = "call_tool"
            else:
                action = "call_multiple_tools"
        else:
            action = DualNormalizationHub.normalize_text(text)

        metadata = {
            "framework": "gemini",
            "model": model,
            "agent": agent,
            "vertexai": vertexai,
            "project": project if vertexai else None,
            "location": location if vertexai else None,
            "usage": response.get("usage") or {},
            "interaction_id": response.get("interaction_id"),
            "finish_reasons": response.get("finish_reasons") or [],
            "stream_events": response.get("event_summaries") or [],
        }

        if response.get("model_version"):
            metadata["model_version"] = response["model_version"]

        if function_calls:
            metadata["function_calls"] = function_calls

        return {
            "status": "success",
            "output": text,
            "action": action,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # generateContent response normalization
    # ------------------------------------------------------------------

    def _normalize_generate_content_response(
        self,
        *,
        response: Any,
        model: str,
        vertexai: bool,
        project: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        if isinstance(response, list):
            return self._normalize_generate_content_chunks(
                response=response,
                model=model,
                vertexai=vertexai,
                project=project,
                location=location,
            )

        text = self._extract_generate_content_text(response)

        function_calls = self._extract_generate_content_function_calls(response)

        usage = self._serialize(self._value(response, "usage_metadata"))

        candidates = self._extract_generate_content_candidates(response)

        finish_reasons = [
            candidate.get("finish_reason")
            for candidate in candidates
            if candidate.get("finish_reason") is not None
        ]

        if not text and not function_calls:
            return self._error(
                "Gemini generateContent response contained no usable output.",
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
            action = "call_tool" if len(function_calls) == 1 else "call_multiple_tools"
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
            "api_mode": "generate_content",
            "legacy_api": True,
        }

        model_version = self._value(response, "model_version")
        if model_version:
            metadata["model_version"] = model_version

        response_id = self._value(response, "response_id") or self._value(response, "id")

        if response_id:
            metadata["response_id"] = response_id

        if function_calls:
            metadata["function_calls"] = function_calls

        parsed = self._value(response, "parsed")
        if parsed is not None:
            metadata["parsed"] = self._serialize(parsed)

        return {
            "status": "success",
            "output": text,
            "action": action,
            "metadata": metadata,
        }

    def _normalize_generate_content_chunks(
        self,
        *,
        response: list[Any],
        model: str,
        vertexai: bool,
        project: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        text_chunks: list[str] = []
        function_calls: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        candidates: list[dict[str, Any]] = []

        for chunk in response:
            text = self._extract_generate_content_text(chunk)

            if text:
                text_chunks.append(text)

            function_calls.extend(self._extract_generate_content_function_calls(chunk))

            chunk_usage = self._serialize(self._value(chunk, "usage_metadata"))

            if isinstance(chunk_usage, dict):
                usage.update(chunk_usage)

            candidates.extend(self._extract_generate_content_candidates(chunk))

        text = "".join(text_chunks).strip()

        if not text and not function_calls:
            return self._error(
                "Gemini generateContent stream contained no usable output.",
                metadata={
                    "framework": "gemini",
                    "model": model,
                    "vertexai": vertexai,
                    "usage": usage,
                    "candidates": candidates,
                },
            )

        if function_calls and not text:
            action = "call_tool" if len(function_calls) == 1 else "call_multiple_tools"
        else:
            action = DualNormalizationHub.normalize_text(text)

        return {
            "status": "success",
            "output": text,
            "action": action,
            "metadata": {
                "framework": "gemini",
                "model": model,
                "vertexai": vertexai,
                "project": project if vertexai else None,
                "location": location if vertexai else None,
                "usage": usage,
                "candidates": candidates,
                "api_mode": "generate_content",
                "legacy_api": True,
                "function_calls": function_calls,
            },
        }

    # ------------------------------------------------------------------
    # Request configuration
    # ------------------------------------------------------------------

    @classmethod
    def _build_generation_config(
        cls,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        config_values: dict[str, Any] = {}

        explicit = payload.get("generation_config")

        if isinstance(explicit, Mapping):
            config_values.update(deepcopy(dict(explicit)))

        for key in cls.INTERACTION_CONFIG_KEYS:
            value = payload.get(key)

            if value is not None:
                config_values[key] = deepcopy(value)

        if payload.get("thinking_config") is not None:
            thinking_config = payload.get("thinking_config")

            if isinstance(thinking_config, Mapping):
                for key, value in thinking_config.items():
                    config_values[str(key)] = deepcopy(value)

        return config_values

    @staticmethod
    def _build_generate_content_config(
        *,
        payload: dict[str, Any],
        types: Any,
        system_instruction: str | None,
    ) -> Any | None:
        config_values: dict[str, Any] = {}

        explicit = payload.get("generation_config")

        if isinstance(explicit, Mapping):
            config_values.update(deepcopy(dict(explicit)))

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
            "service_tier": "service_tier",
        }

        for source_key, config_key in mapping.items():
            value = payload.get(source_key)

            if value is not None:
                config_values[config_key] = deepcopy(value)

        if system_instruction:
            config_values["system_instruction"] = system_instruction

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

        http_timeout_ms = payload.get("http_timeout_ms")

        if http_timeout_ms is not None:
            options["timeout"] = int(http_timeout_ms)

        extra_headers = payload.get("extra_headers")

        if isinstance(extra_headers, Mapping):
            options["headers"] = {str(key): str(value) for key, value in extra_headers.items()}

        extra_query = payload.get("extra_query")

        if isinstance(extra_query, Mapping):
            options["extra_query"] = deepcopy(dict(extra_query))

        extra_body = payload.get("extra_body")

        if isinstance(extra_body, Mapping):
            options["extra_body"] = deepcopy(dict(extra_body))

        if not options:
            return None

        return types.HttpOptions(**options)

    @staticmethod
    def _normalize_tools(
        tools: Any,
    ) -> Any:
        if tools is None:
            return None

        if isinstance(tools, list):
            return deepcopy(tools)

        return deepcopy(tools)

    @staticmethod
    def _resolve_response_format(
        payload: dict[str, Any],
    ) -> Any | None:
        explicit = payload.get("response_format")

        if explicit is not None:
            return deepcopy(explicit)

        schema = payload.get("response_json_schema") or payload.get("response_schema")

        if schema is not None:
            return deepcopy(schema)

        return None

    # ------------------------------------------------------------------
    # Configuration resolution
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_api_mode(
        cls,
        payload: dict[str, Any],
    ) -> str:
        explicit = payload.get("api_mode") or payload.get("api") or payload.get("gemini_api")

        if explicit is None:
            return "interactions"

        value = str(explicit).strip().lower()

        aliases = {
            "interaction": "interactions",
            "interactions": "interactions",
            "legacy": "generate_content",
            "generate": "generate_content",
            "generate_content": "generate_content",
            "generatecontent": "generate_content",
        }

        try:
            return aliases[value]
        except KeyError as exc:
            raise ValueError(f"Unsupported Gemini API mode: {explicit!r}") from exc

    @classmethod
    def _resolve_model(
        cls,
        payload: dict[str, Any],
    ) -> str | None:
        value = (
            payload.get("model")
            or config.GEMINI_MODEL
            or os.getenv("GEMINI_MODEL")
            or cls.DEFAULT_MODEL
        )

        value = str(value).strip()

        return value or None

    @staticmethod
    def _resolve_agent(
        payload: dict[str, Any],
    ) -> str | None:
        value = payload.get("agent") or payload.get("agent_id") or payload.get("managed_agent")

        if value is None:
            return None

        value = str(value).strip()

        return value or None

    @staticmethod
    def _resolve_vertex_mode(
        payload: dict[str, Any],
        url: str | None,
    ) -> bool:
        explicit = payload.get("vertexai")

        if explicit is not None:
            return bool(explicit)

        explicit = payload.get("vertex_ai")

        if explicit is not None:
            return bool(explicit)

        deployment = str(payload.get("deployment", "")).lower()

        if deployment in {
            "vertex",
            "vertexai",
            "vertex_ai",
            "google_cloud",
            "google-cloud",
            "gemini_enterprise",
        }:
            return True

        metadata = payload.get("metadata")

        if isinstance(metadata, Mapping):
            value = metadata.get("vertexai")

            if value is not None:
                return bool(value)

            value = metadata.get("vertex_ai")

            if value is not None:
                return bool(value)

        return "vertex" in str(url or "").lower()

    @staticmethod
    def _resolve_stream(
        payload: dict[str, Any],
    ) -> bool:
        value = payload.get("stream")

        if value is None:
            return False

        return bool(value)

    @staticmethod
    def _resolve_timeout(
        payload: dict[str, Any],
    ) -> float:
        value = (
            payload.get("timeout")
            or payload.get("timeout_seconds")
            or config.DEFAULT_ADAPTER_TIMEOUT
        )

        try:
            return max(
                0.1,
                float(value),
            )
        except (
            TypeError,
            ValueError,
        ):
            return 30.0

    def _resolve_max_attempts(
        self,
        payload: dict[str, Any],
    ) -> int:
        value = payload.get("max_attempts")

        if value is None:
            max_retries = payload.get("max_retries")

            if max_retries is None:
                max_retries = getattr(
                    config,
                    "ADAPTER_MAX_RETRIES",
                    self.DEFAULT_MAX_RETRIES,
                )

            try:
                return max(
                    1,
                    int(max_retries) + 1,
                )
            except (
                TypeError,
                ValueError,
            ):
                return self.DEFAULT_MAX_RETRIES + 1

        try:
            return max(
                1,
                int(value),
            )
        except (
            TypeError,
            ValueError,
        ):
            return self.DEFAULT_MAX_RETRIES + 1

    def _resolve_backoff_base(
        self,
        payload: dict[str, Any],
    ) -> float:
        value = payload.get("retry_delay")

        if value is None:
            value = getattr(
                config,
                "ADAPTER_RETRY_DELAY",
                self.DEFAULT_BACKOFF_BASE,
            )

        try:
            return max(
                0.01,
                float(value),
            )
        except (
            TypeError,
            ValueError,
        ):
            return self.DEFAULT_BACKOFF_BASE

    @classmethod
    def _resolve_backoff_max(
        cls,
        payload: dict[str, Any],
    ) -> float:
        value = payload.get("max_retry_delay")

        if value is None:
            value = getattr(
                config,
                "ADAPTER_MAX_RETRY_DELAY",
                cls.DEFAULT_BACKOFF_MAX,
            )

        try:
            return max(
                0.1,
                float(value),
            )
        except (
            TypeError,
            ValueError,
        ):
            return cls.DEFAULT_BACKOFF_MAX

    async def _retry_sleep(
        self,
        *,
        attempt: int,
        payload: dict[str, Any],
        retry_after: float | None = None,
    ) -> None:
        delay = retry_after

        if delay is None:
            base_delay = self._resolve_backoff_base(payload)

            max_delay = self._resolve_backoff_max(payload)

            exponential = min(
                max_delay,
                base_delay * (2**attempt),
            )

            delay = random.uniform(
                0.5 * exponential,
                exponential,
            )

        if delay > 0:
            await asyncio.sleep(
                min(
                    delay,
                    self._resolve_backoff_max(payload),
                )
            )

    # ------------------------------------------------------------------
    # Interaction response extraction
    # ------------------------------------------------------------------

    @classmethod
    def _extract_interaction_text(
        cls,
        response: Any,
    ) -> str:
        output_text = cls._value(
            response,
            "output_text",
        )

        if (
            isinstance(
                output_text,
                str,
            )
            and output_text.strip()
        ):
            return output_text.strip()

        steps = cls._value(
            response,
            "steps",
        )

        if steps:
            chunks: list[str] = []

            for step in steps:
                if (
                    cls._value(
                        step,
                        "type",
                    )
                    != "model_output"
                ):
                    continue

                content = cls._value(
                    step,
                    "content",
                )

                chunks.extend(cls._extract_step_text(content))

            if chunks:
                return "\n".join(chunks).strip()

        outputs = cls._value(
            response,
            "outputs",
        )

        if outputs:
            chunks = cls._extract_step_text(outputs)

            if chunks:
                return "\n".join(chunks).strip()

        return ""

    @classmethod
    def _extract_function_calls_from_interaction(
        cls,
        response: Any,
    ) -> list[dict[str, Any]]:
        steps = cls._value(
            response,
            "steps",
        )

        result: list[dict[str, Any]] = []

        if steps:
            for step in steps:
                step_type = cls._value(
                    step,
                    "type",
                )

                if step_type != "function_call":
                    continue

                normalized = cls._normalize_function_call(step)

                if normalized:
                    result.append(normalized)

        outputs = cls._value(
            response,
            "outputs",
        )

        if outputs:
            for output in outputs:
                output_type = cls._value(
                    output,
                    "type",
                )

                if output_type != "function_call":
                    continue

                normalized = cls._normalize_function_call(output)

                if normalized:
                    result.append(normalized)

        return result

    @classmethod
    def _extract_step_text(
        cls,
        value: Any,
    ) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            return [value]

        if isinstance(value, Mapping):
            value_type = value.get("type")

            if value_type in {
                "text",
                "output_text",
                "model_output",
            }:
                text = value.get("text")

                if isinstance(
                    text,
                    str,
                ):
                    return [text]

            if "content" in value:
                return cls._extract_step_text(value["content"])

            if "parts" in value:
                return cls._extract_step_text(value["parts"])

            return []

        if isinstance(value, list):
            result: list[str] = []

            for item in value:
                result.extend(cls._extract_step_text(item))

            return result

        text = cls._value(
            value,
            "text",
        )

        if isinstance(
            text,
            str,
        ):
            return [text]

        return []

    @classmethod
    def _extract_interaction_usage(
        cls,
        response: Any,
    ) -> dict[str, Any]:
        for field in (
            "usage",
            "usage_metadata",
        ):
            usage = cls._serialize(
                cls._value(
                    response,
                    field,
                )
            )

            if isinstance(
                usage,
                dict,
            ):
                return usage

        metadata = cls._value(
            response,
            "response_metadata",
        )

        if isinstance(
            metadata,
            Mapping,
        ):
            usage = metadata.get("usage")

            if isinstance(
                usage,
                Mapping,
            ):
                return cls._serialize(usage)

        return {}

    @staticmethod
    def _normalize_function_call(
        value: Any,
    ) -> dict[str, Any] | None:
        name = GeminiAdapterPlugin._value(
            value,
            "name",
        )

        arguments = (
            GeminiAdapterPlugin._value(
                value,
                "arguments",
            )
            or GeminiAdapterPlugin._value(
                value,
                "args",
            )
            or GeminiAdapterPlugin._value(
                value,
                "parameters",
            )
            or {}
        )

        call_id = GeminiAdapterPlugin._value(
            value,
            "id",
        ) or GeminiAdapterPlugin._value(
            value,
            "call_id",
        )

        if not name:
            return None

        return {
            "id": call_id,
            "name": str(name),
            "arguments": GeminiAdapterPlugin._serialize(arguments),
        }

    # ------------------------------------------------------------------
    # generateContent response extraction
    # ------------------------------------------------------------------

    @classmethod
    def _extract_generate_content_text(
        cls,
        response: Any,
    ) -> str:
        text = cls._value(
            response,
            "text",
        )

        if (
            isinstance(
                text,
                str,
            )
            and text.strip()
        ):
            return text.strip()

        parts = cls._value(
            response,
            "parts",
        )

        if parts:
            chunks: list[str] = []

            for part in parts:
                part_text = cls._value(
                    part,
                    "text",
                )

                if isinstance(
                    part_text,
                    str,
                ):
                    chunks.append(part_text)

            if chunks:
                return "\n".join(chunks).strip()

        candidates = cls._value(
            response,
            "candidates",
        )

        if not candidates:
            return ""

        chunks = []

        for candidate in candidates:
            content = cls._value(
                candidate,
                "content",
            )

            parts = cls._value(
                content,
                "parts",
            )

            if not parts:
                continue

            for part in parts:
                part_text = cls._value(
                    part,
                    "text",
                )

                if isinstance(
                    part_text,
                    str,
                ):
                    chunks.append(part_text)

        return "\n".join(chunks).strip()

    @classmethod
    def _extract_generate_content_function_calls(
        cls,
        response: Any,
    ) -> list[dict[str, Any]]:
        calls = cls._value(
            response,
            "function_calls",
        )

        if calls is not None:
            serialized = cls._serialize(calls)

            if isinstance(
                serialized,
                list,
            ):
                result = []

                for call in serialized:
                    normalized = cls._normalize_function_call(call)

                    if normalized:
                        result.append(normalized)

                if result:
                    return result

        candidates = cls._value(
            response,
            "candidates",
        )

        result: list[dict[str, Any]] = []

        if not candidates:
            return result

        for candidate in candidates:
            content = cls._value(
                candidate,
                "content",
            )

            parts = cls._value(
                content,
                "parts",
            )

            if not parts:
                continue

            for part in parts:
                function_call = cls._value(
                    part,
                    "function_call",
                )

                if function_call is None:
                    continue

                normalized = cls._normalize_function_call(function_call)

                if normalized:
                    result.append(normalized)

        return result

    @classmethod
    def _extract_generate_content_candidates(
        cls,
        response: Any,
    ) -> list[dict[str, Any]]:
        candidates = cls._value(
            response,
            "candidates",
        )

        if not candidates:
            return []

        result: list[dict[str, Any]] = []

        for candidate in candidates:
            finish_reason = cls._value(
                candidate,
                "finish_reason",
            )

            safety_ratings = cls._serialize(
                cls._value(
                    candidate,
                    "safety_ratings",
                )
            )

            result.append(
                {
                    "finish_reason": (str(finish_reason) if finish_reason is not None else None),
                    "safety_ratings": safety_ratings,
                }
            )

        return result

    @staticmethod
    def _extract_message_text(
        content: Any,
    ) -> str | None:
        if content is None:
            return None

        if isinstance(
            content,
            str,
        ):
            return content

        if isinstance(
            content,
            Mapping,
        ):
            if "text" in content:
                return str(content["text"])

            if "parts" in content:
                return GeminiAdapterPlugin._extract_message_text(content["parts"])

            return None

        if isinstance(
            content,
            list,
        ):
            values: list[str] = []

            for item in content:
                text = GeminiAdapterPlugin._extract_message_text(item)

                if text:
                    values.append(text)

            return "\n".join(values) if values else None

        return str(content)

    # ------------------------------------------------------------------
    # Generic serialization / SDK helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _value(
        value: Any,
        name: str,
    ) -> Any:
        if isinstance(
            value,
            Mapping,
        ):
            return value.get(name)

        return getattr(
            value,
            name,
            None,
        )

    @classmethod
    def _serialize(
        cls,
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return value

        if isinstance(
            value,
            Mapping,
        ):
            return {str(key): cls._serialize(item) for key, item in value.items()}

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            return [cls._serialize(item) for item in value]

        for method_name in (
            "model_dump",
            "to_json_dict",
            "dict",
        ):
            method = getattr(
                value,
                method_name,
                None,
            )

            if callable(method):
                try:
                    return cls._serialize(method())
                except Exception:
                    pass

        try:
            return {
                str(key): cls._serialize(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        except Exception:
            return str(value)

    @classmethod
    def _summarize_stream_event(
        cls,
        event: Any,
    ) -> dict[str, Any] | None:
        event_type = cls._value(
            event,
            "event_type",
        ) or cls._value(
            event,
            "type",
        )

        if not event_type:
            return None

        summary: dict[str, Any] = {"event_type": str(event_type)}

        step = cls._value(
            event,
            "step",
        )

        if step is not None:
            step_type = cls._value(
                step,
                "type",
            )

            if step_type:
                summary["step_type"] = str(step_type)

        delta = cls._value(
            event,
            "delta",
        )

        if delta is not None:
            delta_type = cls._value(
                delta,
                "type",
            )

            if delta_type:
                summary["delta_type"] = str(delta_type)

        status = cls._value(
            event,
            "status",
        )

        if status is not None:
            summary["status"] = str(status)

        return summary

    # ------------------------------------------------------------------
    # Errors / telemetry
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_usage(
        metadata: dict[str, Any],
    ) -> None:
        usage = metadata.get("usage") or {}

        if not isinstance(
            usage,
            Mapping,
        ):
            return

        prompt_tokens = (
            usage.get("prompt_token_count")
            or usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )

        completion_tokens = (
            usage.get("candidates_token_count")
            or usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )

        total_tokens = (
            usage.get("total_token_count")
            or usage.get("total_tokens")
            or (prompt_tokens + completion_tokens)
        )

        if not any(
            (
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
        ):
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
    # Provider error handling
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_status_code(
        exc: BaseException,
    ) -> int | None:
        for attr in (
            "code",
            "status_code",
            "status",
        ):
            value = getattr(
                exc,
                attr,
                None,
            )

            if isinstance(
                value,
                int,
            ):
                return value

            if (
                isinstance(
                    value,
                    str,
                )
                and value.isdigit()
            ):
                return int(value)

        return None

    @staticmethod
    def _extract_retry_after(
        exc: BaseException,
    ) -> float | None:
        raw_response = getattr(
            exc,
            "raw_response",
            None,
        )

        if raw_response is not None:
            try:
                headers = getattr(
                    raw_response,
                    "headers",
                    None,
                )

                if headers:
                    value = headers.get("Retry-After")

                    if value is not None:
                        return max(
                            0.0,
                            float(value),
                        )
            except (
                TypeError,
                ValueError,
                AttributeError,
            ):
                pass

        headers = getattr(
            exc,
            "headers",
            None,
        )

        if headers:
            try:
                value = headers.get("Retry-After")

                if value is not None:
                    return max(
                        0.0,
                        float(value),
                    )
            except (
                TypeError,
                ValueError,
                AttributeError,
            ):
                pass

        return None

    @staticmethod
    def _safe_error_message(
        exc: BaseException,
    ) -> str:
        message = getattr(
            exc,
            "message",
            None,
        )

        if (
            not isinstance(
                message,
                str,
            )
            or not message.strip()
        ):
            message = str(exc)

        sensitive_markers = (
            "api_key",
            "access_token",
            "Authorization:",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "x-goog-api-key",
        )

        if any(marker in message for marker in sensitive_markers):
            return "Gemini request failed; provider returned a credential-sensitive error."

        return f"Gemini SDK Error: {message}"


__all__ = ["GeminiAdapterPlugin"]
