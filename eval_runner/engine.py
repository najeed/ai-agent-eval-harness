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

# Read the agent URL from an environment variable, with a default for local testing
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")

# Maximum number of conversation turns per task before forcing completion
MAX_TURNS = int(os.getenv("EVAL_MAX_TURNS", "5"))

# Run Log Configuration
RUN_LOG_DIR = Path(os.getenv("RUN_LOG_DIR", "runs"))
RUN_LOG_PER_RUN = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
RUN_LOG_MASTER = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
RUN_LOG_ROTATE_COUNT = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))  # 0 means no rotation

def rotate_logs(log_dir: Path, max_files: int):
    """Keeps only the latest N run-<id>.jsonl files in the log directory."""
    if max_files <= 0:
        return
    
    run_files = sorted(
        log_dir.glob("run-*.jsonl"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    
    if len(run_files) >= max_files:
        for old_file in run_files[max_files - 1:]:
            try:
                old_file.unlink()
                print(f"      [Engine] Rotated old log: {old_file.name}")
            except Exception as e:
                print(f"      [Engine] Error rotating log {old_file}: {e}")

# Dynamic Adapter Registry for Agent Communication
class AgentAdapterRegistry:
    _adapters: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, protocol: str, adapter_func):
        cls._adapters[protocol] = adapter_func
        
    @classmethod
    async def call_agent(cls, payload: dict, protocol="http"):
        adapter = cls._adapters.get(protocol)
        if adapter:
            return await adapter(payload)
        # Default HTTP implementation
        async with aiohttp.ClientSession() as session:
            async with session.post(
                AGENT_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                return await response.json()

async def run_evaluation(scenario: dict, attempts: int = 1, metadata: Optional[dict] = None) -> list:
    """Entry point for evaluation. Delegates to the Runner strategy."""
    from .runner import DefaultRunner
    
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
