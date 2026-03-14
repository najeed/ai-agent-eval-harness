"""
plugins.py

Plugin management system for AI Agent Eval Harness.
Handles dynamic discovery and loading of evaluation plugins.
Updated to respect Zero-Touch architecture and immutable core.
"""

from __future__ import annotations
import importlib.metadata
from typing import List, Any, Optional

class BaseEvalPlugin:
    """Base class for all evaluation plugins."""
    def before_evaluation(self, context: Any): pass
    def after_evaluation(self, context: Any, results: list): pass
    def on_register_commands(self, registry: Any): pass
    def on_discover_adapters(self, registry: Any): pass

class PluginManager:
    """Orchestrates plugin lifecycle."""

    def __init__(self):
        self.plugins: List[BaseEvalPlugin] = []
        self._loaded = False

    def load_plugins(self):
        """Discovers and loads plugins from entry points."""
        if self._loaded:
            return
        
        # 1. Discover external plugins via entry points
        for entry_point in importlib.metadata.entry_points(group='eval_harness.plugins'):
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
            from .live_bridge_plugin import LiveBridgePlugin
            internal_plugin_classes.append(LiveBridgePlugin)
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

        for PluginClass in internal_plugin_classes:
            if not any(isinstance(p, PluginClass) for p in self.plugins):
                self.plugins.append(PluginClass())

        self._loaded = True

    def trigger(self, hook_name: str, *args, **kwargs):
        """Triggers a plugin hook across all loaded plugins."""
        self.load_plugins()
        for plugin in self.plugins:
            if hasattr(plugin, hook_name):
                try:
                    hook = getattr(plugin, hook_name)
                    hook(*args, **kwargs)
                except Exception as e:
                    print(f"   [PluginManager] Error in {hook_name} for {plugin.__class__.__name__}: {e}")

manager = PluginManager()
