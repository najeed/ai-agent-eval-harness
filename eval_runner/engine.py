from __future__ import annotations

"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import os  # noqa: E402
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

    # Authoritative Taxonomy (v1.5.0 Standard)
    ADAPTER_TAXONOMY = {
        "http": "protocols",
        "local": "protocols",
        "socket": "protocols",
        "openapi": "protocols",
        "openai": "providers",
        "claude": "providers",
        "gemini": "providers",
        "grok": "providers",
        "ollama": "providers",
        "autogen": "frameworks",
        "crewai": "frameworks",
        "langgraph": "frameworks",
        "langchain": "frameworks",
    }

    # Baseline protocols protected from accidental overwrite
    CORE_PROTOCOLS = {"http", "local", "socket", "openapi"}

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

        # Hardened Zero-Trust Baseline (v1.5.0 Standard)
        cls._active_whitelists["protocols"] = {"http", "openapi"}
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
        payload: dict,
        protocol="http",
        endpoint: str | None = None,
        span_context: dict[str, Any] | None = None,
        **kwargs,
    ):
        cls._discover()

        adapter = cls._adapters.get(protocol)
        if not adapter:
            raise ValueError(f"No adapter registered for protocol: {protocol}")

        # Use provided endpoint or fall back to defaults
        if not endpoint:
            if protocol == "http":
                endpoint = config.AGENT_API_URL
            elif protocol == "local":
                endpoint = os.getenv("AGENT_LOCAL_CMD")
            elif protocol == "socket":
                endpoint = os.getenv("AGENT_SOCKET_ADDR")

        if not endpoint:
            raise ValueError(f"No endpoint/command provided for protocol '{protocol}'")

        print(f"      [Engine] Executing {protocol} call to: {endpoint}")
        response = await adapter(payload, endpoint, span_context=span_context, **kwargs)

        # [Forensic Persistence] Recording raw interaction Stimulus
        forensics_handle = kwargs.get("forensics")
        if forensics_handle:
            forensics_handle.register_raw_interaction(payload, response)

        return response


async def run_evaluation(
    scenario: dict,
    run_id: str | None = None,
    attempts: int = 1,
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
    from .reporting_plugin import ReportingPlugin

    plugins.manager.register(FlightRecorderPlugin(), origin="CORE")
    plugins.manager.register(ReportingPlugin(), origin="CORE")

    runner = DefaultRunner()
    results = await runner.run(
        scenario, attempts, run_id=run_id, metadata=metadata, max_turns=max_turns
    )

    # Backward compatibility: return first attempt if k=1
    if attempts == 1:
        return results[0] if results else []
    return results
