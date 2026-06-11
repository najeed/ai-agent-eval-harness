import concurrent.futures
import json
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.plugins import BaseEvalPlugin, PluginManager, _invoke_with_timeout

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_pm():
    return PluginManager()


# ---------------------------------------------------------------------------
# Internal Imports & Discovery robustness tests
# ---------------------------------------------------------------------------


def test_pm_internal_imports(monkeypatch):
    pm = PluginManager()

    core_modules = [
        "eval_runner.coverage_plugin",
        "eval_runner.flight_recorder",
        "eval_runner.reporting_plugin",
        "eval_runner.artifact_plugin",
        "eval_runner.publication_plugin",
        "eval_runner.live_bridge_plugin",
        "eval_runner.triage_plugin",
    ]

    adapter_modules = [
        "eval_runner.adapters.autogen",
        "eval_runner.adapters.claude",
        "eval_runner.adapters.crewai",
        "eval_runner.adapters.gemini",
        "eval_runner.adapters.grok",
        "eval_runner.adapters.langchain",
        "eval_runner.adapters.langgraph",
        "eval_runner.adapters.ollama",
        "eval_runner.adapters.openai",
    ]

    with monkeypatch.context() as m:
        for mod in core_modules + adapter_modules:
            m.setitem(sys.modules, mod, None)
        pm.load_plugins(force=True)

    with monkeypatch.context() as m:
        m.setitem(sys.modules, "eval_runner.adapters.autogen", None)
        pm.load_plugins(force=True)


def test_pm_robust_instantiation_failure(clean_pm):
    class BadPlugin:
        def __init__(self):
            raise Exception("Instantiation Failed!")

    clean_pm._loaded = False
    clean_pm.load_plugins()


# ---------------------------------------------------------------------------
# finalize / cleanup tests
# ---------------------------------------------------------------------------


def test_pm_finalize_hooks(clean_pm):
    class F1(BaseEvalPlugin):
        def finalize_run(self):
            pass

    class F2(BaseEvalPlugin):
        def finalize_run(self):
            raise Exception("F2 Error")

    class C1(BaseEvalPlugin):
        def cleanup(self):
            pass

    class C2(BaseEvalPlugin):
        def cleanup(self):
            raise Exception("C2 Error")

    clean_pm.plugins.extend([F1(), F2(), C1(), C2()])
    clean_pm.finalize()


def test_pm_finalize_plugin_with_no_hooks(clean_pm):
    """finalize() silently skips plugins with neither finalize_run nor cleanup."""

    class SilentPlugin(BaseEvalPlugin):
        pass

    clean_pm.plugins.append(SilentPlugin())
    clean_pm.finalize()


# ---------------------------------------------------------------------------
# load_plugins — dynamic scenarios
# ---------------------------------------------------------------------------


