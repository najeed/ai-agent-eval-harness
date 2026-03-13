from __future__ import annotations
"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import os
import json
import aiohttp
import asyncio
import inspect
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from . import plugins
from . import metrics
from .context import EvaluationContext, TurnContext
from .tool_sandbox import ToolSandbox

from . import config

# Security Guardrails
MAX_ENGINE_ATTEMPTS = config.MAX_ENGINE_ATTEMPTS
MAX_TURNS = config.EVAL_MAX_TURNS

# Dynamic Adapter Registry for Agent Communication
class AgentAdapterRegistry:
    _adapters: Dict[str, Callable] = {}
    _discovered: bool = False
    
    @classmethod
    def register(cls, protocol: str, adapter_func):
        cls._adapters[protocol] = adapter_func

    @classmethod
    def _discover(cls):
        """Triggers plugin-based discovery of adapters."""
        if cls._discovered:
            return
        
        # Load standard adapters
        from . import adapters
        cls.register("http", adapters.http_adapter)
        cls.register("local", adapters.local_subprocess_adapter)
        cls.register("socket", adapters.socket_adapter)

        plugins.manager.trigger("on_discover_adapters", cls)
        
        # Register default human adapter if not already registered
        if "human" not in cls._adapters:
            cls._adapters["human"] = cls._human_adapter
            
        cls._discovered = True
        
    @classmethod
    async def _human_adapter(cls, payload: dict):
        """Placeholder for Human-In-The-Loop intervention."""
        # This will be handled by the session execution loop
        return {"action": "hitl_pause", "message": "Waiting for human intervention."}
        
    @classmethod
    async def call_agent(cls, payload: dict, protocol="http", endpoint: Optional[str] = None):
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
        return await adapter(payload, endpoint)

async def run_evaluation(scenario: dict, attempts: int = 1, metadata: Optional[dict] = None) -> list:
    """Entry point for evaluation. Delegates to the Runner strategy."""
    from .runner import DefaultRunner
    
    if attempts > MAX_ENGINE_ATTEMPTS:
        print(f"[Engine] Security WARNING: requested attempts ({attempts}) exceeds MAX_ENGINE_ATTEMPTS ({MAX_ENGINE_ATTEMPTS}). Capping.")
        attempts = MAX_ENGINE_ATTEMPTS
    
    # Load internal plugins if not already loaded (like FlightRecorder and ReportingPlugin)
    from .flight_recorder import FlightRecorderPlugin
    from .reporting_plugin import ReportingPlugin
    if not any(isinstance(p, FlightRecorderPlugin) for p in plugins.manager.plugins):
        plugins.manager.plugins.append(FlightRecorderPlugin())
    if not any(isinstance(p, ReportingPlugin) for p in plugins.manager.plugins):
        plugins.manager.plugins.append(ReportingPlugin())

    runner = DefaultRunner()
    results = await runner.run(scenario, attempts, metadata=metadata)
    
    # Backward compatibility: return first attempt if k=1
    return results[0] if attempts == 1 else results
