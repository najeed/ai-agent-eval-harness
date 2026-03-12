from __future__ import annotations
"""
plugins.py

Plugin management system for OpenCore.
Allows discovery and loading of external evaluation plugins.
Updated to support typed contexts.
"""

import importlib.metadata
import concurrent.futures
from typing import List, Any
from .context import EvaluationContext, TurnContext

# Security Guardrails: Halt Execution Mitigation
PLUGIN_TIMEOUT = 5.0

def _invoke_with_timeout(method, *args, **kwargs):
    """Wraps synchronous plugin hooks in a strict timeout."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(method, *args, **kwargs)
        try:
            return future.result(timeout=PLUGIN_TIMEOUT)
        except concurrent.futures.TimeoutError:
            print(f"   [Plugins] Timeout executing {method.__name__} after {PLUGIN_TIMEOUT}s")
            raise

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
    
    def on_register_commands(self, registry: Any):
        """Allows plugins to register custom CLI subcommands under their namespace."""
        pass

    def on_register_console_routes(self, app: Any, nav_registry: list):
        """Allows plugins to register custom Flask Blueprints and UI navigation links to the Admin Console API."""
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

        # Zero-Touch Live Bridge Fallback
        try:
            from .live_bridge_plugin import RemoteBridgePlugin
            if not any(isinstance(p, RemoteBridgePlugin) for p in self.plugins):
                self.plugins.append(RemoteBridgePlugin())
                # print("   [Plugins] Loaded internal plugin: live_bridge")
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
                    _invoke_with_timeout(method, *args, **kwargs)
                except Exception as e:
                    print(f"   [Plugins] Error in plugin hook {hook_name}: {e}")

    def trigger_interceptor(self, hook_name: str, *args, **kwargs) -> bool:
        """Triggers a hook that can block progress (returns False if any plugin blocks)."""
        for plugin in self.plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                try:
                    res = _invoke_with_timeout(method, *args, **kwargs)
                    if res is False:
                        return False
                except Exception as e:
                    print(f"   [Plugins] Error or Timeout in interceptor hook {hook_name}: {e}. Defaulting to True.")
        return True



# Global plugin manager instance
manager = PluginManager()