def test_pm_load_valid_definition_hit(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "custom_registry.json"
    registry_file.write_text(json.dumps({"plugins": [{"module": "sys", "class": "exit"}]}))
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", False)
    clean_pm.load_plugins(force=True)


# ---------------------------------------------------------------------------
# Interceptor & Hook Execution Tests
# ---------------------------------------------------------------------------


def test_pm_trigger_interceptor(clean_pm):
    class MutPlugin(BaseEvalPlugin):
        def hook(self, ctx, tool, args):
            return {
                "allowed": True,
                "tool_name": "new_tool",
                "arguments": {"k": "v"},
                "short_circuit_result": 42,
            }

    class MutPlugin2(BaseEvalPlugin):
        def hook(self, ctx, tool, args):
            return {"allowed": False}

    class MutPluginErr(BaseEvalPlugin):
        def hook(self, ctx, tool, args):
            raise Exception("Err")

    clean_pm.plugins.extend([MutPlugin()])
    res1 = clean_pm.trigger_interceptor("hook", {}, "old_tool", {})
    assert res1["tool_name"] == "new_tool"
    assert res1["arguments"] == {"k": "v"}
    assert res1["short_circuit_result"] == 42

    clean_pm.plugins.append(MutPlugin2())
    res2 = clean_pm.trigger_interceptor("hook", {}, "old_tool", {})
    assert res2 is False

    clean_pm.plugins.clear()
    clean_pm.plugins.append(MutPluginErr())
    res3 = clean_pm.trigger_interceptor("hook", {}, "old_tool", {})
    assert res3 is True


# ---------------------------------------------------------------------------
# Persistence Registration & Unregistration
# ---------------------------------------------------------------------------


def test_pm_register_unregister_persistent_files(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "reg.json"
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    plugin_file = tmp_path / "my_super_plugin.py"
    plugin_content = (
        "from eval_runner.plugins import BaseEvalPlugin\n"
        "class SuperDuperPlugin(BaseEvalPlugin): pass\n"
        "class OtherClass: pass\n"
    )
    plugin_file.write_text(plugin_content)

    clean_pm.register_persistent(str(plugin_file))
    clean_pm.register_persistent(str(plugin_file))
    clean_pm.unregister_persistent(str(plugin_file))

    ambig_file = tmp_path / "ambig.py"
    ambig_content = (
        "from eval_runner.plugins import BaseEvalPlugin\n"
        "class APlugin(BaseEvalPlugin): pass\n"
        "class BPlugin(BaseEvalPlugin): pass"
    )
    ambig_file.write_text(ambig_content)
    with pytest.raises(ValueError, match="Ambiguous"):
        clean_pm.register_persistent(str(ambig_file))

    monkeypatch.setattr(plugins.Path, "exists", lambda self: False)
    clean_pm.unregister_persistent(str(plugin_file))


def test_pm_register_legacy(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "reg.json"
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    clean_pm.register_persistent("module.class")
    clean_pm.unregister_persistent("module.class")

    with pytest.raises(ValueError):
        clean_pm.register_persistent("module_path_without_dots_and_no_file")

    clean_pm.unregister_persistent("module_path_without_dots_and_no_file")


def test_pm_register_heuristics(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "reg.json"
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

    ambig_file = tmp_path / "ambig2.py"
    ambig2_content = (
        "from eval_runner.plugins import BaseEvalPlugin\n"
        "class Ambig2Plugin(BaseEvalPlugin): pass\n"
        "class OtherThing(BaseEvalPlugin): pass"
    )
    ambig_file.write_text(ambig2_content)
    clean_pm.register_persistent(str(ambig_file))

    no_cls_file = tmp_path / "no_cls.py"
    no_cls_file.write_text("class NoInherit: pass")
    clean_pm.register_persistent(str(no_cls_file))

    bad_file = tmp_path / "bad.py"
    bad_file.write_text("import sys\nsys.exit(1)")
    with monkeypatch.context() as m:

        def mock_exit(*args):
            raise RuntimeError("Fail introspection")

        m.setattr(sys, "exit", mock_exit)
        clean_pm.register_persistent(str(bad_file))


# --- Ported Coverage-Booster tests for eval_runner/plugins.py ---


def test_invoke_with_timeout_success():
    """_invoke_with_timeout returns the function's return value on success."""
    result = _invoke_with_timeout(lambda: 42)
    assert result == 42


def test_invoke_with_timeout_timeout(monkeypatch, capsys):
    """_invoke_with_timeout re-raises TimeoutError and prints a message."""
    import eval_runner.plugins as plugins_mod

    monkeypatch.setattr(plugins_mod, "PLUGIN_TIMEOUT", 0.001)

    def slow_func():
        time.sleep(10)

    with pytest.raises(concurrent.futures.TimeoutError):
        _invoke_with_timeout(slow_func)

    captured = capsys.readouterr()
    assert "Timeout" in captured.out


def test_load_plugins_ttl_debounce():
    """If loaded within 60s and force=False, scan is skipped."""
    pm = PluginManager()
    pm._loaded = True
    pm._last_load_time = time.time()

    original_len = len(pm.plugins)
    pm.load_plugins(force=False)
    assert len(pm.plugins) == original_len


def test_load_plugins_force_rescans():
    """force=True always triggers a re-scan even within 60s."""
    pm = PluginManager()
    pm._loaded = True
    pm._last_load_time = time.time()
    pm.load_plugins(force=True)
    assert pm._loaded is True


def test_load_plugins_entry_point_failure(monkeypatch, capsys, tmp_path):
    """Entry-point that fails to load is printed and skipped."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / ".isolated_plugins.json"
    reg_file.write_text(json.dumps({"plugins": []}))
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)

    bad_ep = MagicMock()
    bad_ep.name = "bad_plugin"
    bad_ep.load.side_effect = RuntimeError("Import failed")

    with (
        patch("importlib.metadata.entry_points", return_value=[bad_ep]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        pm.load_plugins(force=True)

    captured = capsys.readouterr()
    assert "bad_plugin" in captured.out or "Entry-point" in captured.out


def test_load_plugins_disabled_plugin_skipped(monkeypatch, tmp_path):
    """Plugins with enabled=false are skipped."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(
        json.dumps({"plugins": [{"module": "sys", "class": "exit", "enabled": False}]})
    )
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)
    monkeypatch.setattr(plugins_mod, "STRICT_PLUGINS", False)

    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        pm.load_plugins(force=True)

    assert not any(type(p).__name__ == "exit" for p in pm.plugins)


def test_load_plugins_malformed_definition_skipped(monkeypatch, tmp_path, capsys):
    """Plugin definition missing module/class is skipped with a warning."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(json.dumps({"plugins": [{"id": "bad", "name": "bad_plugin"}]}))
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)
    monkeypatch.setattr(plugins_mod, "STRICT_PLUGINS", False)

    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        pm.load_plugins(force=True)

    captured = capsys.readouterr()
    assert "malformed" in captured.out or "Skipping" in captured.out


def test_load_plugins_strict_mode_raises_on_failure(monkeypatch, tmp_path):
    """STRICT_PLUGINS=True causes load failure to raise ValueError."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(
        json.dumps(
            {
                "plugins": [
                    {"module": "nonexistent_module_xyz", "class": "FakeClass", "enabled": True}
                ]
            }
        )
    )
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)
    monkeypatch.setattr(plugins_mod, "STRICT_PLUGINS", True)

    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        with pytest.raises(ValueError, match="Failed to load plugin"):
            pm.load_plugins(force=True)


