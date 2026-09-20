# eval_runner/adapters/crewai.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)


class CrewAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native CrewAI adapter.

    Execution contract:
      - Requires an explicitly bound CrewAI Crew instance/factory via metadata["crew_path"].
      - Executes real CrewAI work only.
      - Never fabricates successful execution.
      - Prefers native async `akickoff()`, then `kickoff_async()`, then isolates
        synchronous `kickoff()` in a worker thread.
      - Captures CrewAI lifecycle telemetry through the event bus when available.
      - Preserves structured CrewOutput evidence rather than collapsing it to str().
      - Does not retry a completed/partially executed crew because arbitrary CrewAI
        workflows may contain non-idempotent side effects.
    """

    PROTOCOL = "v1"

    def __init__(self):
        BaseAdapter.__init__(self, name="crewai")

    def on_discover_adapters(self, registry: Any):
        """Register canonical CrewAI adapter protocols."""
        registry.register("crewai", self.execute_crewai_task)
        registry.register("crewai:v1", self.execute_crewai_task)

    async def execute_crewai_task(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a real CrewAI Crew.

        Required:
            payload["metadata"]["crew_path"] = "module.submodule:attribute"

        Optional:
            payload["input"] / payload["inputs"]
            payload["task_description"]
            payload["messages"]
            payload["timeout"]
            payload["task_id"]
            payload["metadata"]["execution_mode"]

        `endpoint` is deliberately not treated as a CrewAI-native protocol because
        CrewAI does not define a generic remote Crew HTTP contract.
        """
        task_id = str(payload.get("task_id") or payload.get("run_id") or "default_task")
        metadata = payload.get("metadata") or {}
        execution_mode = str(metadata.get("execution_mode") or "live").lower()

        if execution_mode in {"simulated", "simulation", "mock", "dry_run"}:
            return self._reject_simulation(task_id, execution_mode)

        if endpoint and str(endpoint).strip():
            return {
                "status": "error",
                "action": "error",
                "message": (
                    "CrewAI adapter received a remote endpoint, but CrewAI does not "
                    "define a generic remote execution protocol. Bind a native CrewAI "
                    "Crew with metadata.crew_path or use the HTTP/OpenAPI adapter."
                ),
                "metadata": {
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "mode": "failed",
                },
            }

        crew_path = metadata.get("crew_path")
        if not crew_path:
            return {
                "status": "error",
                "action": "error",
                "message": (
                    "Missing metadata.crew_path. A live CrewAI evaluation must bind "
                    "an actual Crew instance or factory using "
                    "'module.submodule:attribute'."
                ),
                "metadata": {
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "mode": "failed",
                },
            }

        try:
            crewai = importlib.import_module("crewai")
            crew_cls = getattr(crewai, "Crew", None)
            if crew_cls is None:
                raise RuntimeError("Installed CrewAI package does not expose crewai.Crew.")

            version = str(getattr(crewai, "__version__", "unknown"))

            crew = self._resolve_crew(crew_path, crew_cls)
            inputs = self._build_inputs(payload)

            emit(
                CoreEvents.CHAIN_START,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "crew_path": crew_path,
                    "version": version,
                    "input_keys": sorted(str(k) for k in inputs.keys()),
                },
                span_context=payload.get("span_context"),
            )

            telemetry = _CrewAITelemetry(
                task_id=task_id,
                crew_path=str(crew_path),
                span_context=payload.get("span_context"),
            )

            timeout = self._resolve_timeout(payload)

            try:
                result = await telemetry.execute(
                    crew,
                    inputs,
                    timeout=timeout,
                )
            except asyncio.CancelledError:
                emit(
                    CoreEvents.ERROR,
                    {
                        "adapter": "crewai",
                        "task_id": task_id,
                        "message": "CrewAI execution cancelled.",
                    },
                    span_context=payload.get("span_context"),
                )
                raise
            except Exception:
                raise
            finally:
                telemetry.close()

            evidence = self._serialize_crew_output(result)
            output_text = self._extract_output_text(evidence)
            action = DualNormalizationHub.normalize_text(output_text)

            usage = evidence.get("token_usage") or {}
            if usage:
                emit(
                    "metric_update",
                    {
                        "adapter": "crewai",
                        "tokens": usage.get("total_tokens"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                    },
                    span_context=payload.get("span_context"),
                )

            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "crew_path": crew_path,
                    "version": version,
                    "output_length": len(output_text),
                },
                span_context=payload.get("span_context"),
            )

            return {
                "status": "success",
                "output": output_text,
                "action": action,
                "metadata": {
                    "framework": "crewai",
                    "version": version,
                    "crew_path": crew_path,
                    "protocol": self.PROTOCOL,
                    "mode": "live",
                    "task_id": task_id,
                    "crew_output": evidence,
                    "telemetry": telemetry.summary(),
                },
            }

        except asyncio.CancelledError:
            raise
        except ImportError as exc:
            message = f"CrewAI SDK unavailable: {exc}"
            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "crewai",
                    "task_id": task_id,
                    "message": message,
                },
                span_context=payload.get("span_context"),
            )
            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "mode": "failed",
                },
            }
        except Exception as exc:
            message = f"CrewAI execution failed: {exc}"
            logger.exception(message)

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "crewai",
                    "task_id": task_id,
                    "message": message,
                },
                span_context=payload.get("span_context"),
            )

            return {
                "status": "error",
                "action": "error",
                "message": message,
                "metadata": {
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "mode": "failed",
                },
            }

    @staticmethod
    def _resolve_timeout(payload: dict[str, Any]) -> float | None:
        """
        Crew execution is not given an arbitrary global timeout because CrewAI
        workflows commonly exceed 30s. A scenario may explicitly declare one.
        """
        raw = payload.get("timeout")
        if raw is None:
            raw = (payload.get("metadata") or {}).get("timeout")

        if raw is None:
            return None

        timeout = float(raw)
        if timeout <= 0:
            return None
        return timeout

    @staticmethod
    def _resolve_crew(crew_path: str, crew_cls: type) -> Any:
        """Resolve a real Crew instance from module:attribute."""
        if not isinstance(crew_path, str) or ":" not in crew_path:
            raise ValueError("metadata.crew_path must use 'module.submodule:attribute' syntax.")

        module_name, attr_name = crew_path.split(":", 1)
        module_name = module_name.strip()
        attr_name = attr_name.strip()

        if not module_name or not attr_name:
            raise ValueError("metadata.crew_path must use 'module.submodule:attribute' syntax.")

        module = importlib.import_module(module_name)

        try:
            target = getattr(module, attr_name)
        except AttributeError as exc:
            raise AttributeError(f"CrewAI binding '{crew_path}' does not exist.") from exc

        # Direct Crew instance.
        if isinstance(target, crew_cls):
            return target

        # Crew subclass.
        if inspect.isclass(target) and issubclass(target, crew_cls):
            return target()

        # Factory / project helper returning a Crew.
        if callable(target):
            resolved = target()
            if isinstance(resolved, crew_cls):
                return resolved

            raise TypeError(
                f"CrewAI binding '{crew_path}' returned "
                f"{type(resolved).__name__}, expected crewai.Crew."
            )

        raise TypeError(
            f"CrewAI binding '{crew_path}' resolved to "
            f"{type(target).__name__}, expected crewai.Crew or a factory."
        )

    @staticmethod
    def _build_inputs(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Build CrewAI kickoff inputs without leaking harness-internal transport fields.

        CrewAI kickoff accepts a dictionary of template/context inputs. The adapter
        therefore preserves explicit input mappings and converts the engine's generic
        task_description into a deterministic input field.
        """
        raw_inputs = payload.get("inputs", payload.get("input"))

        if raw_inputs is None:
            inputs: dict[str, Any] = {}
        elif isinstance(raw_inputs, dict):
            inputs = dict(raw_inputs)
        else:
            inputs = {"input": raw_inputs}

        task_description = payload.get("task_description")
        if task_description is not None:
            inputs.setdefault("task_description", task_description)

        messages = payload.get("messages")
        if messages is not None:
            inputs.setdefault("messages", messages)

        task = payload.get("task")
        if task is not None:
            inputs.setdefault("task", task)

        return inputs

    @staticmethod
    def _serialize_crew_output(result: Any) -> dict[str, Any]:
        """
        Preserve CrewOutput evidence without relying on CrewOutput.json, which may
        fail for edge cases such as empty task-output collections.
        """
        raw = getattr(result, "raw", None)
        pydantic_value = getattr(result, "pydantic", None)
        json_dict = getattr(result, "json_dict", None)
        tasks_output = getattr(result, "tasks_output", None)
        token_usage = getattr(result, "token_usage", None)

        serialized_tasks: list[dict[str, Any]] = []
        if tasks_output is not None:
            for task_output in tasks_output:
                serialized_tasks.append(
                    {
                        "description": _safe_scalar(getattr(task_output, "description", None)),
                        "raw": _safe_scalar(getattr(task_output, "raw", None)),
                        "agent": _safe_scalar(getattr(task_output, "agent", None)),
                        "output_format": _safe_scalar(getattr(task_output, "output_format", None)),
                        "json_dict": _safe_jsonable(getattr(task_output, "json_dict", None)),
                        "pydantic": _safe_jsonable(getattr(task_output, "pydantic", None)),
                    }
                )

        return {
            "type": type(result).__name__,
            "raw": _safe_scalar(raw),
            "pydantic": _safe_jsonable(pydantic_value),
            "json_dict": _safe_jsonable(json_dict),
            "tasks_output": serialized_tasks,
            "token_usage": _serialize_usage(token_usage),
        }

    @staticmethod
    def _extract_output_text(evidence: dict[str, Any]) -> str:
        raw = evidence.get("raw")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

        json_dict = evidence.get("json_dict")
        if json_dict is not None:
            return _stringify_jsonable(json_dict)

        pydantic_value = evidence.get("pydantic")
        if pydantic_value is not None:
            return _stringify_jsonable(pydantic_value)

        tasks = evidence.get("tasks_output") or []
        if tasks:
            last_raw = tasks[-1].get("raw")
            if isinstance(last_raw, str) and last_raw.strip():
                return last_raw.strip()

        return ""

    @staticmethod
    def _reject_simulation(task_id: str, mode: str) -> dict[str, Any]:
        """Simulation is not a valid live CrewAI execution result."""
        return {
            "status": "error",
            "action": "error",
            "message": (
                f"CrewAI adapter does not support synthetic execution mode '{mode}'. "
                "Use the explicit simulation/reference-agent pathway outside the "
                "native CrewAI adapter."
            ),
            "metadata": {
                "framework": "crewai",
                "protocol": "v1",
                "task_id": task_id,
                "mode": "rejected_simulation",
                "certifiable": False,
            },
        }


class _CrewAITelemetry:
    """
    Scoped CrewAI event-bus telemetry.

    CrewAI exposes a scoped handler context for temporary event subscriptions.
    Handlers capture lifecycle events without modifying the target Crew instance.
    """

    _EVENTS = (
        "CrewKickoffStartedEvent",
        "CrewKickoffCompletedEvent",
        "CrewKickoffFailedEvent",
        "AgentExecutionStartedEvent",
        "AgentExecutionCompletedEvent",
        "AgentExecutionErrorEvent",
        "TaskStartedEvent",
        "TaskCompletedEvent",
        "TaskFailedEvent",
        "ToolUsageStartedEvent",
        "ToolUsageFinishedEvent",
        "ToolUsageErrorEvent",
        "LLMCallStartedEvent",
        "LLMCallCompletedEvent",
        "LLMCallFailedEvent",
    )

    def __init__(
        self,
        task_id: str,
        crew_path: str,
        span_context: dict[str, Any] | None = None,
    ):
        self.task_id = task_id
        self.crew_path = crew_path
        self.span_context = span_context
        self._handlers: list[Any] = []
        self._counts: dict[str, int] = {}
        self._context_manager = None
        self._event_bus = None

        self._initialize()

    def _initialize(self) -> None:
        try:
            events_module = importlib.import_module("crewai.events")
        except ImportError:
            return

        event_bus = getattr(events_module, "crewai_event_bus", None)
        scoped_handlers = getattr(event_bus, "scoped_handlers", None)
        if event_bus is None or not callable(scoped_handlers):
            return

        self._event_bus = event_bus
        self._context_manager = scoped_handlers()

        self._context_manager.__enter__()

        for event_name in self._EVENTS:
            event_cls = getattr(events_module, event_name, None)
            if event_cls is None:
                continue

            decorator_factory = getattr(event_bus, "on", None)
            if not callable(decorator_factory):
                continue

            handler = self._make_handler(event_name)
            decorator_factory(event_cls)(handler)
            self._handlers.append(handler)

    def _make_handler(self, event_name: str):
        def handler(source: Any, event: Any) -> None:
            event_key = event_name.removesuffix("Event")
            self._counts[event_key] = self._counts.get(event_key, 0) + 1

            data = {
                "adapter": "crewai",
                "task_id": self.task_id,
                "crew_path": self.crew_path,
                "event": event_key,
            }

            if event_name == "CrewKickoffStartedEvent":
                data.update(
                    {
                        "crew_name": _safe_scalar(getattr(event, "crew_name", None)),
                    }
                )
            elif event_name == "CrewKickoffCompletedEvent":
                output = getattr(event, "output", None)
                data.update(
                    {
                        "crew_name": _safe_scalar(getattr(event, "crew_name", None)),
                        "output_length": _output_length(output),
                    }
                )
            elif event_name == "CrewKickoffFailedEvent":
                data["error"] = _safe_scalar(
                    getattr(event, "error", None) or getattr(event, "exception", None)
                )
            elif event_name in {
                "AgentExecutionStartedEvent",
                "AgentExecutionCompletedEvent",
                "AgentExecutionErrorEvent",
            }:
                agent = getattr(event, "agent", None)
                data.update(
                    {
                        "agent_role": _safe_scalar(getattr(agent, "role", None)),
                    }
                )
                if event_name == "AgentExecutionCompletedEvent":
                    data["output_length"] = _output_length(getattr(event, "output", None))
                elif event_name == "AgentExecutionErrorEvent":
                    data["error"] = _safe_scalar(
                        getattr(event, "error", None) or getattr(event, "exception", None)
                    )
            elif event_name in {
                "TaskStartedEvent",
                "TaskCompletedEvent",
                "TaskFailedEvent",
            }:
                task = getattr(event, "task", None)
                data.update(
                    {
                        "task_id": _safe_scalar(getattr(task, "id", None)),
                        "task_name": _safe_scalar(getattr(task, "name", None)),
                        "agent_role": _safe_scalar(
                            getattr(getattr(event, "output", None), "agent", None)
                        ),
                    }
                )
                if event_name == "TaskCompletedEvent":
                    data["output_length"] = _output_length(getattr(event, "output", None))
                elif event_name == "TaskFailedEvent":
                    data["error"] = _safe_scalar(
                        getattr(event, "error", None) or getattr(event, "exception", None)
                    )
            elif event_name in {
                "ToolUsageStartedEvent",
                "ToolUsageFinishedEvent",
                "ToolUsageErrorEvent",
            }:
                tool = getattr(event, "tool_name", None)
                if tool is None:
                    tool = getattr(
                        getattr(event, "tool", None),
                        "name",
                        None,
                    )
                data["tool"] = _safe_scalar(tool)

            emit(
                CoreEvents.ADAPTER_DEBUG,
                data,
                span_context=self.span_context,
            )

        return handler

    async def execute(
        self,
        crew: Any,
        inputs: dict[str, Any],
        timeout: float | None = None,
    ) -> Any:
        """
        Execute using the strongest available native CrewAI API.

        Order:
          1. akickoff()        native async
          2. kickoff_async()   compatibility async wrapper
          3. kickoff()        isolated worker thread
        """
        try:
            if hasattr(crew, "akickoff") and callable(crew.akickoff):
                coro = crew.akickoff(inputs=inputs)
            elif hasattr(crew, "kickoff_async") and callable(crew.kickoff_async):
                coro = crew.kickoff_async(inputs=inputs)
            elif hasattr(crew, "kickoff") and callable(crew.kickoff):
                coro = asyncio.to_thread(crew.kickoff, inputs=inputs)
            else:
                raise TypeError(
                    "Resolved object does not expose a supported CrewAI kickoff method."
                )

            if timeout is None:
                return await coro

            return await asyncio.wait_for(coro, timeout=timeout)

        except TimeoutError:
            raise TimeoutError(
                f"CrewAI execution exceeded configured timeout of {timeout:.2f}s."
            ) from None

    def summary(self) -> dict[str, Any]:
        return {
            "event_handlers_registered": bool(self._handlers),
            "event_counts": dict(self._counts),
        }

    def close(self) -> None:
        if self._context_manager is None:
            return

        try:
            self._context_manager.__exit__(None, None, None)
        finally:
            self._context_manager = None
            self._handlers.clear()


def _safe_scalar(value: Any) -> Any:
    """Return only JSON-safe scalar representations for telemetry/evidence."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple, set)):
        return [_safe_scalar(v) for v in list(value)]

    return str(value)


def _safe_jsonable(value: Any) -> Any:
    """Best-effort conversion of CrewAI structured outputs to JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_jsonable(model_dump(mode="json"))
        except Exception:
            pass

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        try:
            return _safe_jsonable(dict_method())
        except Exception:
            pass

    return str(value)


def _serialize_usage(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}

    if isinstance(usage, dict):
        return _safe_jsonable(usage)

    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        try:
            value = model_dump(mode="json")
            return _safe_jsonable(value)
        except Exception:
            pass

    result: dict[str, Any] = {}
    for field in (
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "reasoning_tokens",
        "cache_creation_tokens",
        "successful_requests",
    ):
        value = getattr(usage, field, None)
        if value is not None:
            result[field] = value

    return result


def _stringify_jsonable(value: Any) -> str:
    import json

    safe = _safe_jsonable(value)
    try:
        return json.dumps(safe, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(safe)


def _output_length(value: Any) -> int:
    if value is None:
        return 0

    raw = getattr(value, "raw", None)
    if raw is not None:
        return len(str(raw))

    return len(str(value))
