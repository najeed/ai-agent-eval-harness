"""
Evaluation Runner Core Package.
"""

# Establish version first for package identity (SSOT)
import asyncio
import inspect
import warnings

# --- MONKEYPATCH DEPRECATIONS ---
# Fix asyncio.iscoroutinefunction deprecation warning in Python 3.14+
# by pointing it directly to inspect.iscoroutinefunction. This prevents
# third-party packages (LangChain, AutoGen, Daytona) from raising warnings.
if not hasattr(asyncio, "_original_iscoroutinefunction"):
    asyncio._original_iscoroutinefunction = asyncio.iscoroutinefunction  # type: ignore[attr-defined]
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction

from .config import VERSION as __version__  # noqa: F401

# --- INDUSTRIAL NEUTRALITY: VERSION-GATE SUPPRESSION ---
# Neutralize speculative compatibility warnings from external dependencies (LangChain/Pydantic)
# that mangle the console output on Python 3.14+ without impacting system stability.
# This ensures a clean, audit-grade experience for Enterprise Trust Workflows.
warnings.filterwarnings("ignore", message=".*compatible with Python 3.14 or greater.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="google.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="autogen.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="daytona.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain_core.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph.*")
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_core.*")
warnings.filterwarnings(
    "ignore",
    message=".*coroutine '_wait_for_close' was never awaited.*",
    category=RuntimeWarning,
)

# NOTE: circular import protection. Engineers should import Engine specifically
# from eval_runner.engine to avoid initialization races.
