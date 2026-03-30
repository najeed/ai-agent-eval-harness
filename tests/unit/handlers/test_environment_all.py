import unittest
from unittest.mock import MagicMock, patch, mock_open, AsyncMock
import json
import os
import asyncio
from pathlib import Path
import tempfile
import shutil

# SUT
import eval_runner.handlers.environment as handlers

class TestEnvironmentHandlers(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.args = MagicMock()
        self.tmp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp_dir)

    @patch("eval_runner.analyzer.analyze_repo", new_callable=AsyncMock)
    async def test_handle_analyze(self, mock_analyze):
        self.args.url = "http://repo"
        await handlers.handle_analyze(self.args)
        mock_analyze.assert_called_with("http://repo")

    @patch("eval_runner.scaffold.init_standard")
    def test_handle_init_standard(self, mock_init):
        self.args.standard = "healthcare"
        handlers.handle_init(self.args)
        mock_init.assert_called_with("healthcare")

    @patch("eval_runner.scaffold.scaffold_benchmark")
    def test_handle_init_scaffold(self, mock_scaffold):
        self.args.standard = None
        self.args.dir = "my-bench"
        self.args.industry = "telecom"
        self.args.protocol = "http"
        handlers.handle_init(self.args)
        mock_scaffold.assert_called_with("my-bench", industry="telecom", protocol="http")

    @patch("eval_runner.catalog.install_pack")
    def test_handle_install(self, mock_install):
        self.args.pack = "fin-pack"
        handlers.handle_install(self.args)
        mock_install.assert_called_with("fin-pack")

    @patch("eval_runner.registry_sync.ensure_schema_sync")
    def test_handle_registry_sync(self, mock_sync):
        handlers.handle_registry_sync(self.args)
        mock_sync.assert_called_with(force=True)

    @patch("eval_runner.plugins.manager.load_plugins")
    @patch("eval_runner.plugins.manager.plugins", [MagicMock(__class__=MagicMock(__name__="TestPlugin"))])
    def test_handle_plugin_list(self, mock_load):
        handlers.handle_plugin_list(self.args)
        mock_load.assert_called()

    def test_handle_plugin_register_success(self):
        plugin_file = Path(self.tmp_dir) / "my_plugin.py"
        plugin_file.write_text("class MyPlugin: pass")
        self.args.path = str(plugin_file)
        
        handlers.handle_plugin_register(self.args)
        
        manifest_path = Path(".aes/plugins.json")
        self.assertTrue(manifest_path.exists())
        with open(manifest_path, "r") as f:
            data = json.load(f)
            self.assertIn(str(plugin_file.resolve()), data["plugins"])

    def test_handle_plugin_unregister(self):
        manifest_dir = Path(".aes")
        manifest_dir.mkdir()
        manifest_path = manifest_dir / "plugins.json"
        target = str(Path(self.tmp_dir).resolve() / "p.py")
        with open(manifest_path, "w") as f:
            json.dump({"plugins": [target]}, f)
        
        self.args.path = target
        handlers.handle_plugin_unregister(self.args)
        
        with open(manifest_path, "r") as f:
            data = json.load(f)
            self.assertNotIn(target, data["plugins"])

    @patch("eval_runner.doctor.run_doctor", new_callable=AsyncMock)
    def test_handle_doctor_new_loop(self, mock_doctor):
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            with patch("asyncio.run") as mock_run:
                handlers.handle_doctor(self.args)
                mock_run.assert_called()

    @patch("eval_runner.doctor.run_doctor", new_callable=AsyncMock)
    def test_handle_doctor_existing_loop(self, mock_doctor):
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            handlers.handle_doctor(self.args)
            mock_loop.create_task.assert_called()

    def test_detect_framework_heuristics(self):
        Path("langgraph.json").write_text("{}")
        self.assertEqual(handlers.detect_framework(), "LangGraph")
        os.remove("langgraph.json")
        
        Path("crew.py").write_text("")
        self.assertEqual(handlers.detect_framework(), "CrewAI")
        os.remove("crew.py")
        
        Path("requirements.txt").write_text("some-pkg\nlanggraph==1.0")
        self.assertEqual(handlers.detect_framework(), "LangGraph")
        
        Path("requirements.txt").write_text("requests")
        self.assertEqual(handlers.detect_framework(), "Custom")

    def test_list_industries(self):
        industries = handlers.list_industries()
        self.assertIn("finance", industries)
        self.assertTrue(len(industries) >= 8)

    @patch("eval_runner.registry_sync.add_standard_to_registry")
    def test_handle_registry_add(self, mock_add):
        self.args.id = "s1"
        self.args.industry = "healthcare"
        handlers.handle_registry_add(self.args)
        mock_add.assert_called()

    @patch("eval_runner.handlers.scenarios.handle_catalog_search")
    def test_handle_registry_search(self, mock_search):
        handlers.handle_registry_search(self.args)
        mock_search.assert_called_with(self.args)

    @patch("eval_runner.scaffold.generate_github_action")
    def test_handle_ci_generate(self, mock_gen):
        handlers.handle_ci_generate(self.args)
        mock_gen.assert_called()

    @patch("eval_runner.cleaner.cleanup_traces")
    def test_handle_cleanup_runs(self, mock_clean):
        self.args.days = 7
        self.args.force = False
        handlers.handle_cleanup_runs(self.args)
        mock_clean.assert_called_with(days=7, force=False)

    @patch("eval_runner.exporter.HFExporter.export")
    def test_handle_export(self, mock_export):
        self.args.input = "in"
        self.args.output = "out"
        handlers.handle_export(self.args)
        mock_export.assert_called_with("in", "out")

    @patch("eval_runner.failure_corpus.search")
    def test_handle_failures_search(self, mock_search):
        self.args.query = "q"
        handlers.handle_failures_search(self.args)
        mock_search.assert_called_with("q")

    @patch("eval_runner.auto_translate.extract_text", return_value="txt")
    @patch("eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock)
    @patch("eval_runner.auto_translate.save_scenario")
    async def test_handle_auto_translate(self, mock_save, mock_trans, mock_ext):
        self.args.input = "in.pdf"
        self.args.industry = "finance"
        self.args.model = "m1"
        self.args.output = "out.json"
        mock_trans.return_value = {"scen": 1}
        await handlers.handle_auto_translate(self.args)
        mock_ext.assert_called_with("in.pdf")
        mock_trans.assert_called_with("txt", industry="finance", model="m1")

    def test_handle_plugin_register_errors(self):
        # Path not exists (Line 60-61)
        self.args.path = "missing_p.py"
        with patch("builtins.print") as mock_print:
            handlers.handle_plugin_register(self.args)
            # Check for substring since it resolves absolute path
            last_call = mock_print.call_args_list[-1][0][0]
            self.assertIn("does not exist", last_call)

        # Already registered (Line 81)
        manifest_dir = Path(".aes")
        manifest_dir.mkdir(exist_ok=True)
        manifest_path = manifest_dir / "plugins.json"
        p_path = Path(self.tmp_dir).resolve() / "p.py"
        p_path.touch()
        with open(manifest_path, "w") as f:
            json.dump({"plugins": [str(p_path)]}, f)
        
        self.args.path = str(p_path)
        with patch("builtins.print") as mock_print:
            handlers.handle_plugin_register(self.args)
            mock_print.assert_called_with(f"ℹ️  Plugin already registered: {p_path}")

    def test_handle_plugin_unregister_missing(self):
        # No manifest found (Line 89-90)
        self.args.path = "any.py"
        with patch("builtins.print") as mock_print:
            handlers.handle_plugin_unregister(self.args)
            mock_print.assert_called_with("ℹ️  No plugin manifest found (.aes/plugins.json).")

        # Plugin not found in manifest (Line 103-105)
        manifest_dir = Path(".aes")
        manifest_dir.mkdir(exist_ok=True)
        manifest_path = manifest_dir / "plugins.json"
        with open(manifest_path, "w") as f:
            json.dump({"plugins": []}, f)
        
        self.args.path = "missing.py"
        with patch("builtins.print") as mock_print:
            handlers.handle_plugin_unregister(self.args)
            # It resolves the path, so just check for the ❌ Error prefix
            mock_print.assert_any_call(unittest.mock.ANY)
            last_call = mock_print.call_args_list[-1][0][0]
            self.assertIn("not found in manifest", last_call)

if __name__ == '__main__':
    unittest.main()
