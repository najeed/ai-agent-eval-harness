# eval_runner/adapters/langchain.py

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import urlparse

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import AESCallbackHandler, BaseAdapter, DualNormalizationHub, SessionManager

logger = logging.getLogger(__name__)


class LangChainAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Production LangChain adapter.

    Supported execution modes:
      1. Local native Runnable execution via metadata.chain_path
      2. Direct local Runnable object supplied through metadata.runnable
      3. Remote LangServe execution via HTTP /invoke
      4. Remote LangServe streaming via HTTP /stream

    The adapter never fabricates an execution result. A missing target is an error.

    Expected local binding:
        metadata:
          chain_path: "my_package.my_chain:chain"

    The resolved object may be:
      - a LangChain Runnable
      - a zero-argument factory returning a Runnable
      - a zero-argument callable returning a compatible object

    Expected remote binding:
        url: "https://agent.example.com/my_chain"
        or
        metadata:
          langserve_url: "https://agent.example.com/my_chain"

    Canonical return contract:
        {
            "status": "success" | "error",
            "output": <JSON-compatible output>,
            "action": <normalized AgentV action>,
            "metadata": {...}
        }
    """

    def __init__(self) -> None:
        BaseAdapter.__init__(self, name="langchain")

    def on_discover_adapters(self, registry: Any) -> None:
        """Register LangChain protocols."""
        registry.register("langchain", self.execute_langchain_query)
        registry.register("langchain:v1", self.execute_langchain_query)

    async def execute_langserve_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Backward-compatible entry point for legacy LangServe callers."""
        return await self.execute_langchain_query(payload, endpoint)

    async def execute_langchain_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a real LangChain target.

        Resolution order:
          1. Explicit endpoint argument / payload URL -> remote LangServe
          2. metadata.langserve_url -> remote LangServe
          3. metadata.runnable -> local Runnable
          4. metadata.chain_path -> local imported Runnable
          5. otherwise fail closed
        """
        if not isinstance(payload, dict):
            return self._error("LangChain adapter payload must be a dictionary.")

        task_id = str(
            payload.get("task_id")
            or payload.get("run_id")
            or payload.get("agent_id")
            or "default_task"
        )

        try:
            target_url = self._resolve_remote_url(payload, endpoint)

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
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "langchain",
                    "task_id": task_id,
                    "message": str(exc),
                },
                span_context=payload.get("span_context"),
            )
            return self._error(f"LangChain execution failed: {exc}")

    # ------------------------------------------------------------------
    # Local execution
    # ------------------------------------------------------------------

    async def _resolve_local_runnable(
        self,
        payload: dict[str, Any],
    ) -> Any | None:
        """
        Resolve an actual LangChain Runnable.

        A direct object injection is supported for embedded/in-process use.
        For durable scenario definitions, chain_path is preferred because it
        is serializable and reproducible.
        """
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

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

    async def _load_object_path(self, object_path: str) -> Any:
        """
        Resolve module:attribute, including nested attributes.

        Example:
            my_agent.graph:compiled_chain
            my_agent.chains:factory
            my_agent.graph:workflow.invoke_target
        """
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

    async def _materialize_runnable(self, target: Any) -> Any:
        """
        Materialize a Runnable or a zero-argument factory.

        We deliberately do not invoke arbitrary functions with evaluation
        payloads. Application-specific target construction must be explicit.
        """
        runnable_type = self._langchain_runnable_type()

        if runnable_type is not None and isinstance(target, runnable_type):
            return target

        if inspect_is_class(target):
            instance = target()
            if inspect_is_awaitable(instance):
                instance = await instance
            return instance

        if callable(target):
            # Only invoke zero-argument factories. We do not pass the
            # evaluation payload to arbitrary application callables.
            try:
                result = target()
            except TypeError:
                return target

            if inspect_is_awaitable(result):
                result = await result

            return result

        return target

    def _validate_runnable(self, runnable: Any) -> None:
        """
        Validate the concrete execution seam.

        LangChain's canonical Runnable execution API is ainvoke/invoke.
        """
        if not callable(getattr(runnable, "ainvoke", None)) and not callable(
            getattr(runnable, "invoke", None)
        ):
            raise TypeError(
                "Configured LangChain target is not executable. "
                "Expected a Runnable exposing ainvoke() or invoke()."
            )

    async def _execute_local(
        self,
        task_id: str,
        payload: dict[str, Any],
        runnable: Any,
    ) -> dict[str, Any]:
        """Execute a real local LangChain Runnable."""
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        input_data = self._resolve_input(payload)

        callback_handler = AESCallbackHandler(
            adapter_name="langchain",
            identifier=task_id,
        )

        runnable_config = self._build_runnable_config(
            payload=payload,
            callback_handler=callback_handler,
        )

        self._emit_chain_start(
            task_id=task_id,
            mode="local",
            payload=payload,
        )

        try:
            output = await self._invoke_runnable(
                runnable=runnable,
                input_data=input_data,
                runnable_config=runnable_config,
            )

            normalized_output = self._to_jsonable(output)
            action = self._normalize_output(normalized_output, status_code=200)

            self._emit_chain_end(
                task_id=task_id,
                mode="local",
                action=action,
                payload=payload,
            )

            return {
                "status": "success",
                "output": normalized_output,
                "action": action,
                "metadata": {
                    "framework": "langchain",
                    "version": self._package_version("langchain"),
                    "langchain_core_version": self._package_version("langchain-core"),
                    "protocol": "v1",
                    "mode": "local",
                    "task_id": task_id,
                    "target": metadata.get("chain_path") or "in_process_runnable",
                },
            }

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit_error(task_id, "local", exc, payload)
            return self._error(
                f"LangChain local execution failed: {exc}",
                metadata={
                    "framework": "langchain",
                    "mode": "local",
                    "task_id": task_id,
                },
            )

    async def _invoke_runnable(
        self,
        runnable: Any,
        input_data: Any,
        runnable_config: dict[str, Any],
    ) -> Any:
        """
        Invoke without blindly retrying the workflow.

        Retrying a whole agent execution can duplicate side effects. Transport
        retries belong below the agent execution boundary unless the target
        explicitly supplies idempotency guarantees.
        """
        ainvoke = getattr(runnable, "ainvoke", None)

        if callable(ainvoke):
            return await ainvoke(input_data, config=runnable_config)

        invoke = getattr(runnable, "invoke", None)
        if not callable(invoke):
            raise TypeError("LangChain target exposes neither ainvoke() nor invoke().")

        return await asyncio.to_thread(
            invoke,
            input_data,
            config=runnable_config,
        )

    # ------------------------------------------------------------------
    # Remote LangServe execution
    # ------------------------------------------------------------------

    async def _execute_remote(
        self,
        task_id: str,
        payload: dict[str, Any],
        url: str,
    ) -> dict[str, Any]:
        """Execute a remote LangServe deployment."""
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        mode = str(metadata.get("langserve_mode") or payload.get("mode") or "invoke").lower()
        if mode not in {"invoke", "stream"}:
            return self._error(
                f"Unsupported LangServe mode '{mode}'. Expected 'invoke' or 'stream'."
            )

        endpoint = self._resolve_langserve_endpoint(url, mode)
        input_data = self._resolve_input(payload)

        request_body = {
            "input": input_data,
        }

        # Preserve explicit LangServe configuration when provided.
        config_data = metadata.get("config")
        if isinstance(config_data, dict) and config_data:
            request_body["config"] = config_data

        kwargs_data = metadata.get("kwargs")
        if isinstance(kwargs_data, dict) and kwargs_data:
            request_body["kwargs"] = kwargs_data

        headers = self._build_remote_headers(payload)

        self._emit_chain_start(
            task_id=task_id,
            mode=f"remote_{mode}",
            payload=payload,
            url=endpoint,
        )

        try:
            if mode == "stream":
                response = await self._remote_stream(
                    endpoint=endpoint,
                    request_body=request_body,
                    headers=headers,
                    payload=payload,
                    task_id=task_id,
                )
            else:
                response = await self._remote_invoke(
                    endpoint=endpoint,
                    request_body=request_body,
                    headers=headers,
                    payload=payload,
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
                    "version": self._package_version("langchain"),
                    "langchain_core_version": self._package_version("langchain-core"),
                    "protocol": "v1",
                    "mode": "remote",
                    "transport": "langserve",
                    "request_mode": mode,
                    "endpoint": endpoint,
                    "task_id": task_id,
                },
            }

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit_error(task_id, f"remote_{mode}", exc, payload, endpoint)
            return self._error(
                f"LangServe execution failed: {exc}",
                metadata={
                    "framework": "langchain",
                    "mode": "remote",
                    "transport": "langserve",
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
        """Execute LangServe /invoke."""
        session = await SessionManager.get_session()

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

        # Whole-agent invocation is not retried by default because it can
        # create duplicate side effects. Opt-in only when explicitly declared.
        if self._retry_enabled(payload):
            return await self.call_with_retry(_call)

        return await _call()

    async def _remote_stream(
        self,
        endpoint: str,
        request_body: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        """Execute LangServe /stream and aggregate the resulting stream."""
        session = await SessionManager.get_session()

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
                data = await self._read_json_or_text(response)
                self._raise_http_error(response.status, data)

            chunks: list[Any] = []
            text_parts: list[str] = []
            terminal_metadata: dict[str, Any] = {}

            async for event in self._iter_sse_events(response.content):
                event_name = str(event.get("event") or "")
                data = event.get("data")

                if data in (None, ""):
                    continue

                if data == "[DONE]":
                    break

                parsed = self._decode_json_if_possible(data)

                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "adapter": "langchain",
                        "task_id": task_id,
                        "event": event_name or "message",
                    },
                    span_context=payload.get("span_context"),
                )

                chunk = parsed

                if isinstance(parsed, dict):
                    # LangServe stream events can contain structured data
                    # alongside chunk output.
                    if "data" in parsed:
                        chunk = parsed["data"]

                    if isinstance(parsed.get("metadata"), dict):
                        terminal_metadata.update(parsed["metadata"])

                chunks.append(chunk)

                text = self._extract_text(chunk)
                if text:
                    text_parts.append(text)

            output: Any

            if len(chunks) == 1:
                output = chunks[0]
            elif self._all_textual(chunks):
                output = "".join(text_parts)
            else:
                output = {
                    "chunks": chunks,
                    "content": "".join(text_parts),
                    "metadata": terminal_metadata,
                }

            return {
                "output": output,
                "metadata": terminal_metadata,
            }

    async def _iter_sse_events(
        self,
        content: Any,
    ) -> AsyncIterator[dict[str, str]]:
        """
        Minimal standards-tolerant SSE parser.

        Handles:
          - event:
          - data:
          - id:
          - retry:
          - multiline data fields
          - blank-line event termination
        """
        event_name = "message"
        event_id = ""
        retry = ""
        data_lines: list[str] = []

        async for raw_line in content:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

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
            if separator:
                value = value[1:] if value.startswith(" ") else value

            if field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)
            elif field == "id":
                event_id = value
            elif field == "retry":
                retry = value

        if data_lines:
            yield {
                "event": event_name,
                "id": event_id,
                "retry": retry,
                "data": "\n".join(data_lines),
            }

    # ------------------------------------------------------------------
    # Input / config
    # ------------------------------------------------------------------

    def _resolve_input(self, payload: dict[str, Any]) -> Any:
        """
        Resolve the agent input without assuming one universal LangChain
        Runnable schema.

        Precedence:
          input
          input_payload
          messages
          task_description
          task
          message
        """
        if "input" in payload:
            return payload["input"]

        if "input_payload" in payload:
            return payload["input_payload"]

        if "messages" in payload:
            return payload["messages"]

        for key in ("task_description", "task", "message"):
            value = payload.get(key)
            if value is not None:
                return value

        raise ValueError(
            "LangChain adapter received no executable input. "
            "Expected one of: input, input_payload, messages, "
            "task_description, task, message."
        )

    def _build_runnable_config(
        self,
        payload: dict[str, Any],
        callback_handler: AESCallbackHandler,
    ) -> dict[str, Any]:
        """
        Construct LangChain RunnableConfig while preserving application-
        supplied configuration and enforcing AgentV telemetry.
        """
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        raw_config = metadata.get("config")
        config_data = dict(raw_config) if isinstance(raw_config, Mapping) else {}

        callbacks = config_data.get("callbacks")
        if callbacks is None:
            callbacks = []

        elif not isinstance(callbacks, list):
            callbacks = [callbacks]

        # AgentV telemetry cannot be omitted from an execution.
        callbacks = [*callbacks, callback_handler]
        config_data["callbacks"] = callbacks

        tags = config_data.get("tags")
        if tags is None:
            tags = []
        elif not isinstance(tags, list):
            tags = [tags]

        tags = [*tags, "agentv", "verification"]
        config_data["tags"] = tags

        agentv_metadata = config_data.get("metadata")
        if not isinstance(agentv_metadata, dict):
            agentv_metadata = {}

        agentv_metadata.update(
            {
                "agentv.adapter": "langchain",
                "agentv.task_id": str(
                    payload.get("task_id") or payload.get("run_id") or "default_task"
                ),
            }
        )

        if payload.get("run_id") is not None:
            agentv_metadata["agentv.run_id"] = str(payload["run_id"])

        if payload.get("scenario_id") is not None:
            agentv_metadata["agentv.scenario_id"] = str(payload["scenario_id"])

        config_data["metadata"] = agentv_metadata

        # Allow standard LangChain RunnableConfig controls.
        for key in (
            "max_concurrency",
            "recursion_limit",
            "max_concurrency",
            "run_name",
            "configurable",
        ):
            if key in metadata and key not in config_data:
                config_data[key] = metadata[key]

        return config_data

    # ------------------------------------------------------------------
    # Remote transport
    # ------------------------------------------------------------------

    def _resolve_remote_url(
        self,
        payload: dict[str, Any],
        endpoint: str | None,
    ) -> str | None:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        candidate = (
            endpoint
            or payload.get("url")
            or payload.get("base_url")
            or metadata.get("langserve_url")
        )

        if not candidate:
            return None

        candidate = str(candidate).strip()
        if not candidate:
            return None

        parsed = urlparse(candidate)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
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

        if path.endswith("/invoke") or path.endswith("/stream"):
            if mode == "stream" and not path.endswith("/stream"):
                path = f"{path}/stream"
            elif mode == "invoke" and not path.endswith("/invoke"):
                path = f"{path}/invoke"
        else:
            path = f"{path}/{mode}"

        return parsed._replace(path=path).geturl()

    def _build_remote_headers(
        self,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        custom_headers = metadata.get("headers")
        if isinstance(custom_headers, dict):
            for key, value in custom_headers.items():
                if value is not None:
                    headers[str(key)] = str(value)

        api_key = (
            payload.get("api_key") or metadata.get("api_key") or metadata.get("langserve_api_key")
        )

        if api_key and "Authorization" not in headers and "X-API-Key" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"

        bearer = metadata.get("bearer_token")
        if bearer and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {bearer}"

        traceparent = self._validated_traceparent(payload)
        if traceparent:
            headers["traceparent"] = traceparent

        return headers

    # ------------------------------------------------------------------
    # Output normalization
    # ------------------------------------------------------------------

    def _extract_langserve_output(self, response: Any) -> Any:
        """
        Unwrap canonical LangServe response envelopes while preserving
        structured application output.
        """
        if isinstance(response, dict):
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
        """
        Normalize structured or textual output into an AgentV action.
        """
        if isinstance(output, dict):
            return DualNormalizationHub.normalize(
                output,
                status_code,
            )

        text = self._extract_text(output)

        if not text:
            raise ValueError("LangChain execution completed without a usable output.")

        return DualNormalizationHub.normalize_text(text)

    def _extract_text(self, value: Any) -> str:
        """Extract textual content without discarding structured output."""
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

        if isinstance(value, Mapping):
            # Prefer canonical textual fields.
            for key in (
                "content",
                "text",
                "output",
                "message",
                "answer",
                "result",
            ):
                if key in value:
                    extracted = self._extract_text(value[key])
                    if extracted:
                        return extracted

            # Common LangChain message representation.
            if "content_blocks" in value:
                return self._extract_text(value["content_blocks"])

            return ""

        if isinstance(value, (list, tuple)):
            parts = [self._extract_text(item) for item in value if self._extract_text(item)]
            return "".join(parts)

        content = getattr(value, "content", None)
        if content is not None:
            return self._extract_text(content)

        text_attr = getattr(value, "text", None)
        if callable(text_attr):
            try:
                return self._extract_text(text_attr())
            except Exception:
                pass

        if text_attr is not None:
            return self._extract_text(text_attr)

        return str(value)

    def _to_jsonable(self, value: Any) -> Any:
        """
        Convert common LangChain/Pydantic objects into deterministic,
        JSON-compatible evidence without stringifying structured results.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

        if isinstance(value, Mapping):
            return {str(key): self._to_jsonable(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [self._to_jsonable(item) for item in value]

        model_dump = getattr(value, "model_dump", None)
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

        dict_method = getattr(value, "dict", None)
        if callable(dict_method):
            try:
                return self._to_jsonable(dict_method())
            except Exception:
                pass

        content = getattr(value, "content", None)
        if content is not None:
            result: dict[str, Any] = {
                "content": self._to_jsonable(content),
            }

            response_metadata = getattr(value, "response_metadata", None)
            if response_metadata:
                result["response_metadata"] = self._to_jsonable(response_metadata)

            usage_metadata = getattr(value, "usage_metadata", None)
            if usage_metadata:
                result["usage_metadata"] = self._to_jsonable(usage_metadata)

            tool_calls = getattr(value, "tool_calls", None)
            if tool_calls:
                result["tool_calls"] = self._to_jsonable(tool_calls)

            additional_kwargs = getattr(value, "additional_kwargs", None)
            if additional_kwargs:
                result["additional_kwargs"] = self._to_jsonable(additional_kwargs)

            return result

        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _read_json_or_text(self, response: Any) -> Any:
        content_type = str(response.headers.get("Content-Type", "")).lower()

        if "json" in content_type:
            try:
                return await response.json()
            except Exception:
                pass

        text = await response.text()
        if not text:
            return {}

        return self._decode_json_if_possible(text)

    def _decode_json_if_possible(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    def _raise_http_error(
        self,
        status_code: int,
        response_data: Any,
    ) -> None:
        if isinstance(response_data, dict):
            detail = (
                response_data.get("detail")
                or response_data.get("message")
                or response_data.get("error")
            )
        else:
            detail = response_data

        detail = str(detail or f"HTTP {status_code}")

        # Construct the same typed aiohttp exception family consumed by
        # BaseAdapter.call_with_retry.
        import aiohttp

        raise aiohttp.ClientResponseError(
            request_info=None,
            history=(),
            status=int(status_code),
            message=detail[:1000],
        )

    def _request_timeout(
        self,
        payload: dict[str, Any],
    ):
        import aiohttp

        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        raw_timeout = metadata.get("timeout") or payload.get("timeout")

        if raw_timeout is None:
            return aiohttp.ClientTimeout(total=30.0)

        timeout = float(raw_timeout)

        if timeout <= 0:
            raise ValueError("LangChain adapter timeout must be greater than zero.")

        return aiohttp.ClientTimeout(total=timeout)

    def _retry_enabled(
        self,
        payload: dict[str, Any],
    ) -> bool:
        metadata = payload.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        return bool(metadata.get("retry_idempotent") or payload.get("retry_idempotent"))

    def _validated_traceparent(
        self,
        payload: dict[str, Any],
    ) -> str | None:
        span_context = payload.get("span_context")
        if not isinstance(span_context, dict):
            return None

        traceparent = span_context.get("traceparent")
        if not isinstance(traceparent, str):
            return None

        # Reuse the W3C validation semantics used by the base transport.
        parts = traceparent.split("-")
        if len(parts) != 4:
            return None

        if parts[0] != "00" or len(parts[1]) != 32 or len(parts[2]) != 16 or len(parts[3]) != 2:
            return None

        allowed = "0123456789abcdef"
        if any(ch not in allowed for part in parts[1:] for ch in part):
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
            span_context=payload.get("span_context"),
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
            span_context=payload.get("span_context"),
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
            span_context=payload.get("span_context"),
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

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

    def _langchain_runnable_type(self) -> type | None:
        try:
            from langchain_core.runnables import Runnable

            return Runnable
        except ImportError:
            return None

    def _package_version(self, package_name: str) -> str:
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def _all_textual(self, chunks: list[Any]) -> bool:
        if not chunks:
            return True

        for chunk in chunks:
            if isinstance(chunk, str):
                continue

            text = self._extract_text(chunk)
            if not text:
                return False

        return True


def inspect_is_awaitable(value: Any) -> bool:
    return hasattr(value, "__await__")


def inspect_is_class(value: Any) -> bool:
    try:
        return isinstance(value, type)
    except Exception:
        return False


async def adapter(
    payload: dict[str, Any],
    endpoint: str | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Compatibility wrapper for module-level adapter discovery.

    Adapter discovery expects a callable named ``adapter`` in the module.
    """
    plugin = LangChainAdapterPlugin()

    merged_payload = dict(payload or {})

    # Preserve dispatcher-provided keyword context without modifying the
    # canonical wire payload contract.
    if kwargs:
        metadata = merged_payload.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}

        for key in (
            "langserve_url",
            "chain_path",
            "runnable",
            "config",
            "headers",
        ):
            if key in kwargs and key not in metadata:
                metadata[key] = kwargs[key]

        merged_payload["metadata"] = metadata

    return await plugin.execute_langchain_query(
        merged_payload,
        endpoint=endpoint,
    )
