"""
Consolidated Plugin Test Suite for AgentV Evaluation Harness.
Verifies the PluginManager lifecycle, dynamic loading, interceptor logic,
provenance tracking, and persistent registry management.
"""

import json

from eval_runner.plugins import BaseEvalPlugin, PluginManager

# --- 1. Base Logic & Initialization ---


def test_pm_initial_state():
    pm = PluginManager()
    assert len(pm.plugins) == 0
    assert not pm._loaded


# --- 2. Dynamic Loading & Provenance ---


def test_plugins_manager_load_valid(tmp_path):
    pm = PluginManager()
    f = tmp_path / "valid_plugin.py"
    f.write_text("""
from eval_runner.plugins import BaseEvalPlugin
class CustomPlugin(BaseEvalPlugin): pass
""")
    metadata = pm.load(str(f))
    assert metadata["class"] == "CustomPlugin"
    assert "CustomPlugin" in pm.provenance_map


# --- 3. Interceptor & Hook Logic ---


def test_pm_trigger_interceptor():
    pm = PluginManager()

    class MutPlugin(BaseEvalPlugin):
        def hook(self, ctx, tool, args):
            return {"allowed": True, "tool_name": "shimmed"}

    pm.plugins.append(MutPlugin())
    res = pm.trigger_interceptor("hook", {}, "orig", {})
    assert res["tool_name"] == "shimmed"


# --- 4. Persistent Registry Management ---


def test_pm_persistent_registry(tmp_path, monkeypatch):
    from eval_runner import plugins

    reg_file = tmp_path / "reg.json"
    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", reg_file)
    pm = PluginManager()

    plugin_file = tmp_path / "my_plugin.py"
    plugin_file.write_text(
        "from eval_runner.plugins import BaseEvalPlugin\nclass P1(BaseEvalPlugin): pass"
    )

    pm.register_persistent(str(plugin_file))
    with open(reg_file) as f:
        assert any(p["class"] == "P1" for p in json.load(f)["plugins"])


# --- 5. Resilience & Finalization ---


def test_pm_finalize_robustness():
    pm = PluginManager()

    class BuggyPlugin(BaseEvalPlugin):
        def finalize_run(self):
            raise Exception("Crash")

        def cleanup(self):
            raise Exception("Leak")

    pm.plugins.append(BuggyPlugin())
    pm.finalize()  # Should handle errors gracefully
