import pytest
from eval_runner.plugins import manager, BaseEvalPlugin
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reporting_plugin import ReportingPlugin
from eval_runner.coverage_plugin import CoveragePlugin

def test_internal_plugins_are_loaded():
    """Verify that all essential internal plugins are discovered and instantiated."""
    manager.reset()
    manager.load_plugins(force=True)
    
    plugin_classes = [p.__class__ for p in manager.plugins]
    
    # Assert essentials are present
    assert FlightRecorderPlugin in plugin_classes
    assert ReportingPlugin in plugin_classes
    assert CoveragePlugin in plugin_classes
    
    # Assert overall count (Adapters + Essentials > 10)
    assert len(manager.plugins) >= 15

def test_plugin_deduplication():
    """Verify that plugins are not double-loaded."""
    manager.reset()
    manager.load_plugins(force=True)
    initial_count = len(manager.plugins)
    
    # Second load should not add anything
    manager.load_plugins(force=False)
    assert len(manager.plugins) == initial_count
