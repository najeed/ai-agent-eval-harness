from __future__ import annotations
"""
plugins.py

Plugin management system for OpenCore.
Allows discovery and loading of external evaluation plugins.
Updated to support typed contexts.
"""

import importlib.metadata
from typing import List, Any
from .context import EvaluationContext, TurnContext

class BaseEvalPlugin:
    """Base class for evaluation plugins."""
    
    def before_evaluation(self, context: EvaluationContext):
        """Called before the evaluation starts."""
        pass
    
    def on_agent_turn_start(self, context: TurnContext):
        """Called before an agent turn begins."""
        pass

    def on_turn_end(self, context: TurnContext):
        """Called after each turn."""
        pass
    
    def on_tool_request(self, context: TurnContext, tool_name: str, args: dict) -> bool:
        """Allows intercepting and blocking tool calls. Return False to block."""
        return True

    def on_tool_result(self, context: TurnContext, tool_name: str, result: dict):
        """Called after a tool execution."""
        pass

    def on_error(self, context: Any, exception: Exception):
        """Called when an unhandled exception occurs in the engine."""
        pass

    def on_discover_adapters(self, registry: dict):
        """Allows plugins to register custom agent adapters."""
        pass

    def on_metrics_calculated(self, context: EvaluationContext, results: list):
        """Called after metrics are calculated, but before finishing."""
        pass

    def after_evaluation(self, context: EvaluationContext, results: list):
        """Called after the evaluation is finished."""
        pass
    
    def extend_cli(self, parser):
        """Called to allow plugins to add CLI arguments."""
        pass

class PluginManager:
    """Discovers and manages evaluation plugins."""
    
    def __init__(self):
        self.plugins: List[BaseEvalPlugin] = []
        self.load_plugins()

    def load_plugins(self):
        """Discovers plugins via entry points."""
        # OpenCore looks for entry points in the 'eval_runner.plugins' group
        eps = importlib.metadata.entry_points()
        if hasattr(eps, 'select'):
            # Python 3.10+ select()
            group_eps = eps.select(group='eval_runner.plugins')
        else:
            # Older dict-like behavior
            group_eps = eps.get('eval_runner.plugins', [])
            
        for entry_point in group_eps:
            try:
                plugin_cls = entry_point.load()
                self.plugins.append(plugin_cls())
                # print(f"   [Plugins] Loaded plugin: {entry_point.name}")
            except Exception as e:
                # print(f"   [Plugins] Failed to load plugin {entry_point.name}: {e}")
                pass
        
        # Fallback: Always ensure CoveragePlugin is loaded for Phase 2
        try:
            from .coverage_plugin import CoveragePlugin
            if not any(isinstance(p, CoveragePlugin) for p in self.plugins):
                self.plugins.append(CoveragePlugin())
                # print("   [Plugins] Loaded internal plugin: coverage")
        except ImportError:
            pass

        # Phase 4: Discovery of built-in adapters as plugins
        self._load_internal_adapters()

    def _load_internal_adapters(self):
        """Discovers internal adapters and loads them as plugins."""
        import os
        from pathlib import Path
        adapter_dir = Path(__file__).parent / "adapters"
        if not adapter_dir.exists():
            return

        for file in adapter_dir.glob("*.py"):
            if file.name == "__init__.py":
                continue
            
            try:
                module_name = f".adapters.{file.stem}"
                module = importlib.import_module(module_name, package="eval_runner")
                # Look for classes inheriting from BaseEvalPlugin
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and issubclass(attr, BaseEvalPlugin) 
                        and attr is not BaseEvalPlugin):
                        if not any(isinstance(p, attr) for p in self.plugins):
                            self.plugins.append(attr())
                            # print(f"   [Plugins] Loaded internal adapter: {attr_name}")
            except Exception as e:
                # print(f"   [Plugins] Failed to load adapter {file.name}: {e}")
                pass

    def trigger(self, hook_name: str, *args, **kwargs):
        """Triggers a lifecycle hook on all loaded plugins."""
        for plugin in self.plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                try:
                    method(*args, **kwargs)
                except Exception as e:
                    print(f"   [Plugins] Error in plugin hook {hook_name}: {e}")

    def trigger_interceptor(self, hook_name: str, *args, **kwargs) -> bool:
        """Triggers a hook that can block progress (returns False if any plugin blocks)."""
        for plugin in self.plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                try:
                    if method(*args, **kwargs) is False:
                        return False
                except Exception as e:
                    print(f"   [Plugins] Error in interceptor hook {hook_name}: {e}")
        return True

    def register_arguments(self, parser):
        """Allows all plugins to add their own arguments."""
        from argparse import _ArgumentGroup
        group = parser.add_argument_group("Plugin Arguments")
        for plugin in self.plugins:
            plugin.extend_cli(group)

# Global plugin manager instance
manager = PluginManager()
