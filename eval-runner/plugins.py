"""
plugins.py

Plugin management system for OpenCore.
Allows discovery and loading of external evaluation plugins.
Updated to support typed contexts.
"""

import importlib.metadata
from typing import List
from .context import EvaluationContext, TurnContext

class BaseEvalPlugin:
    """Base class for evaluation plugins."""
    
    def before_evaluation(self, context: EvaluationContext):
        """Called before the evaluation starts."""
        pass
    
    def on_turn_end(self, context: TurnContext):
        """Called after each turn."""
        pass
    
    def after_evaluation(self, results: list):
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
        eps = importlib.metadata.entry_points(group='eval_runner.plugins')
        for entry_point in eps:
            try:
                plugin_cls = entry_point.load()
                self.plugins.append(plugin_cls())
                print(f"   [Plugins] Loaded plugin: {entry_point.name}")
            except Exception as e:
                print(f"   [Plugins] Failed to load plugin {entry_point.name}: {e}")

    def trigger(self, hook_name: str, *args, **kwargs):
        """Triggers a lifecycle hook on all loaded plugins."""
        for plugin in self.plugins:
            method = getattr(plugin, hook_name, None)
            if method and callable(method):
                try:
                    method(*args, **kwargs)
                except Exception as e:
                    print(f"   [Plugins] Error in plugin hook {hook_name}: {e}")

# Global plugin manager instance
manager = PluginManager()
