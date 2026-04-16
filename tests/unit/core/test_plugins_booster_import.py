import json

import pytest

from eval_runner.plugins import PluginManager


@pytest.fixture
def clean_pm():
    pm = PluginManager()
    return pm


def test_pm_load_plugins_registry_drift(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "custom_registry.json"
    registry_file.write_text(json.dumps({"plugins": [{"module": "sys", "class": "exit"}]}))
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", False)

    class MockValidator:
        def __init__(self, *args, **kwargs):
            pass

        def validate(self, *args, **kwargs):
            raise Exception("Registry Drift Test")

    with monkeypatch.context() as m:
        import jsonschema.validators

        m.setattr(jsonschema.validators, "validator_for", lambda x: MockValidator)
        clean_pm.load_plugins(force=True)


def test_pm_load_plugins_invalid_definition(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "custom_registry.json"
    registry_file.write_text(
        json.dumps(
            {
                "plugins": [
                    {"enabled": False},
                    {"module": "sys"},
                    {"module": "non_existent_module", "class": "BadClass"},
                ]
            }
        )
    )
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", False)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", False)
    clean_pm.load_plugins(force=True)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", True)
    with pytest.raises(ValueError):
        clean_pm.load_plugins(force=True)


def test_pm_load_plugins_root_directory(tmp_path, clean_pm, monkeypatch):
    import eval_runner.config as config
    import eval_runner.discovery as discovery

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    class DummyPlugin:
        pass

    monkeypatch.setattr(
        discovery, "discover_plugins_in_directory", lambda *args, **kwargs: [DummyPlugin()]
    )
    clean_pm.load_plugins(force=True)
    assert len(clean_pm.plugins) >= 1


def test_pm_load_plugins_internal_import_fallback(clean_pm, monkeypatch):
    import sys

    with monkeypatch.context() as m:
        for m_name in [
            "eval_runner.coverage_plugin",
            "eval_runner.flight_recorder",
            "eval_runner.reporting_plugin",
            "eval_runner.artifact_plugin",
            "eval_runner.publication_plugin",
            "eval_runner.live_bridge_plugin",
            "eval_runner.triage_plugin",
        ]:
            m.setitem(sys.modules, m_name, None)

        clean_pm.load_plugins(force=True)
