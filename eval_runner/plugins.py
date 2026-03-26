"""
plugins.py

Plugin management system for MultiAgentEval.
Handles dynamic discovery and loading of evaluation plugins.
Updated to respect Zero-Touch architecture and immutable core.
"""

from __future__ import annotations
import importlib.metadata
import concurrent.futures
from typing import List, Any, Optional
from . import config

PLUGIN_TIMEOUT = config.PLUGIN_TIMEOUT


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

    def before_evaluation(self, context: Any):
        """Hook called before the evaluation scenario begins."""
        pass

    def after_evaluation(self, context: Any, results: list):
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
        self._initialized = True

    def reset(self):
        """Resets the plugin manager state for tests."""
        self.plugins.clear()
        self._loaded = False

    def load_plugins(self):
        """Discovers and loads plugins from entry points."""
        if self._loaded:
            return

        # 1. Discover external plugins via entry points
        for entry_point in importlib.metadata.entry_points(group="eval_runner.plugins"):
            try:
                plugin_cls = entry_point.load()
                self.plugins.append(plugin_cls())
                # print(f"   [Plugins] Loaded plugin: {entry_point.name}")
            except Exception as e:
                # print(f"   [Plugins] Failed to load plugin {entry_point.name}: {e}")
                pass

        # 2. Fallback for internal essential plugins (Zero-Touch)
        internal_plugin_classes = []
        try:
            from .coverage_plugin import CoveragePlugin

            internal_plugin_classes.append(CoveragePlugin)
        except ImportError:
            pass
        try:
            from .live_bridge_plugin import RemoteBridgePlugin

            internal_plugin_classes.append(RemoteBridgePlugin)
        except ImportError:
            pass
        try:
            from .publication_plugin import PublicationPlugin

            internal_plugin_classes.append(PublicationPlugin)
        except ImportError:
            pass
        try:
            from .artifact_plugin import ArtifactPlugin

            internal_plugin_classes.append(ArtifactPlugin)
        except ImportError:
            pass
        try:
            from .triage_plugin import TroubleshootingPlugin

            internal_plugin_classes.append(TroubleshootingPlugin)
        except ImportError:
            pass

        # 3. Ecosystem Adapters & Internal Plugins (Zero-Touch core discovery)
        # These are explicitly loaded to ensure a single identity in the Singleton
        from eval_runner.adapters.openai import OpenAIAdapterPlugin
        from eval_runner.adapters.gemini import GeminiAdapterPlugin
        from eval_runner.adapters.claude import ClaudeAdapterPlugin
        from eval_runner.adapters.ollama import OllamaAdapterPlugin
        from eval_runner.adapters.grok import GrokAdapterPlugin
        from eval_runner.adapters.autogen import AutoGenAdapterPlugin
        from eval_runner.adapters.crewai import CrewAIAdapterPlugin
        from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
        from eval_runner.adapters.langchain import LangChainAdapterPlugin

        internal_plugin_classes += [
            OpenAIAdapterPlugin, GeminiAdapterPlugin, ClaudeAdapterPlugin,
            OllamaAdapterPlugin, GrokAdapterPlugin, AutoGenAdapterPlugin,
            CrewAIAdapterPlugin, LangGraphAdapterPlugin, LangChainAdapterPlugin
        ]
        
        for PluginClass in internal_plugin_classes:
            if not any(isinstance(p, PluginClass) for p in self.plugins):
                self.plugins.append(PluginClass())

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


manager = PluginManager()