def test_load_plugins_non_strict_logs_failure(monkeypatch, tmp_path, capsys):
    """STRICT_PLUGINS=False prints failure and continues."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(
        json.dumps(
            {
                "plugins": [
                    {"module": "nonexistent_module_xyz", "class": "FakeClass", "enabled": True}
                ]
            }
        )
    )
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)
    monkeypatch.setattr(plugins_mod, "STRICT_PLUGINS", False)

    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        pm.load_plugins(force=True)

    captured = capsys.readouterr()
    assert "Failed to load" in captured.out or "nonexistent_module_xyz" in captured.out


def test_load_plugins_registry_read_failure(monkeypatch, tmp_path):
    """Corrupted registry file causes ValueError to be raised."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text("NOT VALID JSON {{{")
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)

    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm = PluginManager()
        with pytest.raises(ValueError, match="CRITICAL"):
            pm.load_plugins(force=True)


def test_register_duplicate_returns_false():
    """register() returns False if a plugin of the same class is already registered."""
    pm = PluginManager()

    class MyPlugin(BaseEvalPlugin):
        pass

    p = MyPlugin()
    assert pm.register(p, origin="CORE") is True
    assert pm.register(MyPlugin(), origin="CORE") is False
    assert len(pm.plugins) == 1


def test_record_provenance_builtin_fallback():
    """_record_provenance uses fallback for classes without physical source files."""
    pm = PluginManager()

    class DynPlugin(BaseEvalPlugin):
        pass

    with patch("inspect.getfile", side_effect=TypeError("builtin")):
        pm._record_provenance(DynPlugin())

    assert "DynPlugin" in pm.provenance_map
    assert pm.provenance_map["DynPlugin"]["path"] == "builtin"
    assert pm.provenance_map["DynPlugin"]["trusted"] is True


def test_trigger_on_discover_metrics_scoped_registry():
    """on_discover_metrics wraps the registry in a ScopedRegistry shim."""
    pm = PluginManager()

    registered_args = []

    class MetricPlugin(BaseEvalPlugin):
        def on_discover_metrics(self, registry):
            registry.register("my_metric")

    class MockRegistry:
        def register(self, name, source=None):
            registered_args.append((name, source))

    pm.plugins.append(MetricPlugin())
    pm._loaded = True

    with patch.object(pm, "load_plugins"):
        pm.trigger("on_discover_metrics", MockRegistry())

    assert len(registered_args) == 1
    assert registered_args[0][0] == "my_metric"
    assert registered_args[0][1] == "MetricPlugin"


def test_trigger_on_discover_metrics_scoped_registry_getattr():
    """ScopedRegistry delegates unknown attributes to the real registry."""
    pm = PluginManager()

    class MetricPlugin(BaseEvalPlugin):
        def on_discover_metrics(self, registry):
            _ = registry.some_custom_attr

    class MockRegistry:
        some_custom_attr = "custom_value"

        def register(self, name, source=None):
            pass

    pm.plugins.append(MetricPlugin())
    pm._loaded = True

    with patch.object(pm, "load_plugins"):
        pm.trigger("on_discover_metrics", MockRegistry())


def test_trigger_exception_caught(capsys):
    """Exceptions in plugin hooks are caught and printed."""
    pm = PluginManager()

    class BrokenPlugin(BaseEvalPlugin):
        def before_evaluation(self, ctx, span_context=None):
            raise RuntimeError("Hook crashed")

    pm.plugins.append(BrokenPlugin())
    pm._loaded = True

    with patch.object(pm, "load_plugins"):
        pm.trigger("before_evaluation", {})

    captured = capsys.readouterr()
    assert "Error" in captured.out or "BrokenPlugin" in captured.out


def test_trigger_interceptor_binary_false_returns_false():
    """If hook returns False, trigger_interceptor returns False immediately."""
    pm = PluginManager()

    class BlockPlugin(BaseEvalPlugin):
        def guard(self, ctx, tool, args):
            return False

    pm.plugins.append(BlockPlugin())
    pm._loaded = True

    with patch.object(pm, "load_plugins"):
        result = pm.trigger_interceptor("guard", {}, "tool_name", {})
    assert result is False


def test_trigger_interceptor_no_mutations_returns_true():
    """If no plugin has the hook or no mutations, returns True."""
    pm = PluginManager()
    pm._loaded = True

    with patch.object(pm, "load_plugins"):
        result = pm.trigger_interceptor("nonexistent_hook", {})
    assert result is True


def test_register_persistent_explicit_class_name(tmp_path, monkeypatch):
    """register_persistent with explicit class_name skips auto-discovery."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)

    pm = PluginManager()
    pm.register_persistent("my_module", class_name="MyClass")

    with open(reg_file) as f:
        data = json.load(f)

    assert any(p["module"] == "my_module" and p["class"] == "MyClass" for p in data["plugins"])


def test_unregister_persistent_by_id(tmp_path, monkeypatch, capsys):
    """unregister_persistent without dots or file path removes by id/name."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(
        json.dumps(
            {
                "plugins": [
                    {"id": "myplugin", "name": "myplugin", "module": "mymod", "class": "MyClass"}
                ]
            }
        )
    )
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)

    pm = PluginManager()
    pm.unregister_persistent("myplugin")

    with open(reg_file) as f:
        data = json.load(f)

    assert len(data["plugins"]) == 0


