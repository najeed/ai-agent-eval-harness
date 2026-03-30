import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
import concurrent.futures
import time
from pathlib import Path
import sys

# SUT
import eval_runner.plugins as plugins

class MockPlugin(plugins.BaseEvalPlugin):
    def before_evaluation(self, context):
        self.called = True
        self.context = context

class TestPlugins(unittest.TestCase):

    def setUp(self):
        plugins.manager.reset()
        # Suppress prints for cleaner logs
        self.print_patch = patch("builtins.print")
        self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()

    def test_base_plugin_no_ops(self):
        # Cover lines 42, 46, 50, 54, 58 (ABC pass methods)
        p = plugins.BaseEvalPlugin()
        p.before_evaluation(None)
        p.after_evaluation(None, [])
        p.on_register_commands(None)
        p.on_discover_adapters(None)
        p.on_register_simulators({})

    def test_plugin_manager_singleton(self):
        m1 = plugins.PluginManager()
        m2 = plugins.PluginManager()
        self.assertIs(m1, m2)
        # Singleton check (hits already initialized return)
        m3 = plugins.PluginManager()
        self.assertIs(m1, m3)

    def test_invoke_with_timeout_success(self):
        def fast(): return "ok"
        res = plugins._invoke_with_timeout(fast)
        self.assertEqual(res, "ok")

    def test_invoke_with_timeout_failure(self):
        def slow(): time.sleep(2)
        with patch.object(plugins, "PLUGIN_TIMEOUT", 0.1):
            with self.assertRaises(concurrent.futures.TimeoutError):
                plugins._invoke_with_timeout(slow)

    @patch("eval_runner.plugins.importlib.metadata.entry_points")
    @patch("eval_runner.plugins.PERSISTENT_PLUGINS_PATH")
    @patch("eval_runner.plugins.discovery.discover_plugins_in_directory")
    def test_load_plugins_all_sources(self, mock_discover, mock_persistent_path, mock_ep):
        # 1. Entry points - one good, one broken (Lines 96-97)
        mock_entry_good = MagicMock()
        mock_entry_good.load.return_value = MockPlugin
        mock_entry_broken = MagicMock()
        mock_entry_broken.load.side_effect = Exception("Broken EP")
        mock_ep.return_value = [mock_entry_good, mock_entry_broken]
        
        # 2. Persistent - cover missing file (Line 100) and broken load (113)
        mock_persistent_path.exists.return_value = True
        mock_data = {"plugins": ["my_mod.MyPlugin", "broken_mod.Broken"]}
        m_open = mock_open(read_data=json.dumps(mock_data))
        
        # 3. Dynamic
        mock_discover.return_value = [MockPlugin()]
        
        # 4. Internal plugins - we want to hit the ImportError blocks (129-152)
        # We need to refined import_module mock to handle 'mock.patch' internals
        orig_import = plugins.importlib.import_module
        
        def import_side(name):
            if name.startswith("eval_runner"):
                 # Force ImportError for optional internal plugins
                 if any(x in name for x in ["coverage_plugin", "live_bridge", "publication", "artifact", "triage_plugin"]):
                     raise ImportError(f"Mocked missing optional: {name}")
                 # Return a realish mock for others or use original for core infrastructure if needed
                 # For our purposes, a MagicMock is fine.
                 return MagicMock()
            if "my_mod" in name:
                m = MagicMock()
                m.MyPlugin = MockPlugin
                return m
            if "broken_mod" in name:
                raise Exception("Import Boom")
            # For unittest.mock or other system modules, use original
            return orig_import(name)

        with patch("builtins.open", m_open):
             with patch("importlib.import_module", side_effect=import_side):
                # Ensure internal adapter classes can be instantiated
                with patch("eval_runner.adapters.openai.OpenAIAdapterPlugin", create=True) as m1:
                    with patch("eval_runner.adapters.gemini.GeminiAdapterPlugin", create=True) as m2:
                        plugins.manager.load_plugins()
                        self.assertTrue(len(plugins.manager.plugins) > 0)

    def test_trigger_hooks(self):
        p = MockPlugin()
        p.called = False
        plugins.manager.plugins = [p]
        plugins.manager._loaded = True
        
        plugins.manager.trigger("before_evaluation", context="ctx")
        self.assertTrue(p.called)
        
        # Error in hook (Line 189)
        with patch.object(plugins, "_invoke_with_timeout", side_effect=Exception("Hook Boom")):
            plugins.manager.trigger("before_evaluation", context="ctx")

    def test_trigger_interceptor(self):
        p1 = MagicMock()
        p1.check.return_value = True
        p2 = MagicMock()
        p2.check.return_value = False
        
        plugins.manager.plugins = [p1, p2]
        plugins.manager._loaded = True
        
        # Rejection by p2 (Line 203)
        res = plugins.manager.trigger_interceptor("check")
        self.assertFalse(res) 
        
        # Exception in interceptor (Line 205) - loop continues
        p1.check.side_effect = Exception("Interceptor Boom")
        # Ensure p2 is still present and rejecting
        res = plugins.manager.trigger_interceptor("check")
        self.assertFalse(res) # Still False because p2 returned False after p1 boomed

        # Successfully continue through boom to allow-all
        p2.check.return_value = True
        res = plugins.manager.trigger_interceptor("check")
        self.assertTrue(res) # True because p1 boomed (silently ignored) and p2 said True

    @patch("eval_runner.plugins.PERSISTENT_PLUGINS_PATH")
    def test_persistence_lifecycle(self, mock_path):
        mock_path.exists.return_value = True
        mock_path.parent = MagicMock()
        
        # Registration with existing file
        m_existing = mock_open(read_data=json.dumps({"plugins": ["existing.P"]}))
        with patch("builtins.open", m_existing):
            plugins.manager.register_persistent("new.P")
            # Already exists (Line 222)
            plugins.manager.register_persistent("existing.P")
            
        # Unregistration missing path (Line 238)
        mock_path.exists.return_value = True
        m_unregister = mock_open(read_data=json.dumps({"plugins": ["some.P"]}))
        with patch("builtins.open", m_unregister):
            plugins.manager.unregister_persistent("missing.P")

if __name__ == '__main__':
    unittest.main()
