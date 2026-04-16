import pytest

from eval_runner.plugins import BaseEvalPlugin, PluginManager


def test_plugins_base_diagnose_failure():
    class ExtPlugin(BaseEvalPlugin):
        pass

    p = ExtPlugin()
    p.on_diagnose_failure({})


def test_plugins_manager_load_missing_path(tmp_path):
    pm = PluginManager()
    with pytest.raises(FileNotFoundError):
        pm.load(str(tmp_path / "missing.py"))


def test_plugins_manager_load_no_spec(tmp_path, monkeypatch):
    pm = PluginManager()
    f = tmp_path / "valid.py"
    f.write_text("class NotAPlugin: pass")
    import importlib.util

    def mock_spec(*args, **kwargs):
        class MockSpec:
            loader = None

        return MockSpec()

    with monkeypatch.context() as m:
        m.setattr(importlib.util, "spec_from_file_location", mock_spec)
        with pytest.raises(ImportError):
            pm.load(str(f))


def test_plugins_manager_load_valid(tmp_path, monkeypatch):
    pm = PluginManager()
    f = tmp_path / "valid_plugin.py"
    f.write_text("""
from eval_runner.plugins import BaseEvalPlugin
class CustomPlugin(BaseEvalPlugin):
    pass
""")
    metadata = pm.load(str(f))
    assert metadata["class"] == "CustomPlugin"
    assert metadata["origin"] == "EXTERNAL"
    assert "CustomPlugin" in pm.provenance_map

    # 127-130 already loaded coverage
    import inspect

    def mock_getmembers(module, predicate=None):
        class FakeClass(BaseEvalPlugin):
            __module__ = module.__name__

        plugin_instance = pm.plugins[0]
        # Return the exact class object
        return [("CustomPlugin", plugin_instance.__class__)]

    with monkeypatch.context() as m:
        m.setattr(inspect, "getmembers", mock_getmembers)
        meta2 = pm.load(str(f))
        assert meta2["class"] == "CustomPlugin"
        assert len(pm.plugins) == 1


def test_plugins_manager_load_no_valid_plugin(tmp_path):
    pm = PluginManager()
    f = tmp_path / "junk.py"
    f.write_text("class RandomClass:\n  pass")
    with pytest.raises(ValueError, match="No valid BaseEvalPlugin"):
        pm.load(str(f))
