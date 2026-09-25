from __future__ import annotations

"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import copy  # noqa: E402
import hashlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402

from eval_runner import plugins  # noqa: E402

from . import config  # noqa: E402
from .context import AdapterInvocationContext  # noqa: E402

logger = logging.getLogger(__name__)

# Security Guardrails
MAX_ENGINE_ATTEMPTS = config.MAX_ENGINE_ATTEMPTS
MAX_TURNS = config.EVAL_MAX_TURNS


def render_outbound_payload(
    message: str,
    turn_ctx: Any,
    protocol: str,
) -> tuple[dict[str, Any], str]:
    """
    Renders the exact wire payload and computes its cryptographic hash (P0-04).
    Ensures that mutations on the prompt alter the actual transmitted request body.
    """
    metadata = getattr(turn_ctx, "metadata", {}) if turn_ctx else {}
    if not isinstance(metadata, dict):
        metadata = {}
    payload_template = metadata.get("payload_template")
    input_payload = getattr(turn_ctx, "input_payload", {}) or {}
    node = getattr(turn_ctx, "node", {}) or {}
    node_id = str(
        getattr(turn_ctx, "node_id", "") or (node.get("id", "") if isinstance(node, dict) else "")
    )
    run_id = str(getattr(turn_ctx, "run_id", "") or "")

    if payload_template and isinstance(payload_template, dict):
        payload = {}
        for k, v in payload_template.items():
            if isinstance(v, str):
                rendered = v.replace("{task_description}", message)
                rendered = rendered.replace("{node_id}", node_id)
                rendered = rendered.replace("{run_id}", run_id)
                if v == "{input_payload}":
                    payload[k] = copy.deepcopy(input_payload)
                elif v == "{task_description}":
                    payload[k] = message
                else:
                    payload[k] = rendered
            else:
                payload[k] = copy.deepcopy(v)
    elif protocol == "openapi":
        if isinstance(input_payload, dict) and input_payload:
            payload = copy.deepcopy(input_payload)
            # Propagate prompt mutation to common prompt keys if present
            prompt_keys = (
                "task_description",
                "task",
                "prompt",
                "input",
                "query",
                "message",
                "instruction",
            )
            matched = False
            for pk in prompt_keys:
                if pk in payload:
                    payload[pk] = message
                    matched = True
                    break
            if not matched:
                payload["task_description"] = message
        else:
            payload = {"task_description": message}
    else:
        payload = {"task_description": message}

    from agentv_runtime.canonical import canonical_json_encode

    try:
        c_bytes = canonical_json_encode(payload)
    except Exception:
        c_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")

    payload_hash = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
    return payload, payload_hash


def _internal_adapter_payload(
    wire_payload: dict[str, Any], context: AdapterInvocationContext
) -> dict[str, Any]:
    """Materialize context for a native adapter without changing wire payloads."""
    payload = dict(wire_payload)
    payload["history"] = [dict(item) for item in context.history]
    payload["input_payload"] = dict(context.input_payload)
    payload["metadata"] = dict(context.metadata)
    if context.task_id:
        payload.setdefault("task_id", context.task_id)
    if context.turn_number is not None:
        payload.setdefault("turn_number", context.turn_number)
    if context.span_context:
        payload["span_context"] = dict(context.span_context)
    return payload


def _adapter_endpoint_kwargs(adapter_func: Callable, endpoint: str | None) -> dict[str, Any]:
    """Use the endpoint spelling accepted by legacy adapter entry points."""
    parameters = inspect.signature(adapter_func).parameters
    for name in ("endpoint", "url", "base_url"):
        if name in parameters:
            return {name: endpoint}
    # Generic/plugin adapters conventionally accept endpoint through **kwargs.
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return {"endpoint": endpoint}
    return {}


def _adapter_context_kwargs(
    adapter_func: Callable,
    context: AdapterInvocationContext,
    turn_ctx: Any | None,
) -> dict[str, Any]:
    """Pass internal context only to adapters that opt into it.

    This preserves compatibility with existing third-party adapters whose
    callable contract is limited to ``(payload, endpoint)``.
    """
    parameters = inspect.signature(adapter_func).parameters
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if accepts_kwargs or "context" in parameters:
        kwargs["context"] = context
    if accepts_kwargs or "turn_ctx" in parameters:
        kwargs["turn_ctx"] = turn_ctx
    return kwargs


