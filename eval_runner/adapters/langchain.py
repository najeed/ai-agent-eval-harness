# eval_runner/adapters/langchain.py

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import inspect
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import urlparse

import aiohttp

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import (
    AdapterSessionPool,
    AESCallbackHandler,
    BaseAdapter,
    DualNormalizationHub,
)

logger = logging.getLogger(__name__)


class LangChainAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production LangChain adapter.

    Supported execution modes:

      Local:
        - Runnable / ainvoke
        - Runnable / invoke
        - Runnable / astream

      Remote:
        - LangServe /invoke
        - LangServe /stream

    Resolution order:

      1. Explicit endpoint argument / payload URL -> remote LangServe
      2. metadata.langserve_url -> remote LangServe
      3. metadata.runnable -> local Runnable
      4. metadata.chain_path -> imported Runnable/factory
      5. fail closed

    The adapter accepts both simple task strings and richer payloads:

      input
      input_payload
      messages
      task_description
      task
      message

    For multi-turn/local callers, history may also be supplied through:
      history

    Canonical return contract:

        {
            "status": "success" | "error",
            "output": <JSON-compatible output>,
            "action": <normalized AgentV action>,
            "metadata": {...}
        }
    """

    def __init__(
        self,
        session_pool: AdapterSessionPool | None = None,
    ) -> None:
        BaseAdapter.__init__(
            self,
            name="langchain",
            session_pool=session_pool,
        )

    def on_discover_adapters(self, registry: Any) -> None:
        registry.register("langchain", self.execute_langchain_query)
        registry.register("langchain:v1", self.execute_langchain_query)

    async def execute_langserve_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        return await self.execute_langchain_query(payload, endpoint)

    async def execute_langchain_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._error("LangChain adapter payload must be a dictionary.")

        task_id = str(
            payload.get("task_id")
            or payload.get("run_id")
            or payload.get("agent_id")
            or "default_task"
        )

        try:
            target_url = self._resolve_remote_url(
                payload=payload,
                endpoint=endpoint,
            )

            if target_url:
                return await self._execute_remote(
                    task_id=task_id,
                    payload=payload,
                    url=target_url,
                )

            runnable = await self._resolve_local_runnable(payload)

            if runnable is None:
                return self._error(
                    "No LangChain execution target configured. "
                    "Provide a remote endpoint or metadata.chain_path/"
                    "metadata.runnable."
                )

            return await self._execute_local(
                task_id=task_id,
                payload=payload,
                runnable=runnable,
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("LangChain adapter execution failed")
            self._emit_error(
                task_id=task_id,
                mode="dispatch",
                exc=exc,
                payload=payload,
            )
            return self._error(
                f"LangChain execution failed: {exc}",
                metadata={
                    "framework": "langchain",
                    "protocol": "v1",
                    "task_id": task_id,
                },
            )

    # ------------------------------------------------------------------
    # Local execution
    # ------------------------------------------------------------------

    async def _resolve_local_runnable(
        self,
        payload: dict[str, Any],
    ) -> Any | None:
        metadata = self._metadata(payload)

        direct = metadata.get("runnable")
        if direct is not None:
            runnable = await self._materialize_runnable(direct)
            self._validate_runnable(runnable)
            return runnable

        chain_path = (
            metadata.get("chain_path") or payload.get("chain_path") or metadata.get("runnable_path")
        )

        if not chain_path:
            return None

        runnable = await self._load_object_path(str(chain_path))
        runnable = await self._materialize_runnable(runnable)
        self._validate_runnable(runnable)
        return runnable

    async def _load_object_path(
        self,
        object_path: str,
    ) -> Any:
        if ":" not in object_path:
            raise ValueError(
                f"Invalid LangChain target '{object_path}'. Expected 'module:attribute'."
            )

        module_name, attr_path = object_path.split(":", 1)
        module_name = module_name.strip()
        attr_path = attr_path.strip()

        if not module_name or not attr_path:
            raise ValueError(
                f"Invalid LangChain target '{object_path}'. "
                "Expected non-empty module and attribute."
            )

        module = importlib.import_module(module_name)
        value: Any = module

        for part in attr_path.split("."):
            part = part.strip()

            if not part:
                raise ValueError(f"Invalid LangChain attribute path '{object_path}'.")

            value = getattr(value, part)

        return value

    async def _materialize_runnable(
        self,
        target: Any,
    ) -> Any:
        runnable_type = self._langchain_runnable_type()

        if runnable_type is not None and isinstance(target, runnable_type):
            return target

        if inspect.isclass(target):
            instance = target()

            if inspect.isawaitable(instance):
                instance = await instance

            return instance

        if callable(target):
            try:
                result = target()
            except TypeError:
                return target

            if inspect.isawaitable(result):
                result = await result

            return result

        return target

    def _validate_runnable(
        self,
        runnable: Any,
    ) -> None:
        if (
            not callable(getattr(runnable, "ainvoke", None))
            and not callable(getattr(runnable, "invoke", None))
            and not callable(getattr(runnable, "astream", None))
        ):
            raise TypeError(
                "Configured LangChain target is not executable. "
                "Expected ainvoke(), invoke(), or astream()."
            )

    async def _execute_local(
        self,
        task_id: str,
        payload: dict[str, Any],
        runnable: Any,
    ) -> dict[str, Any]:
        metadata = self._metadata(payload)
        input_data = self._resolve_input(payload)

        callback_handler = AESCallbackHandler(
            adapter_name="langchain",
            identifier=task_id,
            span_context=self._span_context(payload),
        )

        runnable_config = self._build_runnable_config(
            payload=payload,
            callback_handler=callback_handler,
        )

        requested_mode = self._execution_mode(
            payload=payload,
            metadata=metadata,
        )

        self._emit_chain_start(
            task_id=task_id,
            mode=f"local_{requested_mode}",
            payload=payload,
        )

        try:
            if requested_mode == "stream":
                output = await self._stream_local(
                    runnable=runnable,
                    input_data=input_data,
                    runnable_config=runnable_config,
                    payload=payload,
                    task_id=task_id,
                )
            else:
                output = await self._invoke_local(
                    runnable=runnable,
                    input_data=input_data,
                    runnable_config=runnable_config,
                )

            normalized_output = self._to_jsonable(output)
            action = self._normalize_output(
                normalized_output,
                status_code=200,
            )

            self._emit_chain_end(
                task_id=task_id,
                mode=f"local_{requested_mode}",
                action=action,
                payload=payload,
            )

            return {
                "status": "success",
                "output": normalized_output,
                "action": action,
                "metadata": {
                    "framework": "langchain",
                    "protocol": "v1",
                    "mode": "local",
                    "execution_mode": requested_mode,
                    "task_id": task_id,
                    "target": (
                        metadata.get("chain_path")
                        or metadata.get("runnable_path")
                        or "in_process_runnable"
                    ),
                    "version": self._package_version("langchain"),
                    "langchain_core_version": self._package_version("langchain-core"),
                },
            }

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit_error(
                task_id=task_id,
                mode=f"local_{requested_mode}",
                exc=exc,
                payload=payload,
            )

            return self._error(
                f"LangChain local execution failed: {exc}",
                metadata={
                    "framework": "langchain",
                    "protocol": "v1",
                    "mode": "local",
                    "execution_mode": requested_mode,
                    "task_id": task_id,
                },
            )

    async def _invoke_local(
        self,
        runnable: Any,
        input_data: Any,
        runnable_config: dict[str, Any],
    ) -> Any:
        ainvoke = getattr(runnable, "ainvoke", None)

        if callable(ainvoke):
            return await ainvoke(
                input_data,
                config=runnable_config,
            )

        invoke = getattr(runnable, "invoke", None)

        if not callable(invoke):
            raise TypeError("LangChain target exposes neither ainvoke() nor invoke().")

        return await asyncio.to_thread(
            invoke,
            input_data,
            config=runnable_config,
        )

    async def _stream_local(
        self,
        runnable: Any,
        input_data: Any,
        runnable_config: dict[str, Any],
        payload: dict[str, Any],
        task_id: str,
    ) -> Any:
        astream = getattr(runnable, "astream", None)

        if not callable(astream):
            raise TypeError(
                "LangChain streaming was requested but the configured "
                "Runnable does not expose astream()."
            )

        chunks: list[Any] = []

        async for chunk in astream(
            input_data,
            config=runnable_config,
        ):
            chunks.append(chunk)

            emit(
                CoreEvents.ADAPTER_DEBUG,
                {
                    "adapter": "langchain",
                    "task_id": task_id,
                    "event": "stream_chunk",
                    "chunk_type": type(chunk).__name__,
                },
                span_context=self._span_context(payload),
            )

        if not chunks:
            raise ValueError("LangChain streaming completed without emitting any chunks.")

        if self._all_textual(chunks):
            return "".join(self._extract_text(chunk) for chunk in chunks)

        return {"chunks": [self._to_jsonable(chunk) for chunk in chunks]}

    # ------------------------------------------------------------------
    # Remote LangServe
    # ------------------------------------------------------------------

    async def _execute_remote(
        self,
        task_id: str,
        payload: dict[str, Any],
        url: str,
    ) -> dict[str, Any]:
        metadata = self._metadata(payload)

        mode = self._execution_mode(
            payload=payload,
            metadata=metadata,
            remote=True,
        )

        if mode not in {"invoke", "stream"}:
            return self._error(
                f"Unsupported LangServe mode '{mode}'. Expected 'invoke' or 'stream'."
            )

        endpoint = self._resolve_langserve_endpoint(
            url=url,
            mode=mode,
        )

        input_data = self._resolve_input(payload)

        request_body: dict[str, Any] = {
            "input": input_data,
        }

        config_data = metadata.get("config")

        if isinstance(config_data, Mapping) and config_data:
            request_body["config"] = dict(config_data)

        kwargs_data = metadata.get("kwargs")

        if isinstance(kwargs_data, Mapping) and kwargs_data:
            request_body["kwargs"] = dict(kwargs_data)

        headers = self._build_remote_headers(payload)

        self._emit_chain_start(
            task_id=task_id,
            mode=f"remote_{mode}",
            payload=payload,
            url=endpoint,
        )

        try:
            if mode == "invoke":
                response = await self._remote_invoke(
                    endpoint=endpoint,
                    request_body=request_body,
                    headers=headers,
                    payload=payload,
                )
            else:
                response = await self._remote_stream(
                    endpoint=endpoint,
                    request_body=request_body,
                    headers=headers,
                    payload=payload,
                    task_id=task_id,
                )

            normalized_output = self._extract_langserve_output(response)
            action = self._normalize_output(
                normalized_output,
                status_code=200,
            )

            self._emit_chain_end(
                task_id=task_id,
                mode=f"remote_{mode}",
                action=action,
                payload=payload,
                url=endpoint,
            )

            return {
                "status": "success",
                "output": normalized_output,
                "action": action,
                "metadata": {
                    "framework": "langchain",
                    "protocol": "v1",
                    "mode": "remote",
                    "transport": "langserve",
                    "execution_mode": mode,
                    "endpoint": endpoint,
                    "task_id": task_id,
                    "version": self._package_version("langchain"),
                    "langchain_core_version": self._package_version("langchain-core"),
                },
            }

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit_error(
                task_id=task_id,
                mode=f"remote_{mode}",
                exc=exc,
                payload=payload,
                url=endpoint,
            )

            return self._error(
                f"LangServe execution failed: {exc}",
                metadata={
                    "framework": "langchain",
                    "protocol": "v1",
                    "mode": "remote",
                    "transport": "langserve",
                    "execution_mode": mode,
                    "task_id": task_id,
                    "endpoint": endpoint,
                },
            )

    async def _remote_invoke(
        self,
        endpoint: str,
        request_body: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> Any:
        session = await self.get_session()
        timeout = self._request_timeout(payload)

        async def _call() -> Any:
            async with session.post(
                endpoint,
                json=request_body,
                headers=headers,
                timeout=timeout,
            ) as response:
                response_data = await self._read_json_or_text(response)

                if response.status >= 400:
                    self._raise_http_error(
                        response.status,
                        response_data,
                    )

                return response_data

        if self._retry_enabled(payload):
            return await self.call_with_retry(
                _call,
                deadline=self._retry_deadline(payload),
            )

        return await _call()

    async def _remote_stream(
        self,
        endpoint: str,
        request_body: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        session = await self.get_session()

        stream_headers = dict(headers)
        stream_headers["Accept"] = "text/event-stream"

        timeout = self._request_timeout(payload)

        async with session.post(
            endpoint,
            json=request_body,
            headers=stream_headers,
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                response_data = await self._read_json_or_text(response)
                self._raise_http_error(
                    response.status,
                    response_data,
                )

            chunks: list[Any] = []
            text_parts: list[str] = []
            event_metadata: dict[str, Any] = {}

            async for event in self._iter_sse_events(response.content):
                event_name = str(event.get("event") or "message")
                raw_data = event.get("data")

                if raw_data in (None, ""):
                    continue

                if raw_data == "[DONE]":
                    break

                parsed = self._decode_json_if_possible(raw_data)

                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "langchain",
                        "task_id": task_id,
                        "event": event_name,
                    },
                    span_context=self._span_context(payload),
                )

                chunk, metadata = self._normalize_stream_event(parsed)

                if metadata:
                    event_metadata.update(metadata)

                if chunk is None:
                    continue

                chunks.append(chunk)

                text = self._extract_text(chunk)

                if text:
                    text_parts.append(text)

            if not chunks:
                raise ValueError("LangServe stream completed without emitting usable output.")

            if self._all_textual(chunks):
                output: Any = "".join(text_parts)
            elif len(chunks) == 1:
                output = chunks[0]
            else:
                output = {
                    "chunks": [self._to_jsonable(chunk) for chunk in chunks],
                    "content": "".join(text_parts),
                    "metadata": event_metadata,
                }

            return {
                "output": output,
                "metadata": event_metadata,
            }

    async def _iter_sse_events(
        self,
        content: Any,
    ) -> AsyncIterator[dict[str, str]]:
        event_name = "message"
        event_id = ""
        retry = ""
        data_lines: list[str] = []

        async for raw_line in content:
            line = raw_line.decode(
                "utf-8",
                errors="replace",
            ).rstrip("\r\n")

            if line == "":
                if data_lines:
                    yield {
                        "event": event_name,
                        "id": event_id,
                        "retry": retry,
                        "data": "\n".join(data_lines),
                    }

                event_name = "message"
                event_id = ""
                retry = ""
                data_lines = []
                continue

            if line.startswith(":"):
                continue

            field, separator, value = line.partition(":")

            if separator and value.startswith(" "):
                value = value[1:]

            if field == "event":
                event_name = value
            elif field == "id":
                event_id = value
            elif field == "retry":
                retry = value
            elif field == "data":
                data_lines.append(value)

        if data_lines:
            yield {
                "event": event_name,
                "id": event_id,
                "retry": retry,
                "data": "\n".join(data_lines),
            }

    def _normalize_stream_event(
        self,
        event: Any,
    ) -> tuple[Any, dict[str, Any]]:
        if not isinstance(event, Mapping):
            return event, {}

        metadata: dict[str, Any] = {}

        raw_metadata = event.get("metadata")

        if isinstance(raw_metadata, Mapping):
            metadata.update(raw_metadata)

        if "data" in event:
            data = event["data"]

            if isinstance(data, Mapping):
                nested_metadata = data.get("metadata")

                if isinstance(nested_metadata, Mapping):
                    metadata.update(nested_metadata)

                if "chunk" in data:
                    return data["chunk"], metadata

                if "output" in data:
                    return data["output"], metadata

            return data, metadata

        if "chunk" in event:
            return event["chunk"], metadata

        if "output" in event:
            return event["output"], metadata

        return dict(event), metadata

    # ------------------------------------------------------------------
    # Input / execution config
    # ------------------------------------------------------------------

    def _resolve_input(
        self,
        payload: dict[str, Any],
    ) -> Any:
        if "input" in payload:
            return payload["input"]

        if "input_payload" in payload:
            return payload["input_payload"]

        if "messages" in payload:
            return payload["messages"]

        if "history" in payload:
            current = payload.get("task_description")

            history = payload.get("history")
            if isinstance(history, list) and history:
                if current is None:
                    return history

                return {
                    "history": history,
                    "input": current,
                }

        for key in (
            "task_description",
            "task",
            "message",
        ):
            value = payload.get(key)

            if value is not None:
                return value

        raise ValueError(
            "LangChain adapter received no executable input. "
            "Expected one of: input, input_payload, messages, "
            "history, task_description, task, message."
        )

    def _build_runnable_config(
        self,
        payload: dict[str, Any],
        callback_handler: AESCallbackHandler,
    ) -> dict[str, Any]:
        metadata = self._metadata(payload)

        raw_config = metadata.get("config")

        config_data: dict[str, Any] = dict(raw_config) if isinstance(raw_config, Mapping) else {}

        callbacks = config_data.get("callbacks")

        if callbacks is None:
            callbacks = []
        elif not isinstance(callbacks, list):
            callbacks = [callbacks]

        if not any(callback is callback_handler for callback in callbacks):
            callbacks.append(callback_handler)

        config_data["callbacks"] = callbacks

        tags = config_data.get("tags")

        if tags is None:
            tags = []
        elif not isinstance(tags, list):
            tags = [tags]

        if "agentv" not in tags:
            tags.append("agentv")

        if "verification" not in tags:
            tags.append("verification")

        config_data["tags"] = tags

        callback_metadata = config_data.get("metadata")

        if not isinstance(callback_metadata, dict):
            callback_metadata = {}

        callback_metadata.update(
            {
                "agentv.adapter": "langchain",
                "agentv.task_id": str(
                    payload.get("task_id") or payload.get("run_id") or "default_task"
                ),
            }
        )

        if payload.get("run_id") is not None:
            callback_metadata["agentv.run_id"] = str(payload["run_id"])

        if payload.get("scenario_id") is not None:
            callback_metadata["agentv.scenario_id"] = str(payload["scenario_id"])

        config_data["metadata"] = callback_metadata

        for key in (
            "max_concurrency",
            "recursion_limit",
            "run_name",
            "configurable",
        ):
            if key in metadata and key not in config_data:
                config_data[key] = metadata[key]

        return config_data

    def _execution_mode(
        self,
        payload: dict[str, Any],
        metadata: Mapping[str, Any],
        *,
        remote: bool = False,
    ) -> str:
        raw_mode = (
            metadata.get("langserve_mode" if remote else "langchain_mode")
            or metadata.get("execution_mode")
            or payload.get("mode")
            or payload.get("stream_mode")
            or "invoke"
        )

        mode = str(raw_mode).strip().lower()

        aliases = {
            "async": "invoke",
            "ainvoke": "invoke",
            "sync": "invoke",
            "invoke": "invoke",
            "stream": "stream",
            "astream": "stream",
        }

        if mode not in aliases:
            raise ValueError(f"Unsupported LangChain execution mode '{mode}'.")

        return aliases[mode]

    # ------------------------------------------------------------------
    # Remote transport
    # ------------------------------------------------------------------

    def _resolve_remote_url(
        self,
        payload: dict[str, Any],
        endpoint: str | None,
    ) -> str | None:
        metadata = self._metadata(payload)

        candidate = (
            endpoint
            or payload.get("url")
            or payload.get("base_url")
            or metadata.get("langserve_url")
        )

        if candidate is None:
            return None

        candidate = str(candidate).strip()

        if not candidate:
            return None

        parsed = urlparse(candidate)

        if (
            parsed.scheme
            not in {
                "http",
                "https",
            }
            or not parsed.netloc
        ):
            raise ValueError(
                f"Invalid LangServe endpoint '{candidate}'. Expected an http:// or https:// URL."
            )

        return candidate.rstrip("/")

    def _resolve_langserve_endpoint(
        self,
        url: str,
        mode: str,
    ) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        if path.endswith("/invoke"):
            path = path[: -len("/invoke")]

        if path.endswith("/stream"):
            path = path[: -len("/stream")]

        path = f"{path}/{mode}"

        return parsed._replace(
            path=path,
        ).geturl()

    def _build_remote_headers(
        self,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        metadata = self._metadata(payload)

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        custom_headers = metadata.get("headers")

        if isinstance(custom_headers, Mapping):
            for key, value in custom_headers.items():
                if value is None:
                    continue

                headers[str(key)] = str(value)

        api_key = (
            payload.get("api_key") or metadata.get("api_key") or metadata.get("langserve_api_key")
        )

        if api_key and "Authorization" not in headers and "X-API-Key" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"

        bearer_token = metadata.get("bearer_token")

        if bearer_token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {bearer_token}"

        traceparent = self._validated_traceparent(payload)

        if traceparent:
            headers["traceparent"] = traceparent

        return headers

    # ------------------------------------------------------------------
    # Output normalization
    # ------------------------------------------------------------------

    def _extract_langserve_output(
        self,
        response: Any,
    ) -> Any:
        if isinstance(response, Mapping):
            if "output" in response:
                return response["output"]

            if "result" in response and len(response) <= 2:
                return response["result"]

            if "response" in response and len(response) <= 2:
                return response["response"]

        return response

    def _normalize_output(
        self,
        output: Any,
        status_code: int,
    ) -> str:
        if isinstance(output, Mapping):
            return DualNormalizationHub.normalize(
                output,
                status_code,
            )

        text = self._extract_text(output)

        if not text:
            raise ValueError("LangChain execution completed without a usable output.")

        return DualNormalizationHub.normalize_text(text)

    def _extract_text(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, bytes):
            return value.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(value, Mapping):
            for key in (
                "content",
                "text",
                "output",
                "message",
                "answer",
                "result",
            ):
                if key not in value:
                    continue

                extracted = self._extract_text(value[key])

                if extracted:
                    return extracted

            if "content_blocks" in value:
                return self._extract_text(value["content_blocks"])

            return ""

        if isinstance(value, (list, tuple)):
            parts: list[str] = []

            for item in value:
                text = self._extract_text(item)

                if text:
                    parts.append(text)

            return "".join(parts)

        content = getattr(
            value,
            "content",
            None,
        )

        if content is not None:
            return self._extract_text(content)

        text_attr = getattr(
            value,
            "text",
            None,
        )

        if callable(text_attr):
            try:
                return self._extract_text(text_attr())
            except Exception:
                return ""

        if text_attr is not None:
            return self._extract_text(text_attr)

        return str(value)

    def _to_jsonable(
        self,
        value: Any,
    ) -> Any:
        if value is None or isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return value

        if isinstance(value, bytes):
            return value.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(value, Mapping):
            return {str(key): self._to_jsonable(item) for key, item in value.items()}

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            return [self._to_jsonable(item) for item in value]

        model_dump = getattr(
            value,
            "model_dump",
            None,
        )

        if callable(model_dump):
            try:
                return self._to_jsonable(model_dump(mode="json"))
            except TypeError:
                try:
                    return self._to_jsonable(model_dump())
                except Exception:
                    pass
            except Exception:
                pass

        dict_method = getattr(
            value,
            "dict",
            None,
        )

        if callable(dict_method):
            try:
                return self._to_jsonable(dict_method())
            except Exception:
                pass

        result: dict[str, Any] = {}

        content = getattr(
            value,
            "content",
            None,
        )

        if content is not None:
            result["content"] = self._to_jsonable(content)

            for attribute in (
                "response_metadata",
                "usage_metadata",
                "tool_calls",
                "additional_kwargs",
            ):
                attribute_value = getattr(
                    value,
                    attribute,
                    None,
                )

                if attribute_value:
                    result[attribute] = self._to_jsonable(attribute_value)

            return result

        try:
            json.dumps(value)
            return value
        except (
            TypeError,
            ValueError,
        ):
            return str(value)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _read_json_or_text(
        self,
        response: aiohttp.ClientResponse,
    ) -> Any:
        content_type = str(
            response.headers.get(
                "Content-Type",
                "",
            )
        ).lower()

        if "json" in content_type:
            try:
                return await response.json()
            except Exception:
                pass

        text = await response.text()

        if not text:
            return {}

        return self._decode_json_if_possible(text)

    def _decode_json_if_possible(
        self,
        value: Any,
    ) -> Any:
        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except (
            TypeError,
            ValueError,
        ):
            return value

    def _raise_http_error(
        self,
        status_code: int,
        response_data: Any,
    ) -> None:
        if isinstance(response_data, Mapping):
            detail = (
                response_data.get("detail")
                or response_data.get("message")
                or response_data.get("error")
            )
        else:
            detail = response_data

        message = str(detail or f"HTTP {status_code}")

        raise aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=int(status_code),
            message=message[:1000],
        )

    def _request_timeout(
        self,
        payload: dict[str, Any],
    ) -> aiohttp.ClientTimeout:
        metadata = self._metadata(payload)

        raw_timeout = metadata.get("timeout") or payload.get("timeout")

        if raw_timeout is None:
            timeout = 30.0
        else:
            timeout = float(raw_timeout)

        if timeout <= 0:
            raise ValueError("LangChain adapter timeout must be greater than zero.")

        return aiohttp.ClientTimeout(total=timeout)

    def _retry_enabled(
        self,
        payload: dict[str, Any],
    ) -> bool:
        metadata = self._metadata(payload)

        return bool(metadata.get("retry_idempotent") or payload.get("retry_idempotent"))

    def _retry_deadline(
        self,
        payload: dict[str, Any],
    ) -> float | None:
        metadata = self._metadata(payload)

        raw_deadline = metadata.get("retry_deadline") or payload.get("retry_deadline")

        if raw_deadline is None:
            return None

        deadline = float(raw_deadline)

        if deadline <= 0:
            raise ValueError("LangChain retry_deadline must be greater than zero.")

        return deadline

    def _validated_traceparent(
        self,
        payload: dict[str, Any],
    ) -> str | None:
        span_context = payload.get("span_context")

        if not isinstance(
            span_context,
            Mapping,
        ):
            return None

        traceparent = span_context.get("traceparent")

        if not isinstance(
            traceparent,
            str,
        ):
            return None

        parts = traceparent.split("-")

        if len(parts) != 4:
            return None

        if parts[0] != "00" or len(parts[1]) != 32 or len(parts[2]) != 16 or len(parts[3]) != 2:
            return None

        allowed = "0123456789abcdef"

        if any(character not in allowed for part in parts[1:] for character in part):
            return None

        if set(parts[1]) == {"0"}:
            return None

        if set(parts[2]) == {"0"}:
            return None

        return traceparent

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _emit_chain_start(
        self,
        task_id: str,
        mode: str,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "adapter": "langchain",
            "task_id": task_id,
            "protocol": "v1",
            "mode": mode,
        }

        if url:
            data["url"] = url

        emit(
            CoreEvents.CHAIN_START,
            data,
            span_context=self._span_context(payload),
        )

    def _emit_chain_end(
        self,
        task_id: str,
        mode: str,
        action: str,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "adapter": "langchain",
            "task_id": task_id,
            "protocol": "v1",
            "mode": mode,
            "action": action,
        }

        if url:
            data["url"] = url

        emit(
            CoreEvents.CHAIN_END,
            data,
            span_context=self._span_context(payload),
        )

    def _emit_error(
        self,
        task_id: str,
        mode: str,
        exc: Exception,
        payload: dict[str, Any],
        url: str | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "adapter": "langchain",
            "task_id": task_id,
            "protocol": "v1",
            "mode": mode,
            "message": str(exc),
        }

        if url:
            data["url"] = url

        emit(
            CoreEvents.ERROR,
            data,
            span_context=self._span_context(payload),
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata(
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        metadata = payload.get("metadata")

        return dict(metadata) if isinstance(metadata, Mapping) else {}

    @staticmethod
    def _span_context(
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        span_context = payload.get("span_context")

        return (
            dict(span_context)
            if isinstance(
                span_context,
                Mapping,
            )
            else None
        )

    def _error(
        self,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "error",
            "action": "error",
            "message": message,
        }

        if metadata:
            result["metadata"] = metadata

        return result

    def _langchain_runnable_type(
        self,
    ) -> type | None:
        try:
            from langchain_core.runnables import Runnable

            return Runnable
        except ImportError:
            return None

    def _package_version(
        self,
        package_name: str,
    ) -> str:
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def _all_textual(
        self,
        chunks: list[Any],
    ) -> bool:
        if not chunks:
            return True

        for chunk in chunks:
            if isinstance(chunk, str):
                continue

            if not self._extract_text(chunk):
                return False

        return True


async def adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Compatibility wrapper for module-level adapter discovery.
    """
    merged_payload = dict(payload or {})

    metadata = merged_payload.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}

    for key in (
        "langserve_url",
        "chain_path",
        "runnable",
        "config",
        "headers",
        "history",
        "messages",
        "input",
        "input_payload",
        "langchain_mode",
        "execution_mode",
    ):
        if key in kwargs and key not in metadata:
            metadata[key] = kwargs[key]

    if metadata:
        merged_payload["metadata"] = metadata

    session_pool = kwargs.get("session_pool")

    plugin = LangChainAdapterPlugin(
        session_pool=(
            session_pool
            if isinstance(
                session_pool,
                AdapterSessionPool,
            )
            else None
        )
    )

    return await plugin.execute_langchain_query(
        merged_payload,
        endpoint=endpoint,
    )