def test_unregister_persistent_not_found_prints(tmp_path, monkeypatch, capsys):
    """unregister_persistent prints message when no match found."""
    from eval_runner import plugins as plugins_mod

    reg_file = tmp_path / "reg.json"
    reg_file.write_text(json.dumps({"plugins": []}))
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)

    pm = PluginManager()
    pm.unregister_persistent("nonexistent")

    captured = capsys.readouterr()
    assert "No plugin found" in captured.out or "nonexistent" in captured.out


def test_pm_load_file_not_found():
    """load() raises FileNotFoundError for missing plugin file."""
    pm = PluginManager()
    with pytest.raises(FileNotFoundError):
        pm.load("/nonexistent/path/plugin.py")


def test_pm_load_no_base_plugin_subclass(tmp_path):
    """load() raises ValueError when no BaseEvalPlugin subclass is found."""
    pm = PluginManager()
    plugin_file = tmp_path / "no_plugin.py"
    plugin_file.write_text("class NotAPlugin: pass")

    with pytest.raises(ValueError, match="No valid BaseEvalPlugin"):
        pm.load(str(plugin_file))


def test_pm_load_returns_provenance_metadata(tmp_path):
    """load() returns full provenance metadata."""
    pm = PluginManager()
    plugin_file = tmp_path / "meta_plugin.py"
    plugin_file.write_text(
        "from eval_runner.plugins import BaseEvalPlugin\nclass MetaPlugin(BaseEvalPlugin): pass\n"
    )
    metadata = pm.load(str(plugin_file))
    assert metadata["class"] == "MetaPlugin"
    assert metadata["origin"] == "EXTERNAL"
    assert metadata["trusted"] is False
    assert "hash" in metadata
    assert "path" in metadata
    assert "MetaPlugin" in pm.provenance_map
    assert len(pm.plugins) == 1

    # To trigger the 'already loaded' branch in load() where isinstance(p, obj) is True,
    # we must ensure that the class obj found in module has the same class definition object.
    # By default, executing specs creates new class objects. We can mock inspect.getmembers
    # to return the exact class of the already registered plugin instance.
    existing_class = pm.plugins[0].__class__
    with patch("inspect.getmembers", return_value=[("MetaPlugin", existing_class)]):
        metadata2 = pm.load(str(plugin_file))
        assert metadata2["class"] == "MetaPlugin"
        assert len(pm.plugins) == 1