# Dynamic Adapter Registry for Agent Communication
class AgentAdapterRegistry:
    _adapters: dict[str, Callable] = {}
    _discovered: bool = False
    _active_whitelists: dict[str, set[str] | None] = {
        "protocols": None,
        "providers": None,
        "frameworks": None,
    }

    # Authoritative Taxonomy (v1.6.0 Standard)
    ADAPTER_TAXONOMY = {
        "http": "protocols",
        "local": "protocols",
        "socket": "protocols",
        "sse": "protocols",
        "openapi": "protocols",
        "openai": "providers",
        "claude": "providers",
        "gemini": "providers",
        "grok": "providers",
        "ollama": "providers",
        "ag2": "frameworks",
        "crewai": "frameworks",
        "langgraph": "frameworks",
        "langchain": "frameworks",
    }

    # Baseline protocols protected from accidental overwrite
    CORE_PROTOCOLS = {"http", "sse", "local", "socket", "openapi"}

    @classmethod
    def register(
        cls, protocol: str, adapter_func, category: str | None = None, allow_override: bool = False
    ):
        """
        Registers an adapter, enforcing categorical whitelists and core immutability.
        """
        # 1. Core Immutability Check
        if protocol in cls.CORE_PROTOCOLS and protocol in cls._adapters and not allow_override:
            import sys

            sys.stderr.write(
                f"      [Engine] WARNING: Blocked attempt to overwrite core protocol '{protocol}'. "
                "Set allow_override=True to force.\n"
            )
            return

        # 2. Categorical Governance check
        # Resolve category from taxonomy if not provided explicitly
        base_protocol = protocol.split(":")[0]
        category = category or cls.ADAPTER_TAXONOMY.get(base_protocol)

        if category and category in cls._active_whitelists:
            whitelist = cls._active_whitelists[category]
            if (
                whitelist is not None
                and protocol not in whitelist
                and base_protocol not in whitelist
            ):
                # Silently skip if disabled by administrative policy
                return

        cls._adapters[protocol] = adapter_func

    @classmethod
    def get_available_protocols(cls) -> list[str]:
        """Returns sorted list of all active registered protocol adapters."""
        if not cls._discovered:
            cls._discover()
        return sorted(list(cls._adapters.keys()))

    @classmethod
    def reset(cls):
        """Resets the registry state for tests."""
        cls._discovered = False
        cls._adapters = {}
        cls._active_whitelists = {"protocols": None, "providers": None, "frameworks": None}

    @classmethod
    def _discover(cls):
        """Triggers dynamic discovery of all adapters in the adapters/ directory."""
        if cls._discovered:
            return

        # 0. Load Administrative Activation Policy
        from .config import RegistryManager

        # Hardened Zero-Trust Baseline (v1.6.0 Standard)
        cls._active_whitelists["protocols"] = {"http", "sse", "openapi"}
        cls._active_whitelists["providers"] = set()
        cls._active_whitelists["frameworks"] = set()

        resolved = RegistryManager.get_resolved_registry()
        policy = resolved.get("adapters", {})

        if not policy:
            print(
                "      [Engine] WARNING: No administrative adapter policy found. "
                "Falling back to Zero-Trust Baseline."
            )

        # Apply Whitelists from Policy
        for cat in ["protocols", "providers", "frameworks"]:
            key = f"active_{cat}"
            if key in policy:
                cls._active_whitelists[cat] = set(policy[key])

        from eval_runner import adapters

        from . import discovery

        # 1. Authoritative Protocol Registration (Baseline)
        cls.register("http", adapters.http_adapter)
        cls.register("sse", adapters.sse_http_adapter)
        cls.register("local", adapters.local_subprocess_adapter)
        cls.register("socket", adapters.socket_adapter)

        # 2. Ecosystem Discovery (Dynamic)
        discovery.scan_package_for_adapters(adapters, cls.register)

        # 3. Trigger Plugin Discovery
        from eval_runner import plugins

        plugins.manager.trigger("on_discover_adapters", cls)

        cls._discovered = True

    @classmethod
    async def call_agent(
        cls,
        protocol: str,
        endpoint: str | None,
        message: str,
        history: list[dict],
        turn_ctx: Any | None = None,
    ) -> dict[str, Any]:
        """
        Industrial Multi-Agent Dispatcher (v1.6.0).
        Routes the task to the appropriate adapter based on protocol.
        """
        if not cls._discovered:
            cls._discover()

        # 1. Resolve Adapter
        normalized_proto = protocol.lower().strip() if protocol else ""
        adapter_func = cls._adapters.get(normalized_proto)
        if not adapter_func:
            available = list(cls._adapters.keys())
            raise ValueError(f"Unsupported protocol '{protocol}'. Available: {available}")

        # 2. Wire Payload — only what an agent in the wild would receive from a human caller.
        # Renders the exact outbound request and computes its cryptographic hash (P0-04).
        payload, outbound_payload_hash = render_outbound_payload(
            message, turn_ctx, normalized_proto
        )
        if turn_ctx:
            if not hasattr(turn_ctx, "metadata") or not isinstance(
                getattr(turn_ctx, "metadata", None), dict
            ):
                try:
                    object.__setattr__(turn_ctx, "metadata", {})
                except (AttributeError, TypeError) as meta_err:
                    logger.debug("Failed setting turn_ctx metadata dict: %s", meta_err)
            if hasattr(turn_ctx, "metadata") and isinstance(turn_ctx.metadata, dict):
                turn_ctx.metadata["outbound_payload_hash"] = outbound_payload_hash
                turn_ctx.metadata["rendered_outbound_payload"] = payload

        # Resolve OpenTelemetry child span context. Keep it in the internal
        # invocation context rather than in a remote application's payload.
        invocation_context = AdapterInvocationContext.from_turn_context(message, turn_ctx)
        child_otel_ctx = None
        span = None
        parent_context = getattr(turn_ctx, "otel_context", None)
        try:
            from opentelemetry import trace
            from opentelemetry.trace import propagation

            tracer = trace.get_tracer("agentv")
            span = tracer.start_span(
                name=f"agentv.call_agent.{protocol}",
                context=parent_context,
            )
            span.set_attribute("agentv.protocol", protocol)
            span.set_attribute("agentv.endpoint", endpoint or "local")

            child_otel_ctx = trace.set_span_in_context(span, parent_context)
            if turn_ctx:
                # Store the child context back on the turn context
                object.__setattr__(turn_ctx, "otel_context", child_otel_ctx)

            carrier = {}
            propagation.inject(carrier, context=child_otel_ctx)
            if "traceparent" in carrier:
                span_context = {"traceparent": carrier["traceparent"]}
                if turn_ctx:
                    object.__setattr__(turn_ctx, "span_context", span_context)
                invocation_context = AdapterInvocationContext(
                    message=invocation_context.message,
                    history=invocation_context.history,
                    input_payload=invocation_context.input_payload,
                    metadata=invocation_context.metadata,
                    span_context=span_context,
                    task_id=invocation_context.task_id,
                    turn_number=invocation_context.turn_number,
                    turn_context=invocation_context.turn_context,
                )
        except Exception as _e:
            logger.debug("Span context injection skipped: %s", _e, exc_info=True)

        # 3. Execution (with Industrial Protection)
        try:
            category = cls.ADAPTER_TAXONOMY.get(normalized_proto.split(":", 1)[0])
            adapter_payload = (
                _internal_adapter_payload(payload, invocation_context)
                if category in {"providers", "frameworks"}
                else payload
            )
            response = await adapter_func(
                adapter_payload,
                **_adapter_endpoint_kwargs(adapter_func, endpoint),
                **_adapter_context_kwargs(adapter_func, invocation_context, turn_ctx),
            )
            if span and span.is_recording():
                span.set_attribute("agentv.action", response.get("action", "unknown"))
            return response
        except Exception as e:
            if span and span.is_recording():
                try:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR)
                except Exception as _ex:
                    logger.debug("Span status recording failed: %s", _ex, exc_info=True)
            sys.stderr.write(f"      [Dispatcher Error] {protocol} failed: {str(e)}\n")
            raise
        finally:
            if span and span.is_recording():
                try:
                    span.end()
                except Exception as _ex2:
                    logger.debug("Span end failed: %s", _ex2, exc_info=True)


