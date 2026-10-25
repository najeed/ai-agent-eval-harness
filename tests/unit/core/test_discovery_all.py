"""Contract tests for the single Runtime discovery implementation."""

from agentv_runtime import discovery


class BaseTest:
    pass


class PluginOne(BaseTest):
    pass


def test_declared_plugins_are_loaded_by_the_runtime_discovery_contract():
    declaration = {
        "module": __name__,
        "class": "PluginOne",
        "enabled": True,
    }
    found = discovery.discover_declared_plugin_instances([declaration], BaseTest)
    assert isinstance(found[0][0], PluginOne)
    assert found[0][1] == declaration


def test_missing_project_plugin_directory_is_empty():
    assert discovery.discover_plugin_instances("missing-project-plugin-directory", BaseTest) == []
