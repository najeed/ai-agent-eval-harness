import json

import pytest

from eval_runner.plugins import PluginManager


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    return registry_file


def test_discovery_camelcase_heuristic(isolated_registry, tmp_path):
    """Verify discovery works via CamelCase heuristic when no inheritance is present."""
    plugin_file = tmp_path / "my_custom_plugin.py"
    plugin_file.write_text("class MyCustomPlugin: pass")

    manager = PluginManager()
    manager.register_persistent(str(plugin_file))

    with open(isolated_registry) as f:
        data = json.load(f)
        p = data["plugins"][0]
        assert p["module"] == "my_custom_plugin"
        assert p["class"] == "MyCustomPlugin"


def test_discovery_inheritance_match(isolated_registry, tmp_path):
    """Verify discovery works via inheritance even if name doesn't match stem."""
    plugin_file = tmp_path / "adapter.py"
    # Inheriting from ABC to satisfy the introspective check
    plugin_file.write_text("from abc import ABC\nclass SpecAdapter(ABC): pass")

    manager = PluginManager()
    manager.register_persistent(str(plugin_file))

    with open(isolated_registry) as f:
        data = json.load(f)
        p = data["plugins"][0]
        assert p["module"] == "adapter"
        assert p["class"] == "SpecAdapter"


def test_discovery_ambiguity_failure(isolated_registry, tmp_path):
    """Verify that multiple candidate classes trigger an error."""
    plugin_file = tmp_path / "multi_plugin.py"
    plugin_file.write_text("from abc import ABC\nclass P1(ABC): pass\nclass P2(ABC): pass")

    manager = PluginManager()
    with pytest.raises(ValueError, match="Ambiguous plugin file"):
        manager.register_persistent(str(plugin_file))


def test_path_aware_unregistration(isolated_registry, tmp_path):
    """Verify unregistration handles file paths by normalizing them to stems."""
    plugin_file = tmp_path / "to_remove.py"

    # Pre-populate registry with a path-based registration entry
    initial_data = {
        "plugins": [
            {
                "id": "to_remove",
                "name": "to_remove",
                "module": "to_remove",
                "class": "ToRemovePlugin",
                "enabled": True,
                "config": {},
            }
        ]
    }
    with open(isolated_registry, "w") as f:
        json.dump(initial_data, f)

    manager = PluginManager()
    # Unregister using the full file path
    manager.unregister_persistent(str(plugin_file))

    with open(isolated_registry) as f:
        data = json.load(f)
        assert len(data["plugins"]) == 0
