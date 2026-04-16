import json
import sys

import pytest

from eval_runner.plugins import BaseEvalPlugin, PluginManager


@pytest.fixture
def clean_pm():
    return PluginManager()


def test_pm_internal_imports(tmp_path, monkeypatch):
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


def test_pm_robust_instantiation_failure(tmp_path, clean_pm):
    class BadPlugin:
        def __init__(self):
            raise Exception("Instantiation Failed!")

    clean_pm._loaded = False
    clean_pm.load_plugins()
    # It logs isolated failure without crashing the manager


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


def test_pm_load_valid_definition_hit(tmp_path, clean_pm, monkeypatch):
    import eval_runner.plugins as plugins

    registry_file = tmp_path / "custom_registry.json"
    registry_file.write_text(json.dumps({"plugins": [{"module": "sys", "class": "exit"}]}))
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", False)
    clean_pm.load_plugins(force=True)


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

    # 510: multiple candidates, one match heuristic
    ambig_file = tmp_path / "ambig2.py"
    ambig2_content = (
        "from eval_runner.plugins import BaseEvalPlugin\n"
        "class Ambig2Plugin(BaseEvalPlugin): pass\n"
        "class OtherThing(BaseEvalPlugin): pass"
    )
    ambig_file.write_text(ambig2_content)
    # heuristic_base = Ambig2, heuristic_candidates = {Ambig2, Ambig2Plugin}
    # intersection will be Ambig2Plugin!
    clean_pm.register_persistent(str(ambig_file))

    # 518: no class_name resolved inside inspect block
    no_cls_file = tmp_path / "no_cls.py"
    no_cls_file.write_text("class NoInherit: pass")
    clean_pm.register_persistent(str(no_cls_file))

    # 523: Exception inside introspection
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("import sys\nsys.exit(1)")
    with monkeypatch.context() as m:
        # Prevent actual sys.exit from killing pytest, raise an inner exception instead
        def mock_exit(*args):
            raise RuntimeError("Fail introspection")

        m.setattr(sys, "exit", mock_exit)
        clean_pm.register_persistent(str(bad_file))
