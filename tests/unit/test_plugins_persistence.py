import json
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.plugins import PluginManager


def test_plugin_registration_modern_schema(tmp_path, monkeypatch):
    """Verify that plugin registration follows the modern dictionary schema."""
    # Isolated path for testing
    registry_file = tmp_path / "config" / "plugins" / "registry.json"
    monkeypatch.setattr(config, "PLUGINS_CONFIG_PATH", registry_file)
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    manager = PluginManager()
    plugin_path = "eval_runner.plugins.flight_recorder.FlightRecorderPlugin"

    manager.register_persistent(plugin_path, plugin_id="recorder")

    assert registry_file.exists()
    with open(registry_file, encoding="utf-8") as f:
        data = json.load(f)

    assert "plugins" in data
    assert len(data["plugins"]) == 1
    p = data["plugins"][0]
    assert p["id"] == "recorder"
    assert p["name"] == "recorder"
    assert p["module"] == "eval_runner.plugins.flight_recorder"
    assert p["class"] == "FlightRecorderPlugin"
    assert p["enabled"] is True
    assert p["config"] == {}


def test_plugin_unregistration(tmp_path, monkeypatch):
    """Verify that plugins are correctly removed from the modern registry."""
    registry_file = tmp_path / "registry.json"
    monkeypatch.setattr(config, "PLUGINS_CONFIG_PATH", registry_file)
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    # Pre-populate
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    initial_data = {
        "plugins": [
            {
                "id": "p1",
                "name": "p1",
                "module": "mod",
                "class": "P1",
                "enabled": True,
                "config": {},
            },
            {
                "id": "p2",
                "name": "p2",
                "module": "mod",
                "class": "P2",
                "enabled": True,
                "config": {},
            },
        ]
    }
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)

    manager = PluginManager()
    manager.unregister_persistent("mod.P1")

    with open(registry_file, encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["id"] == "p2"


def test_strict_loading_malformed_registry(tmp_path, monkeypatch):
    """Verify that malformed registries trigger a descriptive forensic error."""
    registry_file = tmp_path / "bad_registry.json"
    monkeypatch.setattr(config, "PLUGINS_CONFIG_PATH", registry_file)
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    with open(registry_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json ]")

    manager = PluginManager()
    with pytest.raises(ValueError, match="CRITICAL: Failed to read forensic registry"):
        manager.load_plugins()


def test_loading_ignoring_disabled_plugins(tmp_path, monkeypatch):
    """Verify that disabled plugins are not instantiated during load."""
    registry_file = tmp_path / "registry.json"
    monkeypatch.setattr(config, "PLUGINS_CONFIG_PATH", registry_file)
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    # Using a dummy path that IS NOT in the internal manifest

    initial_data = {
        "plugins": [
            {
                "id": "dummy",
                "name": "dummy",
                "module": "test_mod",
                "class": "DummyPlugin",
                "enabled": False,
                "config": {},
            }
        ]
    }
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)

    manager = PluginManager()

    # Mocking the import to return a dummy class
    mock_plugin_cls = type("DummyPlugin", (), {})
    mock_module = MagicMock()
    mock_module.DummyPlugin = mock_plugin_cls

    with patch("importlib.import_module", return_value=mock_module):
        manager.load_plugins()

    # Should be empty because it's disabled in registry and not in internal manifest
    assert not any(p.__class__.__name__ == "DummyPlugin" for p in manager.plugins)