async def run_evaluation(
    scenario: dict,
    run_id: str | None = None,
    attempts: int = 1,
    seed: int | None = None,
    metadata: dict | None = None,
    max_turns: int | None = None,
) -> list:
    """Entry point for evaluation. Delegates to the Runner strategy."""
    from .runner import DefaultRunner

    if attempts > MAX_ENGINE_ATTEMPTS:
        print(
            f"[Engine] Security WARNING: requested attempts ({attempts}) exceeds MAX_ENGINE_ATTEMPTS ({MAX_ENGINE_ATTEMPTS}). Capping."  # noqa: E501
        )
        attempts = MAX_ENGINE_ATTEMPTS

    # Load internal plugins if not already loaded (like FlightRecorder and ReportingPlugin)
    from .flight_recorder import FlightRecorderPlugin
    from .otel_bridge import OTelTelemetryBridge
    from .reporting_plugin import ReportingPlugin

    plugins.manager.register(FlightRecorderPlugin(), origin="CORE")
    plugins.manager.register(ReportingPlugin(), origin="CORE")
    plugins.manager.register(OTelTelemetryBridge(), origin="CORE")

    runner = DefaultRunner()
    results = await runner.run(
        scenario, attempts, run_id=run_id, seed=seed, metadata=metadata, max_turns=max_turns
    )

    # Backward compatibility: return first attempt if k=1
    if attempts == 1:
        return results[0] if results else []
    return results