def test_base_eval_plugin_all_hooks_are_noop():
    """All BaseEvalPlugin hooks are no-ops."""

    class ConcretePlugin(BaseEvalPlugin):
        pass

    plugin = ConcretePlugin()
    plugin.before_evaluation(context={}, span_context={})
    plugin.after_evaluation(context={}, results=[], span_context={})
    plugin.on_register_commands(registry=None)
    plugin.on_discover_adapters(registry=None)
    plugin.on_register_simulators(registry={})
    plugin.on_discover_metrics(registry=None)
    plugin.on_diagnose_failure(taxonomy=None)


def test_load_plugins_missing_branches(tmp_path, monkeypatch):
    """Cover lines 264-269 (loading already registered or trusted flag mappings)
    and 343, 379-381 (instantiation failure warnings).
    """
    import eval_runner.plugins as plugins_mod

    # Cover 264-269 by registering a class and loading it from persistent registry
    reg_file = tmp_path / "reg.json"
    reg_file.write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "module": "tests.unit.core.test_plugin_logic",
                        "class": "DummyLoadPlugin",
                        "enabled": True,
                        "trusted": True,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(plugins_mod, "PERSISTENT_PLUGINS_PATH", reg_file)
    monkeypatch.setattr(plugins_mod, "STRICT_PLUGINS", False)

    pm = PluginManager()
    # Mock entry points and directories
    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
    ):
        pm.load_plugins(force=True)
    # The DummyLoadPlugin should have been instantiated and provenance mapped to trusted=True
    assert any(p.__class__.__name__ == "DummyLoadPlugin" for p in pm.plugins)
    assert pm.provenance_map["DummyLoadPlugin"]["trusted"] is True

    # Cover lines 379-381 (isolated failure loading internal manifest class)
    # Mock TroubleshootingPlugin import to raise an exception or instantiate incorrectly
    class BrokenInitPlugin(BaseEvalPlugin):
        def __init__(self):
            raise RuntimeError("Init crash")

    pm2 = PluginManager()
    with (
        patch("importlib.metadata.entry_points", return_value=[]),
        patch("eval_runner.discovery.discover_plugins_in_directory", return_value=[]),
        patch("eval_runner.plugins.PERSISTENT_PLUGINS_PATH", reg_file),
    ):
        # Inject TroubleshootingPlugin causing ImportError or dynamic class load crash
        with patch("eval_runner.plugins.manager.plugins", []):
            with patch("eval_runner.plugins.TroubleshootingPlugin", BrokenInitPlugin, create=True):
                pm2.load_plugins(force=True)  # Should not raise, warning logged


class DummyLoadPlugin(BaseEvalPlugin):
    pass


def test_pm_initial_state():
    pm = PluginManager()
    assert len(pm.plugins) == 0
    assert not pm._loaded


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
