"""
plugins.py

Plugin management system for MultiAgentEval.
Handles dynamic discovery and loading of evaluation plugins.
Updated to respect Zero-Touch architecture and immutable core.
"""

from __future__ import annotations
import json
import os
import importlib.metadata
import concurrent.futures
from typing import List, Any, Optional, Dict
from pathlib import Path
from . import config
from . import discovery

PLUGIN_TIMEOUT = config.PLUGIN_TIMEOUT
PERSISTENT_PLUGINS_PATH = config.PROJECT_ROOT / ".aes" / "plugins.json"


def _invoke_with_timeout(func, *args, **kwargs):
    """Executes a plugin hook with a security timeout using a thread pool."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=PLUGIN_TIMEOUT)
        except concurrent.futures.TimeoutError:
            print(f"   [PluginManager] Timeout (>{PLUGIN_TIMEOUT}s) in hook execution.")
            raise


from abc import ABC, abstractmethod


class BaseEvalPlugin(ABC):
    """Base class for all evaluation plugins."""

    def before_evaluation(self, context: Any, span_context: Optional[Dict[str, Any]] = None):
        """Hook called before the evaluation scenario begins."""
        pass

    def after_evaluation(self, context: Any, results: list, span_context: Optional[Dict[str, Any]] = None):
        """Hook called after the evaluation scenario completes."""
        pass

    def on_register_commands(self, registry: Any):
        """Hook to register custom CLI commands."""
        pass

    def on_discover_adapters(self, registry: Any):
        """Hook to register custom agent adapters."""
        pass

    def on_register_simulators(self, registry: dict):
        """Hook to register custom world simulators."""
        pass


class PluginManager:
    """Orchestrates plugin lifecycle."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PluginManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self.plugins: List[BaseEvalPlugin] = []
        self._plugins = self.plugins  # Alias for diagnostic visibility
        self._loaded = False
        self._last_load_time = 0
        self._initialized = True

    def reset(self):
        """Resets the plugin manager state for tests."""
        self.plugins.clear()
        self._loaded = False

    def load_plugins(self, force: bool = False):
        """Discovers and loads plugins with an industrial 60s TTL debounce."""
        import time
        now = time.time()
        
        # Performance: Skip scan if loaded within 60s (unless forced)
        if self._loaded and not force:
            if now - self._last_load_time < 60:
                return
        
        self._last_load_time = now

        # 1. Discover external plugins via entry points (standard install)
        for entry_point in importlib.metadata.entry_points(group="eval_runner.plugins"):
            try:
                plugin_cls = entry_point.load()
                if not any(isinstance(p, plugin_cls) for p in self.plugins):
                    self.plugins.append(plugin_cls())
            except Exception:
                pass

        # 2. Load manually registered persistent plugins
        if PERSISTENT_PLUGINS_PATH.exists():
            try:
                with open(PERSISTENT_PLUGINS_PATH, "r", encoding="utf-8") as f:
                    persistent = json.load(f)
                    for plugin_path in persistent.get("plugins", []):
                        try:
                            # Assuming format "module.ClassName"
                            module_name, class_name = plugin_path.rsplit(".", 1)
                            module = importlib.import_module(module_name)
                            plugin_cls = getattr(module, class_name)
                            if not any(isinstance(p, plugin_cls) for p in self.plugins):
                                self.plugins.append(plugin_cls())
                        except Exception as e:
                            print(f"   [PluginManager] Failed to load persistent plugin {plugin_path}: {e}")
            except Exception as e:
                print(f"   [PluginManager] Failed to read {PERSISTENT_PLUGINS_PATH}: {e}")

        # 3. Dynamic search in project-root 'plugins' directory
        root_plugins = discovery.discover_plugins_in_directory(config.PROJECT_ROOT / "plugins", BaseEvalPlugin)
        for p in root_plugins:
            if not any(isinstance(existing, p.__class__) for existing in self.plugins):
                self.plugins.append(p)

        # 4. Fallback for Internal Essential Plugins & Ecosystem Adapters
        # Industrial-Grade Discovery: Ensures core capabilities are loaded even if entry-points are shadowed.
        internal_manifest = []

        # -- Core Essentials --
        try:
            from .coverage_plugin import CoveragePlugin
            internal_manifest.append(CoveragePlugin)
        except ImportError:
            pass

        try:
            from .flight_recorder import FlightRecorderPlugin
            internal_manifest.append(FlightRecorderPlugin)
        except ImportError:
            pass

        try:
            from .reporting_plugin import ReportingPlugin
            internal_manifest.append(ReportingPlugin)
        except ImportError:
            pass

        try:
            from .artifact_plugin import ArtifactPlugin
            internal_manifest.append(ArtifactPlugin)
        except ImportError:
            pass

        try:
            from .publication_plugin import PublicationPlugin
            internal_manifest.append(PublicationPlugin)
        except ImportError:
            pass

        try:
            from .live_bridge_plugin import RemoteBridgePlugin
            internal_manifest.append(RemoteBridgePlugin)
        except ImportError:
            pass

        try:
            from .triage_plugin import TroubleshootingPlugin
            internal_manifest.append(TroubleshootingPlugin)
        except ImportError:
            pass

        # -- Ecosystem Adapters --
        try:
            from eval_runner.adapters.openai import OpenAIAdapterPlugin
            from eval_runner.adapters.gemini import GeminiAdapterPlugin
            from eval_runner.adapters.claude import ClaudeAdapterPlugin
            from eval_runner.adapters.ollama import OllamaAdapterPlugin
            from eval_runner.adapters.grok import GrokAdapterPlugin
            from eval_runner.adapters.autogen import AutoGenAdapterPlugin
            from eval_runner.adapters.crewai import CrewAIAdapterPlugin
            from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
            from eval_runner.adapters.langchain import LangChainAdapterPlugin

            internal_manifest.extend([
                OpenAIAdapterPlugin, GeminiAdapterPlugin, ClaudeAdapterPlugin,
                OllamaAdapterPlugin, GrokAdapterPlugin, AutoGenAdapterPlugin,
                CrewAIAdapterPlugin, LangGraphAdapterPlugin, LangChainAdapterPlugin
            ])
        except ImportError:
            pass

        # Robust Instantiation Loop (Zero-Touch Isolation)
        for PluginClass in internal_manifest:
            try:
                # Deduplication: Only load if an instance of this class doesn't exist
                if not any(isinstance(p, PluginClass) for p in self.plugins):
                    self.plugins.append(PluginClass())
            except Exception as e:
                # Log isolated failure without crashing the manager
                print(f"   [PluginManager] Isolated Failure loading {PluginClass.__name__}: {e}")

        self._loaded = True

    def trigger(self, hook_name: str, *args, **kwargs):
        """Triggers a plugin hook across all loaded plugins with timeout."""
        self.load_plugins()
        for plugin in self.plugins:
            if hasattr(plugin, hook_name):
                try:
                    hook = getattr(plugin, hook_name)
                    _invoke_with_timeout(hook, *args, **kwargs)
                except Exception as e:
                    print(f"   [PluginManager] Error in {hook_name} for {plugin.__class__.__name__}: {e}")

    def trigger_interceptor(self, hook_name: str, *args, **kwargs) -> bool:
        """
        Triggers an interceptor hook and returns False if any plugin rejects the action.
        Defaults to True (allow).
        """
        self.load_plugins()
        for plugin in self.plugins:
            if hasattr(plugin, hook_name):
                try:
                    hook = getattr(plugin, hook_name)
                    result = hook(*args, **kwargs)
                    if result is False:
                        return False
                except Exception as e:
                    print(f"   [PluginManager] Error in interceptor {hook_name} for {plugin.__class__.__name__}: {e}")
        return True

    def register_persistent(self, plugin_path: str):
        """Register a plugin persistently by adding it to plugins.json."""
        PERSISTENT_PLUGINS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"plugins": []}
        if PERSISTENT_PLUGINS_PATH.exists():
            with open(PERSISTENT_PLUGINS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        
        if plugin_path not in data["plugins"]:
            data["plugins"].append(plugin_path)
            with open(PERSISTENT_PLUGINS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"   [Plugins] Persistent registration saved: {plugin_path}")
        else:
            print(f"   [Plugins] Plugin legacy already exists: {plugin_path}")

    def unregister_persistent(self, plugin_path: str):
        """Unregister a plugin persistently."""
        if not PERSISTENT_PLUGINS_PATH.exists():
            return
            
        with open(PERSISTENT_PLUGINS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        if plugin_path in data["plugins"]:
            data["plugins"].remove(plugin_path)
            with open(PERSISTENT_PLUGINS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"   [Plugins] Persistent registration removed: {plugin_path}")
        else:
            print(f"   [Plugins] Plugin not found in persistence: {plugin_path}")


manager = PluginManager()
