# eval_runner/adapters/crewai.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import math
import re
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)


class CrewAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Native CrewAI adapter.

    Design guarantees:
      - Executes only a real CrewAI Crew.
      - Requires an explicit native Crew binding.
      - Refuses arbitrary remote endpoints because CrewAI does not define a
        generic remote execution protocol.
      - Prefers Crew.akickoff(), which is CrewAI's native async execution API.
      - Falls back to thread-based execution only when native async execution
        is unavailable.
      - Does not retry CrewAI execution because workflows may perform
        non-idempotent side effects.
      - Uses CrewAI's event bus directly without scoped_handlers(), avoiding
        global handler removal/replacement during concurrent executions.
      - Filters telemetry to the bound Crew to prevent cross-crew event
        contamination.
      - Flushes pending CrewAI event handlers before unregistering them.
      - Preserves structured CrewOutput evidence and token usage.
      - Fails closed when a configured timeout cannot be safely enforced.
    """

    PROTOCOL = "v1"

    def __init__(self, session_pool: Any | None = None):
        BaseAdapter.__init__(
            self,
            name="crewai",
            session_pool=session_pool,
        )

    def on_discover_adapters(self, registry: Any) -> None:
        """Register canonical CrewAI adapter protocols."""
        registry.register("crewai", self.execute_crewai_task)
        registry.register("crewai:v1", self.execute_crewai_task)

    async def execute_crewai_task(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute a real CrewAI Crew.

        Supported binding forms:

          payload["metadata"]["crew"]
              A live crewai.Crew instance.

          payload["metadata"]["crew_path"]
              "module.submodule:attribute"

        The attribute may be:
          - a Crew instance
          - a Crew subclass
          - a callable returning a Crew instance

        Optional:
          payload["inputs"] / payload["input"]
          payload["task_description"]
          payload["messages"]
          payload["task"]
          payload["timeout"]
          payload["task_id"]
          payload["metadata"]["execution_mode"]
        """
        payload = payload if isinstance(payload, dict) else {}

        task_id = str(
            payload.get("task_id")
            or payload.get("run_id")
            or payload.get("execution_id")
            or "default_task"
        )

        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        execution_mode = str(metadata.get("execution_mode") or "live").strip().lower()

        span_context = payload.get("span_context")

        if execution_mode in {
            "simulated",
            "simulation",
            "mock",
            "dry_run",
        }:
            return self._reject_simulation(task_id, execution_mode)

        if endpoint and str(endpoint).strip():
            return self._error_result(
                task_id=task_id,
                message=(
                    "CrewAI adapter received a remote endpoint, but CrewAI does not "
                    "define a generic remote execution protocol. Bind a native CrewAI "
                    "Crew with metadata.crew or metadata.crew_path, or use the "
                    "HTTP/OpenAPI adapter."
                ),
                mode="failed",
            )

        try:
            crewai = importlib.import_module("crewai")
            crew_cls = getattr(crewai, "Crew", None)

            if crew_cls is None:
                raise RuntimeError("Installed CrewAI package does not expose crewai.Crew.")

            version = str(
                getattr(crewai, "__version__", None)
                or getattr(crewai, "VERSION", None)
                or "unknown"
            )

            crew = self._resolve_crew(
                metadata=metadata,
                crew_cls=crew_cls,
            )

            inputs = self._build_inputs(payload)
            timeout = self._resolve_timeout(payload)

            execution_method = self._select_execution_method(
                crew,
                timeout=timeout,
            )

            telemetry = _CrewAITelemetry(
                crew=crew,
                task_id=task_id,
                crew_path=self._crew_binding_label(metadata, crew),
                span_context=span_context,
            )

            started = False

            try:
                emit(
                    CoreEvents.CHAIN_START,
                    {
                        "adapter": "crewai",
                        "framework": "crewai",
                        "protocol": self.PROTOCOL,
                        "task_id": task_id,
                        "crew": telemetry.crew_label,
                        "version": version,
                        "execution_method": execution_method,
                        "input_keys": sorted(str(key) for key in inputs.keys()),
                    },
                    span_context=span_context,
                )

                started = True

                result = await telemetry.execute(
                    crew=crew,
                    inputs=inputs,
                    timeout=timeout,
                    execution_method=execution_method,
                )

            except asyncio.CancelledError:
                emit(
                    CoreEvents.ERROR,
                    {
                        "adapter": "crewai",
                        "framework": "crewai",
                        "protocol": self.PROTOCOL,
                        "task_id": task_id,
                        "message": "CrewAI execution cancelled.",
                    },
                    span_context=span_context,
                )
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
                        "task_id": task_id,
                        "tokens": usage.get("total_tokens"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                    },
                    span_context=span_context,
                )

            emit(
                CoreEvents.CHAIN_END,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "crew": telemetry.crew_label,
                    "version": version,
                    "execution_method": execution_method,
                    "output_length": len(output_text),
                    "started": started,
                    "telemetry": telemetry.summary(),
                },
                span_context=span_context,
            )

            return {
                "status": "success",
                "output": output_text,
                "action": action,
                "metadata": {
                    "framework": "crewai",
                    "version": version,
                    "protocol": self.PROTOCOL,
                    "mode": "live",
                    "task_id": task_id,
                    "execution_method": execution_method,
                    "timeout_seconds": timeout,
                    "timeout_enforced": execution_method == "native_async",
                    "crew_binding": telemetry.crew_label,
                    "crew_id": _safe_scalar(getattr(crew, "id", None)),
                    "crew_name": _safe_scalar(getattr(crew, "name", None)),
                    "crew_output": evidence,
                    "telemetry": telemetry.summary(),
                },
            }

        except asyncio.CancelledError:
            raise

        except ImportError as exc:
            message = f"CrewAI SDK unavailable: {_safe_error_text(exc)}"

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "message": message,
                },
                span_context=span_context,
            )

            return self._error_result(
                task_id=task_id,
                message=message,
                mode="failed",
            )

        except TimeoutError as exc:
            message = _safe_error_text(exc) or "CrewAI execution timed out."

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "message": message,
                },
                span_context=span_context,
            )

            return self._error_result(
                task_id=task_id,
                message=message,
                mode="timeout",
            )

        except Exception as exc:
            message = f"CrewAI execution failed: {_safe_error_text(exc) or type(exc).__name__}"

            logger.error(
                "CrewAI execution failed for task_id=%s (%s)",
                task_id,
                type(exc).__name__,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )

            emit(
                CoreEvents.ERROR,
                {
                    "adapter": "crewai",
                    "framework": "crewai",
                    "protocol": self.PROTOCOL,
                    "task_id": task_id,
                    "message": message,
                    "error_type": (f"{type(exc).__module__}:{type(exc).__qualname__}"),
                },
                span_context=span_context,
            )

            return self._error_result(
                task_id=task_id,
                message=message,
                mode="failed",
                error_type=(f"{type(exc).__module__}:{type(exc).__qualname__}"),
            )

    @staticmethod
    def _error_result(
        task_id: str,
        message: str,
        mode: str,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "framework": "crewai",
            "protocol": CrewAIAdapterPlugin.PROTOCOL,
            "task_id": task_id,
            "mode": mode,
            "certifiable": False,
        }

        if error_type:
            metadata["error_type"] = error_type

        return {
            "status": "error",
            "action": "error",
            "message": message,
            "metadata": metadata,
        }

    @staticmethod
    def _resolve_timeout(payload: dict[str, Any]) -> float | None:
        """
        Resolve a positive finite execution timeout.

        A non-positive, NaN, or infinite timeout is treated as unset rather
        than passed into asyncio.
        """
        raw = payload.get("timeout")

        if raw is None:
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                raw = metadata.get("timeout")

        if raw is None:
            return None

        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid CrewAI timeout value: {raw!r}.") from None

        if not math.isfinite(timeout):
            raise ValueError("CrewAI timeout must be a finite number of seconds.")

        if timeout <= 0:
            return None

        return timeout

    @staticmethod
    def _resolve_crew(
        metadata: dict[str, Any],
        crew_cls: type,
    ) -> Any:
        """
        Resolve a real Crew instance.

        Direct object binding takes precedence over module-path resolution.
        """
        direct_crew = metadata.get("crew")

        if direct_crew is not None:
            if isinstance(direct_crew, crew_cls):
                return direct_crew

            raise TypeError("metadata.crew must be an instance of crewai.Crew.")

        crew_path = metadata.get("crew_path")

        if not isinstance(crew_path, str) or not crew_path.strip():
            raise ValueError(
                "Missing metadata.crew or metadata.crew_path. "
                "A live CrewAI evaluation must bind an actual crewai.Crew."
            )

        return CrewAIAdapterPlugin._resolve_crew_path(
            crew_path=crew_path.strip(),
            crew_cls=crew_cls,
        )

    @staticmethod
    def _resolve_crew_path(
        crew_path: str,
        crew_cls: type,
    ) -> Any:
        """
        Resolve module:attribute binding without fabricating execution.

        Examples:
            myapp.crews:research_crew
            myapp.crews:ResearchCrew
            myapp.crews:build_crew
        """
        if ":" not in crew_path:
            raise ValueError("metadata.crew_path must use 'module.submodule:attribute' syntax.")

        module_name, attr_path = crew_path.split(":", 1)

        module_name = module_name.strip()
        attr_path = attr_path.strip()

        if not module_name or not attr_path:
            raise ValueError("metadata.crew_path must use 'module.submodule:attribute' syntax.")

        module = importlib.import_module(module_name)

        target: Any = module

        for attribute in attr_path.split("."):
            attribute = attribute.strip()

            if not attribute:
                raise ValueError(f"Invalid CrewAI binding '{crew_path}'.")

            try:
                target = getattr(target, attribute)
            except AttributeError as exc:
                raise AttributeError(f"CrewAI binding '{crew_path}' does not exist.") from exc

        if isinstance(target, crew_cls):
            return target

        if inspect.isclass(target) and issubclass(target, crew_cls):
            return target()

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
            f"{type(target).__name__}, expected crewai.Crew, "
            "a Crew subclass, or a factory returning Crew."
        )

    @staticmethod
    def _crew_binding_label(
        metadata: dict[str, Any],
        crew: Any,
    ) -> str:
        crew_path = metadata.get("crew_path")

        if isinstance(crew_path, str) and crew_path.strip():
            return crew_path.strip()

        name = getattr(crew, "name", None)
        crew_id = getattr(crew, "id", None)

        if name:
            if crew_id:
                return f"{name}:{crew_id}"
            return str(name)

        if crew_id:
            return str(crew_id)

        return f"{type(crew).__module__}:{type(crew).__qualname__}"

    @staticmethod
    def _build_inputs(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build the exact dictionary passed to Crew.kickoff/akickoff.

        Explicit inputs are preserved. Generic harness fields are added only
        when present and do not overwrite explicit values.
        """
        raw_inputs = payload.get("inputs")

        if raw_inputs is None:
            raw_inputs = payload.get("input")

        if raw_inputs is None:
            inputs: dict[str, Any] = {}
        elif isinstance(raw_inputs, dict):
            inputs = dict(raw_inputs)
        else:
            inputs = {"input": raw_inputs}

        task_description = payload.get("task_description")
        if task_description is not None:
            inputs.setdefault(
                "task_description",
                task_description,
            )

        messages = payload.get("messages")
        if messages is not None:
            inputs.setdefault("messages", messages)

        task = payload.get("task")
        if task is not None:
            inputs.setdefault("task", task)

        return inputs

    @staticmethod
    def _select_execution_method(
        crew: Any,
        timeout: float | None,
    ) -> str:
        """
        Select the strongest available native execution path.

        A configured timeout is only accepted when CrewAI exposes native async
        execution. Cancelling a thread-backed kickoff cannot safely terminate
        the underlying synchronous Crew execution, which would violate the
        verifier's execution boundary.
        """
        akickoff = getattr(crew, "akickoff", None)

        if callable(akickoff):
            return "native_async"

        kickoff_async = getattr(crew, "kickoff_async", None)

        if callable(kickoff_async):
            if timeout is not None:
                raise RuntimeError(
                    "Configured CrewAI timeout cannot be safely enforced because "
                    "this CrewAI version exposes only thread-backed "
                    "kickoff_async(). Native akickoff() is required for "
                    "bounded execution."
                )

            return "thread_async"

        kickoff = getattr(crew, "kickoff", None)

        if callable(kickoff):
            if timeout is not None:
                raise RuntimeError(
                    "Configured CrewAI timeout cannot be safely enforced because "
                    "this CrewAI version exposes only synchronous kickoff(). "
                    "Native akickoff() is required for bounded execution."
                )

            return "thread_sync"

        raise TypeError(
            "Resolved CrewAI object does not expose akickoff(), kickoff_async(), or kickoff()."
        )

    @staticmethod
    def _serialize_crew_output(
        result: Any,
    ) -> dict[str, Any]:
        """
        Preserve structured CrewOutput evidence without relying on
        CrewOutput.json(), which is not guaranteed to succeed for all
        output combinations.
        """
        tasks_output = getattr(result, "tasks_output", None)

        serialized_tasks: list[dict[str, Any]] = []

        if tasks_output is not None:
            try:
                iterator = iter(tasks_output)
            except TypeError:
                iterator = iter(())

            for task_output in iterator:
                serialized_tasks.append(
                    {
                        "description": _safe_scalar(
                            getattr(
                                task_output,
                                "description",
                                None,
                            )
                        ),
                        "raw": _safe_scalar(
                            getattr(
                                task_output,
                                "raw",
                                None,
                            )
                        ),
                        "agent": _safe_scalar(
                            getattr(
                                task_output,
                                "agent",
                                None,
                            )
                        ),
                        "output_format": _safe_scalar(
                            getattr(
                                task_output,
                                "output_format",
                                None,
                            )
                        ),
                        "json_dict": _safe_jsonable(
                            getattr(
                                task_output,
                                "json_dict",
                                None,
                            )
                        ),
                        "pydantic": _safe_jsonable(
                            getattr(
                                task_output,
                                "pydantic",
                                None,
                            )
                        ),
                    }
                )

        token_usage = _serialize_usage(getattr(result, "token_usage", None))

        return {
            "type": type(result).__name__,
            "raw": _safe_scalar(getattr(result, "raw", None)),
            "pydantic": _safe_jsonable(getattr(result, "pydantic", None)),
            "json_dict": _safe_jsonable(getattr(result, "json_dict", None)),
            "tasks_output": serialized_tasks,
            "token_usage": token_usage,
        }

    @staticmethod
    def _extract_output_text(
        evidence: dict[str, Any],
    ) -> str:
        raw = evidence.get("raw")

        if isinstance(raw, str) and raw.strip():
            return raw.strip()

        for field in (
            "json_dict",
            "pydantic",
        ):
            value = evidence.get(field)

            if value is not None:
                text = _stringify_jsonable(value)

                if text:
                    return text

        tasks = evidence.get("tasks_output") or []

        for task_output in reversed(tasks):
            task_raw = task_output.get("raw")

            if isinstance(task_raw, str) and task_raw.strip():
                return task_raw.strip()

            for field in ("json_dict", "pydantic"):
                value = task_output.get(field)

                if value is not None:
                    text = _stringify_jsonable(value)

                    if text:
                        return text

        return ""

    @staticmethod
    def _reject_simulation(
        task_id: str,
        mode: str,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "action": "error",
            "message": (
                f"CrewAI adapter does not support synthetic execution mode "
                f"'{mode}'. Use the explicit simulation/reference-agent "
                "pathway outside the native CrewAI adapter."
            ),
            "metadata": {
                "framework": "crewai",
                "protocol": CrewAIAdapterPlugin.PROTOCOL,
                "task_id": task_id,
                "mode": "rejected_simulation",
                "certifiable": False,
            },
        }


class _CrewAITelemetry:
    """
    Per-execution CrewAI event telemetry.

    Deliberately avoids CrewAI's scoped_handlers() because that context manager
    temporarily removes existing global handlers while it is active. That is
    unsafe for concurrent enterprise workloads.

    Instead, handlers are registered directly and removed explicitly after the
    execution, while every event is filtered to the bound Crew.
    """

    _EVENT_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "crewai.events.types.crew_events",
            (
                "CrewKickoffStartedEvent",
                "CrewKickoffCompletedEvent",
                "CrewKickoffFailedEvent",
            ),
        ),
        (
            "crewai.events.types.agent_events",
            (
                "AgentExecutionStartedEvent",
                "AgentExecutionCompletedEvent",
                "AgentExecutionErrorEvent",
            ),
        ),
        (
            "crewai.events.types.task_events",
            (
                "TaskStartedEvent",
                "TaskCompletedEvent",
                "TaskFailedEvent",
            ),
        ),
        (
            "crewai.events.types.tool_usage_events",
            (
                "ToolUsageStartedEvent",
                "ToolUsageFinishedEvent",
                "ToolUsageErrorEvent",
                "ToolFailureDetectedEvent",
                "ToolValidateInputErrorEvent",
                "ToolSelectionErrorEvent",
            ),
        ),
        (
            "crewai.events.types.llm_events",
            (
                "LLMCallStartedEvent",
                "LLMCallCompletedEvent",
                "LLMCallFailedEvent",
            ),
        ),
    )

    def __init__(
        self,
        crew: Any,
        task_id: str,
        crew_path: str,
        span_context: dict[str, Any] | None = None,
    ):
        self.crew = crew
        self.task_id = task_id
        self.crew_label = crew_path
        self.span_context = span_context

        self._handlers: list[tuple[type[Any], Any]] = []

        self._counts: dict[str, int] = {}
        self._registered = False
        self._closed = False

        self._initialize()

    def _initialize(self) -> None:
        try:
            event_bus_module = importlib.import_module("crewai.events.event_bus")
            event_bus = getattr(
                event_bus_module,
                "crewai_event_bus",
                None,
            )

            if event_bus is None:
                return

        except ImportError:
            return

        register_handler = getattr(
            event_bus,
            "register_handler",
            None,
        )

        if not callable(register_handler):
            return

        for module_name, event_names in self._EVENT_SOURCES:
            try:
                events_module = importlib.import_module(module_name)
            except ImportError:
                continue

            for event_name in event_names:
                event_cls = getattr(
                    events_module,
                    event_name,
                    None,
                )

                if event_cls is None:
                    continue

                handler = self._make_handler(event_name)

                try:
                    register_handler(
                        event_cls,
                        handler,
                    )
                except Exception:
                    logger.debug(
                        "Failed to register CrewAI telemetry handler for %s",
                        event_name,
                        exc_info=True,
                    )
                    continue

                self._handlers.append(
                    (
                        event_cls,
                        handler,
                    )
                )

        self._registered = bool(self._handlers)

    def _make_handler(
        self,
        event_name: str,
    ):
        def handler(
            source: Any,
            event: Any,
        ) -> None:
            if not self._belongs_to_crew(
                source,
                event,
            ):
                return

            event_key = event_name.removesuffix("Event")

            self._counts[event_key] = self._counts.get(event_key, 0) + 1

            data: dict[str, Any] = {
                "adapter": "crewai",
                "framework": "crewai",
                "task_id": self.task_id,
                "crew": self.crew_label,
                "event": event_key,
            }

            self._populate_event_data(
                event_name=event_name,
                event=event,
                data=data,
            )

            emit(
                CoreEvents.ADAPTER_DEBUG,
                data,
                span_context=self.span_context,
            )

        return handler

    def _populate_event_data(
        self,
        event_name: str,
        event: Any,
        data: dict[str, Any],
    ) -> None:
        if event_name.startswith("CrewKickoff"):
            crew = getattr(
                event,
                "crew",
                None,
            )

            data.update(
                {
                    "crew_name": _safe_scalar(
                        getattr(
                            event,
                            "crew_name",
                            None,
                        )
                    ),
                    "crew_id": _safe_scalar(
                        getattr(
                            crew,
                            "id",
                            None,
                        )
                    ),
                }
            )

            if event_name == "CrewKickoffCompletedEvent":
                data["output_length"] = _output_length(
                    getattr(
                        event,
                        "output",
                        None,
                    )
                )

            elif event_name == "CrewKickoffFailedEvent":
                data["error"] = _safe_error_value(
                    getattr(
                        event,
                        "error",
                        None,
                    )
                )

            return

        if event_name.startswith("AgentExecution"):
            agent = getattr(
                event,
                "agent",
                None,
            )

            data.update(
                {
                    "agent_id": _safe_scalar(
                        getattr(
                            agent,
                            "id",
                            None,
                        )
                    ),
                    "agent_role": _safe_scalar(
                        getattr(
                            agent,
                            "role",
                            None,
                        )
                    ),
                }
            )

            if event_name == "AgentExecutionCompletedEvent":
                data["output_length"] = _output_length(
                    getattr(
                        event,
                        "output",
                        None,
                    )
                )

            elif event_name == "AgentExecutionErrorEvent":
                data["error"] = _safe_error_value(
                    getattr(
                        event,
                        "error",
                        None,
                    )
                )

            return

        if event_name.startswith("Task"):
            task = getattr(
                event,
                "task",
                None,
            )

            data.update(
                {
                    "task_event_id": _safe_scalar(
                        getattr(
                            task,
                            "id",
                            None,
                        )
                    ),
                    "task_name": _safe_scalar(
                        getattr(
                            task,
                            "name",
                            None,
                        )
                    ),
                }
            )

            if event_name == "TaskCompletedEvent":
                data["output_length"] = _output_length(
                    getattr(
                        event,
                        "output",
                        None,
                    )
                )

            elif event_name == "TaskFailedEvent":
                data["error"] = _safe_error_value(
                    getattr(
                        event,
                        "error",
                        None,
                    )
                )

            return

        if event_name.startswith("Tool"):
            tool = getattr(
                event,
                "tool_name",
                None,
            )

            if tool is None:
                tool_object = getattr(
                    event,
                    "tool",
                    None,
                )

                tool = getattr(
                    tool_object,
                    "name",
                    None,
                )

            data["tool"] = _safe_scalar(tool)

            if event_name in {
                "ToolUsageErrorEvent",
                "ToolValidateInputErrorEvent",
                "ToolSelectionErrorEvent",
            }:
                data["error"] = _safe_error_value(
                    getattr(
                        event,
                        "error",
                        None,
                    )
                )

            if event_name == "ToolFailureDetectedEvent":
                data["failure"] = _safe_jsonable(
                    getattr(
                        event,
                        "failure",
                        None,
                    )
                )

            return

        if event_name.startswith("LLMCall"):
            data["model"] = _safe_scalar(
                getattr(
                    event,
                    "model",
                    None,
                )
            )

            data["call_id"] = _safe_scalar(
                getattr(
                    event,
                    "call_id",
                    None,
                )
            )

            if event_name == "LLMCallCompletedEvent":
                data["usage"] = _safe_jsonable(
                    getattr(
                        event,
                        "usage",
                        None,
                    )
                )

            elif event_name == "LLMCallFailedEvent":
                data["error"] = _safe_error_value(
                    getattr(
                        event,
                        "error",
                        None,
                    )
                )

    def _belongs_to_crew(
        self,
        source: Any,
        event: Any,
    ) -> bool:
        """
        Determine whether an event belongs to this Crew instance.

        CrewAI events do not expose a single uniform crew reference across all
        event types, so the association is derived from the event's crew,
        agent, task, and source relationships.
        """
        if source is self.crew:
            return True

        if _same_entity(
            getattr(event, "crew", None),
            self.crew,
        ):
            return True

        if _same_entity(
            source,
            self.crew,
        ):
            return True

        for candidate in (
            getattr(event, "agent", None),
            getattr(event, "task", None),
            getattr(event, "from_agent", None),
            getattr(event, "from_task", None),
        ):
            if candidate is None:
                continue

            if _same_entity(
                candidate,
                self.crew,
            ):
                return True

            if _same_entity(
                getattr(candidate, "crew", None),
                self.crew,
            ):
                return True

            nested_agent = getattr(
                candidate,
                "agent",
                None,
            )

            if _same_entity(
                getattr(
                    nested_agent,
                    "crew",
                    None,
                ),
                self.crew,
            ):
                return True

        return False

    async def execute(
        self,
        crew: Any,
        inputs: dict[str, Any],
        timeout: float | None,
        execution_method: str,
    ) -> Any:
        if execution_method == "native_async":
            return await self._execute_native_async(
                crew=crew,
                inputs=inputs,
                timeout=timeout,
            )

        if execution_method == "thread_async":
            kickoff_async = crew.kickoff_async

            return await kickoff_async(
                inputs=inputs,
            )

        if execution_method == "thread_sync":
            return await asyncio.to_thread(
                crew.kickoff,
                inputs=inputs,
            )

        raise RuntimeError(f"Unsupported CrewAI execution method: {execution_method}")

    @staticmethod
    async def _execute_native_async(
        crew: Any,
        inputs: dict[str, Any],
        timeout: float | None,
    ) -> Any:
        coroutine = crew.akickoff(
            inputs=inputs,
        )

        if not inspect.isawaitable(coroutine):
            raise TypeError("Crew.akickoff() did not return an awaitable result.")

        if timeout is None:
            return await coroutine

        try:
            return await asyncio.wait_for(
                coroutine,
                timeout=timeout,
            )
        except TimeoutError:
            raise TimeoutError(
                f"CrewAI execution exceeded configured timeout of {timeout:.2f}s."
            ) from None

    def summary(self) -> dict[str, Any]:
        return {
            "event_handlers_registered": self._registered,
            "event_handler_count": len(self._handlers),
            "event_counts": dict(self._counts),
        }

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        try:
            event_bus_module = importlib.import_module("crewai.events.event_bus")
            event_bus = getattr(event_bus_module, "crewai_event_bus", None)

            flush = getattr(
                event_bus,
                "flush",
                None,
            )

            if callable(flush):
                try:
                    flush(timeout=2.0)
                except Exception:
                    logger.debug(
                        "CrewAI event-bus flush failed during adapter cleanup.",
                        exc_info=True,
                    )

            off = getattr(
                event_bus,
                "off",
                None,
            )

            if callable(off):
                for event_cls, handler in reversed(self._handlers):
                    try:
                        off(
                            event_cls,
                            handler,
                        )
                    except Exception:
                        logger.debug(
                            "Failed to unregister CrewAI event handler %s.",
                            getattr(
                                event_cls,
                                "__name__",
                                event_cls,
                            ),
                            exc_info=True,
                        )

        except ImportError:
            pass

        finally:
            self._handlers.clear()
            self._registered = False


def _same_entity(
    left: Any,
    right: Any,
) -> bool:
    if left is None or right is None:
        return False

    if left is right:
        return True

    left_id = getattr(left, "id", None)
    right_id = getattr(right, "id", None)

    if left_id is not None and right_id is not None:
        return str(left_id) == str(right_id)

    return False


def _safe_scalar(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [_safe_scalar(item) for item in value]

    return str(value)


def _safe_jsonable(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return {str(key): _safe_jsonable(item) for key, item in value.items()}

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [_safe_jsonable(item) for item in value]

    model_dump = getattr(
        value,
        "model_dump",
        None,
    )

    if callable(model_dump):
        try:
            return _safe_jsonable(model_dump(mode="json"))
        except Exception:
            pass

    dict_method = getattr(
        value,
        "dict",
        None,
    )

    if callable(dict_method):
        try:
            return _safe_jsonable(dict_method())
        except Exception:
            pass

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value)


def _serialize_usage(
    usage: Any,
) -> dict[str, Any]:
    if usage is None:
        return {}

    if isinstance(
        usage,
        dict,
    ):
        return _safe_jsonable(usage)

    model_dump = getattr(
        usage,
        "model_dump",
        None,
    )

    if callable(model_dump):
        try:
            return _safe_jsonable(model_dump(mode="json"))
        except Exception:
            pass

    dict_method = getattr(
        usage,
        "dict",
        None,
    )

    if callable(dict_method):
        try:
            return _safe_jsonable(dict_method())
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
        value = getattr(
            usage,
            field,
            None,
        )

        if value is not None:
            result[field] = _safe_jsonable(value)

    return result


def _stringify_jsonable(
    value: Any,
) -> str:
    import json

    safe = _safe_jsonable(value)

    try:
        return json.dumps(
            safe,
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception:
        return str(safe)


def _safe_error_text(
    exc: BaseException,
    max_length: int = 2000,
) -> str:
    message = str(exc).strip()

    if not message:
        return ""

    message = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        message,
    )

    message = re.sub(
        r"(?i)\b(api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|secret)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )

    message = re.sub(
        r"(?i)\bsk-[A-Za-z0-9_-]{12,}\b",
        "[REDACTED]",
        message,
    )

    if len(message) > max_length:
        return f"{message[: max_length - 3]}..."

    return message


def _safe_error_value(
    value: Any,
) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        BaseException,
    ):
        return _safe_error_text(value)

    return _safe_error_text(RuntimeError(str(value)))


def _output_length(
    value: Any,
) -> int:
    if value is None:
        return 0

    raw = getattr(
        value,
        "raw",
        None,
    )

    if raw is not None:
        return len(str(raw))

    return len(str(value))
