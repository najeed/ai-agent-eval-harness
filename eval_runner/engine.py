from __future__ import annotations

"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import sys  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402

from eval_runner import plugins  # noqa: E402

from . import config  # noqa: E402

# Security Guardrails
MAX_ENGINE_ATTEMPTS = config.MAX_ENGINE_ATTEMPTS
MAX_TURNS = config.EVAL_MAX_TURNS


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
        adapter_func = cls._adapters.get(protocol)
        if not adapter_func:
            available = list(cls._adapters.keys())
            raise ValueError(f"Unsupported protocol '{protocol}'. Available: {available}")

        # 2. Forensic Context Preparation
        payload = {
            "protocol": protocol,
            "task_description": message,
            "history": history,
            "turn": turn_ctx.turn_number if turn_ctx else 1,
            "metadata": turn_ctx.metadata if turn_ctx else {},
            "input_payload": getattr(turn_ctx, "input_payload", {}),
        }

        # Resolve OpenTelemetry child span context
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
                payload["span_context"] = {"traceparent": carrier["traceparent"]}
                if turn_ctx:
                    object.__setattr__(turn_ctx, "span_context", payload["span_context"])
        except Exception:
            pass

        # 3. Execution (with Industrial Protection)
        try:
            response = await adapter_func(payload, endpoint=endpoint)
            if span and span.is_recording():
                span.set_attribute("agentv.action", response.get("action", "unknown"))
            return response
        except Exception as e:
            if span and span.is_recording():
                try:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR)
                except Exception:
                    pass
            sys.stderr.write(f"      [Dispatcher Error] {protocol} failed: {str(e)}\n")
            raise
        finally:
            if span and span.is_recording():
                try:
                    span.end()
                except Exception:
                    pass


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
