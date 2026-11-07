from __future__ import annotations

"""
events.py

Centralized event system for OpenCore.
Enables "Flight Recorder" patterns where plugins can subscribe to 
state transitions without modifying the main engine loop.
"""

import logging  # noqa: E402
import re  # noqa: E402
from collections.abc import Callable  # noqa: E402
from datetime import datetime  # noqa: E402
from enum import StrEnum  # noqa: E402
from typing import Any  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

logger = logging.getLogger(__name__)


class EvidenceDeliveryError(RuntimeError):
    """A mandatory evidence consumer did not acknowledge an event."""


def sanitize_payload(data: dict) -> dict:
    """Redacts PII and Secrets from event payload before broadcast.

    Security: Intercepts all outgoing bus payloads with regex-based
    redaction for common secret patterns (Audit Point #2).
    """

    def redact_string(s: str) -> str:
        # JWT tokens
        s = re.sub(r"ey[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]", s)
        # OpenAI / Stripe style keys
        s = re.sub(r"sk-[a-zA-Z0-9]{32,}", "[REDACTED_KEY]", s)
        # AWS Access Key IDs
        s = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", s)
        # GitHub Personal Access Tokens & OAuth tokens
        s = re.sub(r"gh[po]_[a-zA-Z0-9]{36,}", "[REDACTED_GITHUB_TOKEN]", s)
        # Bearer authorization headers
        s = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", s)
        # Format-string injection prevention
        s = s.replace("{", "{{").replace("}", "}}")
        return s

    def recursive_sanitize(obj):
        if isinstance(obj, str):
            return redact_string(obj)
        elif isinstance(obj, dict):
            return {k: recursive_sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [recursive_sanitize(v) for v in obj]
        elif obj is None or isinstance(obj, (int, float, bool)):
            return obj
        else:
            # Handle non-serializable objects (e.g. functions, custom classes)
            return str(obj)

    return recursive_sanitize(data)


class Event:
    """Base event structure."""

    def __init__(self, name: str, data: dict[str, Any], span_context: dict[str, Any] | None = None):
        self.name = name
        self.data = data
        self.span_context = span_context
        self.timestamp = datetime.now().astimezone().isoformat()

    def to_dict(self) -> dict[str, Any]:
        base = {"event": self.name, "timestamp": self.timestamp, **self.data}
        if self.span_context:
            base["span_context"] = self.span_context
        return base


def _execute_subscriber_with_context(sub, event, otel_ctx):
    token = None
    if otel_ctx is not None:
        try:
            from opentelemetry import context as otel_context

            token = otel_context.attach(otel_ctx)
        except Exception as _e:
            logger.debug("OTel attach skipped: %s", _e, exc_info=True)
    try:
        import asyncio

        if asyncio.iscoroutinefunction(sub):
            asyncio.run(sub(event))
        else:
            sub(event)
    except Exception as e:
        logging.getLogger(__name__).debug(
            "Failure in _execute_subscriber_with_context", exc_info=True
        )
        print(f"   [Events] Error in subscriber callback: {e}")
    finally:
        if token is not None:
            try:
                from opentelemetry import context as otel_context

                otel_context.detach(token)
            except Exception as _e:
                logger.debug("OTel detach skipped: %s", _e, exc_info=True)


class EventEmitter:
    """
    Centralized event bus.
    Now supports instantiation for session-scoped isolation.
    """

    _executor = None

    @classmethod
    def get_executor(cls):
        import concurrent.futures

        if cls._executor is None:
            cls._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="agentv_events"
            )
        return cls._executor

    def __init__(self, run_id: str | None = None, async_mode: bool | None = None):
        import os
        import threading

        self.run_id = run_id
        self._subscribers: list[Callable[[Event], None]] = []
        self._keyed_subscribers: dict[str, Callable[[Event], None]] = {}
        if async_mode is None:
            # Check env variable first; default to False for backward-compatibility in tests
            self.async_mode = os.getenv("ASYNC_EVENTS", "false").lower() == "true"
        else:
            self.async_mode = async_mode
        self._pending_futures = []
        self._lock = threading.Lock()
        self._required_subscribers = set()
        self._delivery_failures = {}
        self._emitted_counts = {}
        self._acknowledged_counts = {}
        self._inflight_counts = {}
        self._closed_runs = set()
        self._emission_commitments = {}
        self._baseline_counts = {}

    def subscribe(
        self, subscriber: Callable[[Event], None], key: str | None = None, *, required: bool = False
    ):
        """Register a new subscriber (e.g., a logging plugin)."""
        if key:
            self._keyed_subscribers[key] = subscriber
        elif subscriber not in self._subscribers:
            self._subscribers.append(subscriber)
        if required:
            import inspect

            if inspect.iscoroutinefunction(subscriber):
                self.unsubscribe(subscriber if key is None else key)
                raise TypeError("Mandatory evidence subscribers must acknowledge synchronously")
            self._required_subscribers.add(subscriber)

    def unsubscribe(self, subscriber: Callable[[Event], None] | str):
        """Unregister an existing subscriber or key."""
        if isinstance(subscriber, str):
            if subscriber in self._keyed_subscribers:
                del self._keyed_subscribers[subscriber]
        elif subscriber in self._subscribers:
            self._subscribers.remove(subscriber)
        self._required_subscribers.intersection_update(
            self._subscribers + list(self._keyed_subscribers.values())
        )

    def reset(self):
        """Clear all subscribers and notify them to cleanup if possible."""
        self.flush()
        all_subs = self._subscribers + list(self._keyed_subscribers.values())
        for sub in all_subs:
            try:
                # If subscriber is a bound method of a class with cleanup logic
                if hasattr(sub, "__self__") and hasattr(sub.__self__, "close_all"):
                    sub.__self__.close_all()
            except Exception as e:
                # Forensic Transparency: Log cleanup failures for auditing
                logging.getLogger(__name__).debug("Failure in EventEmitter.reset", exc_info=True)
                print(f"   [Events] Warning: Subscriber cleanup failure: {e}")
        self._subscribers = []
        self._keyed_subscribers = {}
        self._required_subscribers.clear()
        self._delivery_failures.clear()
        self._emitted_counts.clear()
        self._acknowledged_counts.clear()
        self._inflight_counts.clear()
        self._closed_runs.clear()
        self._emission_commitments.clear()
        self._baseline_counts.clear()

    def finalize_capture(self, run_id, run_store, context=None, *, complete=True):
        """Durably acknowledge a complete provider stream before certification."""
        import hashlib
        import json

        with self._lock:
            expected = self._emitted_counts.get(run_id, 0)
            if (
                run_id in self._delivery_failures
                or self._inflight_counts.get(run_id, 0)
                or expected == 0
                or self._acknowledged_counts.get(run_id, 0) != expected
            ):
                raise EvidenceDeliveryError(
                    "IncompleteEvidenceCapture: events lack durable acknowledgement"
                )
            self._closed_runs.add(run_id)
        try:
            raw = run_store.get_trace_bytes(run_id, context=context)
            if not isinstance(raw, bytes):
                raise ValueError("Provider did not return exact trace bytes")
            records = [
                json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
            ]
            if len(records) != expected or any(
                type(row.get("_seq")) is not int or row["_seq"] != index
                for index, row in enumerate(records, 1)
            ):
                raise ValueError("Persisted event count or sequence differs from emitted events")
            from agentv_runtime.canonical import canonical_json_encode

            baseline = self._baseline_counts.get(run_id, 0)
            commitments = self._emission_commitments.get(run_id, [])
            if len(commitments) != expected - baseline:
                raise ValueError("Emission commitments are incomplete")
            for row, (keys, digest) in zip(records[baseline:], commitments, strict=True):
                if (
                    hashlib.sha3_256(
                        canonical_json_encode({key: row[key] for key in keys})
                    ).hexdigest()
                    != digest
                ):
                    raise ValueError("Persisted event content differs from emitted evidence")
            if complete and records[-1].get("event") not in {
                "run_end",
                "end",
                "evaluator_finalization",
            }:
                raise ValueError("Terminal execution event was not persisted")
            receipt = {
                "complete": complete,
                "resumable": not complete,
                "event_count": expected,
                "terminal_seq": expected,
                "trace_hash": "sha3_256:" + hashlib.sha3_256(raw).hexdigest(),
            }
            status = "FINALIZING" if complete else "PAUSED_FOR_APPROVAL"
            if (
                run_store.update_run_status(
                    run_id, status, details={"evidence_capture": receipt}, context=context
                )
                is not True
            ):
                raise ValueError("Provider did not acknowledge capture completion")
            return receipt
        except Exception as exc:
            logger.error("Could not finalize evidence capture for %s", run_id, exc_info=True)
            self._delivery_failures[run_id] = exc
            try:
                run_store.update_run_status(
                    run_id,
                    "CERTIFICATION_FAILED",
                    details={"evidence_capture_failed": True},
                    context=context,
                )
            except Exception:
                logger.error("Could not persist capture failure for %s", run_id, exc_info=True)
            raise EvidenceDeliveryError("IncompleteEvidenceCapture: stream closure failed") from exc

    def resume_capture(self, run_id, run_store, context=None):
        import json

        from .certification_truth import capture_receipt_failures

        with self._lock:
            if self._inflight_counts.get(run_id, 0) or run_id in self._delivery_failures:
                raise EvidenceDeliveryError("Cannot resume an active or failed evidence stream")
        record = run_store.get_run(run_id, context=context) or {}
        receipt = (record.get("status_details") or {}).get("evidence_capture")
        raw = run_store.get_trace_bytes(run_id, context=context)
        rows = (
            [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            if isinstance(raw, bytes)
            else []
        )
        if (
            (record.get("status_details") or {}).get("evidence_capture_failed") is True
            or not isinstance(receipt, dict)
            or receipt.get("complete") is not False
            or receipt.get("resumable") is not True
            or capture_receipt_failures(receipt, raw, rows, require_complete=False)
        ):
            raise EvidenceDeliveryError(
                "IncompleteEvidenceCapture: resumption lacks acknowledged prefix"
            )
        if (
            run_store.update_run_status(
                run_id,
                "OPEN",
                details={"evidence_capture": {**receipt, "resumable": False}},
                context=context,
            )
            is not True
        ):
            raise EvidenceDeliveryError("Provider did not acknowledge capture resumption")
        with self._lock:
            if self._inflight_counts.get(run_id, 0):
                raise EvidenceDeliveryError("Cannot resume an active evidence stream")
            self._closed_runs.discard(run_id)
            self._emitted_counts[run_id] = receipt["event_count"]
            self._acknowledged_counts[run_id] = receipt["event_count"]
            self._baseline_counts[run_id] = receipt["event_count"]
            self._emission_commitments[run_id] = []

    def flush(self, timeout: float | None = None):
        """Block until all currently scheduled async event tasks are complete."""
        import concurrent.futures

        with self._lock:
            futures = list(self._pending_futures)
            self._pending_futures.clear()
        if futures:
            concurrent.futures.wait(futures, timeout=timeout)

    def emit(
        self,
        name: str,
        data: dict[str, Any],
        span_context: dict[str, Any] | None = None,
        *,
        required_only: bool = False,
    ):
        """Emit an event to all subscribers with optional tracing context."""
        sanitized_data = sanitize_payload(data)

        # Inversion of Control: Auto-inject run_id if available in the bus
        if self.run_id and "run_id" not in sanitized_data:
            sanitized_data["run_id"] = self.run_id

        event = Event(name, sanitized_data, span_context=span_context)
        all_subs = self._subscribers + list(self._keyed_subscribers.values())
        run_id = sanitized_data.get("run_id") or self.run_id
        import hashlib

        from agentv_runtime.canonical import canonical_json_encode

        emitted = event.to_dict()
        commitment = (tuple(emitted), hashlib.sha3_256(canonical_json_encode(emitted)).hexdigest())
        with self._lock:
            if run_id in self._closed_runs:
                raise EvidenceDeliveryError(f"Evidence stream is closed for run {run_id}")
            if run_id in self._delivery_failures:
                raise EvidenceDeliveryError(
                    f"Evidence capture already failed for run {run_id}"
                ) from self._delivery_failures[run_id]
            self._emitted_counts[run_id] = self._emitted_counts.get(run_id, 0) + 1
            self._inflight_counts[run_id] = self._inflight_counts.get(run_id, 0) + 1
            self._emission_commitments.setdefault(run_id, []).append(commitment)
        optional_subs = []
        mandatory_count = 0
        for subscriber in all_subs:
            required = (
                subscriber in self._required_subscribers
                or getattr(
                    getattr(subscriber, "__self__", None), "evidence_delivery_required", False
                )
                is True
            )
            if not required:
                optional_subs.append(subscriber)
                continue
            try:
                mandatory_count += 1
                # Mandatory persistence is acknowledged before asynchronous telemetry.
                result = subscriber(event)
                import inspect

                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("Mandatory evidence acknowledgement cannot be asynchronous")
            except Exception as exc:
                logger.error("Mandatory event delivery failed for %s", run_id, exc_info=True)
                self._delivery_failures[run_id] = exc
                with self._lock:
                    self._inflight_counts[run_id] -= 1
                raise EvidenceDeliveryError(f"Evidence capture failed for run {run_id}") from exc
        with self._lock:
            self._inflight_counts[run_id] -= 1
            if mandatory_count:
                self._acknowledged_counts[run_id] = self._acknowledged_counts.get(run_id, 0) + 1
        if required_only:
            return
        all_subs = optional_subs

        # Capture current OTel context if available
        otel_ctx = None
        try:
            from opentelemetry import context as otel_context

            otel_ctx = otel_context.get_current()
        except ImportError:
            pass

        if not self.async_mode:
            for sub in all_subs:
                try:
                    # In sync mode, propagate context natively
                    token = None
                    if otel_ctx is not None:
                        try:
                            from opentelemetry import context as otel_context

                            token = otel_context.attach(otel_ctx)
                        except Exception as _e:
                            logger.debug("OTel attach skipped: %s", _e, exc_info=True)
                    try:
                        sub(event)
                    finally:
                        if token is not None:
                            try:
                                from opentelemetry import context as otel_context

                                otel_context.detach(token)
                            except Exception as _e:
                                logger.debug("OTel detach skipped: %s", _e, exc_info=True)
                except Exception as e:
                    # Core stays stable even if subscribers fail
                    logging.getLogger(__name__).debug("Failure in EventEmitter.emit", exc_info=True)
                    print(f"   [Events] Error in subscriber for {name}: {e}")
            return

        # Async dispatching
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        # Clean completed futures to prevent accumulation leaks
        with self._lock:
            self._pending_futures = [f for f in self._pending_futures if not f.done()]

        for sub in all_subs:
            try:
                if loop is not None:
                    if asyncio.iscoroutinefunction(sub):

                        async def wrapped_coro(s=sub):
                            tok = None
                            if otel_ctx is not None:
                                try:
                                    from opentelemetry import context as otel_context

                                    tok = otel_context.attach(otel_ctx)
                                except Exception as _e:
                                    logger.debug("OTel attach skipped: %s", _e, exc_info=True)
                            try:
                                await s(event)
                            finally:
                                if tok is not None:
                                    try:
                                        from opentelemetry import context as otel_context

                                        otel_context.detach(tok)
                                    except Exception as _e:
                                        logger.debug("OTel detach skipped: %s", _e, exc_info=True)

                        loop.create_task(wrapped_coro())
                    else:
                        future = loop.run_in_executor(
                            None, _execute_subscriber_with_context, sub, event, otel_ctx
                        )
                        with self._lock:
                            self._pending_futures.append(future)
                else:
                    future = self.get_executor().submit(
                        _execute_subscriber_with_context, sub, event, otel_ctx
                    )
                    with self._lock:
                        self._pending_futures.append(future)
            except Exception as e:
                logging.getLogger(__name__).debug("Failure in EventEmitter.emit", exc_info=True)
                print(f"   [Events] Error scheduling subscriber for {name}: {e}")

    # --- Lifecycle Management ---
    _global_instance = None

    @classmethod
    def get_global(cls):
        """Authoritative singleton resolver for the global event bus."""
        if cls._global_instance is None:
            cls._global_instance = cls()
        return cls._global_instance


# Standard Global interface (Module Level Aliases)
def subscribe(
    subscriber: Callable[[Event], None], key: str | None = None, *, required: bool = False
):
    """Register a subscriber to the global event bus."""
    EventEmitter.get_global().subscribe(subscriber, key=key, required=required)


def unsubscribe(subscriber: Callable[[Event], None] | str):
    """Unregister a subscriber from the global event bus."""
    EventEmitter.get_global().unsubscribe(subscriber)


def emit(
    name: str,
    data: dict[str, Any],
    span_context: dict[str, Any] | None = None,
    *,
    required_only: bool = False,
):
    """Broadcast an event via the global bus (Strict Redaction Enforced)."""
    EventEmitter.get_global().emit(
        name, data, span_context=span_context, required_only=required_only
    )


def reset():
    """Reset the global event bus state."""
    EventEmitter.get_global().reset()


# Pre-defined event names for consistency
class CoreEvents:
    RUN_START = "run_start"
    RUN_END = "run_end"
    EVALUATOR_FINALIZATION = "evaluator_finalization"
    TASK_START = "task_start"
    TASK_END = "task_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    AGENT_REQUEST = "agent_request"
    AGENT_RESPONSE = "agent_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    EXTERNAL_TOOL_CALL = "external_tool_call"
    EXTERNAL_TOOL_RESULT = "external_tool_result"
    EVALUATION = "evaluation"
    ASSERTION_EVALUATED = "assertion_evaluated"
    HITL_PAUSE = "hitl_pause"
    HITL_RESUME = "hitl_resume"
    APPROVAL_CREATED = "approval_created"
    APPROVAL_RESOLVED = "approval_resolved"
    ERROR = "error"
    RUN_ERROR = "error"

    # Core Telemetry Extensions (v1.2.4)
    CHAIN_START = "chain_start"
    CHAIN_END = "chain_end"
    NODE_START = "node_start"
    NODE_END = "node_end"

    # Behavioral DNA & OTEL Nesting (v1.1.0)
    STRATEGY_START = "strategy_start"
    STRATEGY_END = "strategy_end"
    MANEUVER_START = "maneuver_start"
    MANEUVER_END = "maneuver_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    SUBTASK_START = "subtask_start"
    SUBTASK_END = "subtask_end"
    ACTION_START = "action_start"
    ACTION_END = "action_end"
    STEP_START = "step_start"
    STEP_END = "step_end"

    # Infrastructure & Target Abstraction (v1.3.0)
    ROUTING_RESOLVED = "routing_resolved"
    ADAPTER_DEBUG = "adapter_debug"

    # Canonical Execution Graph Events (v2.0.0 Architecture)
    GRAPH_UPDATE = "graph_update"
    EXECUTION_GRAPH_NODE = "execution_graph_node"
    EXECUTION_GRAPH_EDGE = "execution_graph_edge"

    # Terminal Trust & Certification Events
    CERTIFICATION_FAILED = "certification_failed"
    EVALUATION_INVALID = "evaluation_invalid"
    PARITY_STATE_DIVERGENCE = "parity_state_divergence"
    TRACE_SEALED = "trace_sealed"
    VERIFICATION_CERTIFICATE_ISSUED = "verification_certificate_issued"


class ExecutionEdgeType(StrEnum):
    """Authoritative edge causality types in the execution graph."""

    SEQUENTIAL = "sequential"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    RETRY = "retry"
    CHILD_TASK = "child_task"


class ExecutionNodeStatus(StrEnum):
    """Execution status for graph nodes."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionGraphNode(BaseModel):
    """Authoritative execution node event emitted by the runtime."""

    run_id: str
    event_id: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    timestamp: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    scenario_revision_hash: str | None = None
    scenario_node_id: str
    execution_node_id: str
    parent_execution_id: str | None = None
    label: str | None = None
    status: ExecutionNodeStatus = ExecutionNodeStatus.PENDING
    attempt: int = 1
    duration_ms: float | None = None
    tool_identity: str | None = None
    failure_class: str | None = None
    failure_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionGraphEdge(BaseModel):
    """Authoritative execution edge linking nodes in the execution graph."""

    run_id: str
    event_id: int = Field(default_factory=lambda: int(datetime.now().timestamp() * 1000))
    source_execution_id: str
    target_execution_id: str
    edge_type: ExecutionEdgeType = ExecutionEdgeType.SEQUENTIAL
    condition: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventStage(StrEnum):
    """Authoritative Forensic Stages (AES v1.4)."""

    IDLE = "idle"
    GROUNDING = "grounding"
    SYNTHESIS = "synthesis"
    SCENARIOS = "scenarios"
    EVALUATION = "evaluation"
    ASSERTION_EVALUATED = "assertion_evaluated"
    STRESS = "stress"
    SYSTEM = "system"


class EventLevel(StrEnum):
    """Forensic Severity & Type Levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    TRACE = "trace"
    ARTIFACT = "artifact"


class ForensicEvent(BaseModel):
    """
    Structured Forensic Event (Pydantic).
    Standardized across Core/Enterprise for unified telemetry streaming.
    """

    id: str = Field(default_factory=lambda: str(int(datetime.now().timestamp() * 1000)))
    ts: float = Field(default_factory=lambda: datetime.now().timestamp())
    stage: EventStage
    level: EventLevel
    message: str
    data: dict[str, Any] | None = None
