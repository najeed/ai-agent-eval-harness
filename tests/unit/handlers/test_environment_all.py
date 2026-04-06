import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# SUT
import eval_runner.handlers.environment as handlers


@pytest.fixture
def args():
    return MagicMock()


@pytest.fixture
def tmp_dir():
    td = tempfile.mkdtemp()
    old_cwd = os.getcwd()
    os.chdir(td)
    yield td
    os.chdir(old_cwd)
    shutil.rmtree(td)


@pytest.fixture
def clean_args(tmp_dir):
    args = MagicMock()
    return args


class TestEnvironmentHandlers:
    @pytest.mark.asyncio
    async def test_handle_analyze(self, clean_args, tmp_dir):
        from unittest.mock import AsyncMock, patch

        mock_analyze = AsyncMock()
        with patch("eval_runner.analyzer.analyze_repo", mock_analyze):
            clean_args.url = "http://repo"
            await handlers.handle_analyze(clean_args)
            mock_analyze.assert_called_with("http://repo")

    @pytest.mark.asyncio
    async def test_handle_init_standard(self, clean_args):
        with patch("eval_runner.scaffold.init_standard") as mock_init:
            clean_args.standard = "healthcare"
            await handlers.handle_init(clean_args)
            mock_init.assert_called_with("healthcare")

    @pytest.mark.asyncio
    async def test_handle_init_scaffold(self, clean_args):
        with patch("eval_runner.scaffold.scaffold_benchmark") as mock_scaffold:
            clean_args.standard = None
            clean_args.dir = "my-bench"
            clean_args.industry = "telecom"
            clean_args.protocol = "http"
            await handlers.handle_init(clean_args)
            mock_scaffold.assert_called_with("my-bench", industry="telecom", protocol="http")

    @pytest.mark.asyncio
    async def test_handle_install(self, clean_args):
        with patch("eval_runner.catalog.install_pack") as mock_install:
            clean_args.pack = "fin-pack"
            await handlers.handle_install(clean_args)
            mock_install.assert_called_with("fin-pack")

    @pytest.mark.asyncio
    async def test_handle_registry_sync(self, clean_args):
        with patch("eval_runner.registry_sync.ensure_schema_sync") as mock_sync:
            await handlers.handle_registry_sync(clean_args)
            mock_sync.assert_called_with(force=True)

    @pytest.mark.asyncio
    async def test_handle_plugin_list(self, clean_args):
        with patch("eval_runner.plugins.manager.load_plugins") as mock_load:
            with patch(
                "eval_runner.plugins.manager.plugins",
                [MagicMock(__class__=MagicMock(__name__="TestPlugin"))],
            ):
                await handlers.handle_plugin_list(clean_args)
                mock_load.assert_called()

    @pytest.mark.asyncio
    async def test_handle_plugin_register_success(self, clean_args, tmp_dir):
        plugin_file = Path(tmp_dir) / "my_plugin.py"
        plugin_file.write_text("class MyPlugin: pass")
        clean_args.path = str(plugin_file)

        await handlers.handle_plugin_register(clean_args)

        manifest_path = Path(".aes/plugins.json")
        assert manifest_path.exists()
        with open(manifest_path) as f:
            data = json.load(f)
            assert str(plugin_file.resolve()) in data["plugins"]

    @pytest.mark.asyncio
    async def test_handle_plugin_unregister(self, clean_args, tmp_dir):
        manifest_dir = Path(".aes")
        manifest_dir.mkdir()
        manifest_path = manifest_dir / "plugins.json"
        target = str(Path(tmp_dir).resolve() / "p.py")
        with open(manifest_path, "w") as f:
            json.dump({"plugins": [target]}, f)

        clean_args.path = target
        await handlers.handle_plugin_unregister(clean_args)

        with open(manifest_path) as f:
            data = json.load(f)
            assert target not in data["plugins"]

    @pytest.mark.asyncio
    async def test_handle_doctor(self, clean_args):
        """Verify doctor handler awaits the internal run_doctor."""
        with patch("eval_runner.doctor.run_doctor", new_callable=AsyncMock) as mock_doctor:
            await handlers.handle_doctor(clean_args)
            mock_doctor.assert_awaited()

    def test_detect_framework_heuristics(self, tmp_dir):
        Path("langgraph.json").write_text("{}")
        assert handlers.detect_framework() == "LangGraph"
        os.remove("langgraph.json")

        Path("crew.py").write_text("")
        assert handlers.detect_framework() == "CrewAI"
        os.remove("crew.py")

        Path("requirements.txt").write_text("some-pkg\nlanggraph==1.0")
        assert handlers.detect_framework() == "LangGraph"

        Path("requirements.txt").write_text("requests")
        assert handlers.detect_framework() == "Custom"

    def test_list_industries(self):
        industries = handlers.list_industries()
        assert "finance" in industries
        assert len(industries) >= 8

    @pytest.mark.asyncio
    async def test_handle_registry_add(self, clean_args):
        with patch("eval_runner.registry_sync.add_standard_to_registry") as mock_add:
            clean_args.id = "s1"
            clean_args.industry = "healthcare"
            await handlers.handle_registry_add(clean_args)
            mock_add.assert_called()

    @pytest.mark.asyncio
    async def test_handle_registry_search(self, clean_args):
        with patch("eval_runner.handlers.scenarios.handle_catalog_search", new_callable=AsyncMock) as mock_search:
            await handlers.handle_registry_search(clean_args)
            mock_search.assert_awaited_with(clean_args)

    @pytest.mark.asyncio
    async def test_handle_ci_generate(self, clean_args):
        with patch("eval_runner.scaffold.generate_github_action") as mock_gen:
            await handlers.handle_ci_generate(clean_args)
            mock_gen.assert_called()

    @pytest.mark.asyncio
    async def test_handle_cleanup_runs(self, clean_args):
        with patch("eval_runner.cleaner.cleanup_traces") as mock_clean:
            clean_args.days = 7
            clean_args.force = False
            await handlers.handle_cleanup_runs(clean_args)
            mock_clean.assert_called_with(days=7, force=False)

    @pytest.mark.asyncio
    async def test_handle_export(self, clean_args):
        with patch("eval_runner.exporter.HFExporter.export") as mock_export:
            clean_args.input = "in"
            clean_args.output = "out"
            await handlers.handle_export(clean_args)
            mock_export.assert_called_with("in", "out")

    @pytest.mark.asyncio
    async def test_handle_failures_search(self, clean_args):
        with patch("eval_runner.failure_corpus.search") as mock_search:
            clean_args.query = "q"
            await handlers.handle_failures_search(clean_args)
            mock_search.assert_called_with("q")

    @pytest.mark.asyncio
    async def test_handle_auto_translate(self, tmp_dir):
        from unittest.mock import AsyncMock, patch

        mock_trans = AsyncMock()
        mock_save = MagicMock()
        mock_ext = MagicMock(return_value="txt")

        args = MagicMock()
        args.input = "in.pdf"
        args.industry = "finance"
        args.model = "m1"
        args.output = "out.json"

        with patch("eval_runner.auto_translate.extract_text", mock_ext):
            with patch("eval_runner.auto_translate.translate_to_scenario", mock_trans):
                with patch("eval_runner.auto_translate.save_scenario", mock_save):
                    mock_trans.return_value = {"scen": 1}
                    await handlers.handle_auto_translate(args)
                    mock_ext.assert_called_with("in.pdf")
                    mock_trans.assert_called_with("txt", industry="finance", model="m1")

    @pytest.mark.asyncio
    async def test_handle_plugin_register_errors(self, clean_args, tmp_dir):
        clean_args.path = "missing_p.py"
        with patch("builtins.print") as mock_print:
            await handlers.handle_plugin_register(clean_args)
            last_call = mock_print.call_args_list[-1][0][0]
            assert "does not exist" in last_call

        manifest_dir = Path(".aes")
        manifest_dir.mkdir(exist_ok=True)
        manifest_path = manifest_dir / "plugins.json"
        p_path = Path(tmp_dir).resolve() / "p.py"
        p_path.touch()
        with open(manifest_path, "w") as f:
            json.dump({"plugins": [str(p_path)]}, f)

        clean_args.path = str(p_path)
        with patch("builtins.print") as mock_print:
            await handlers.handle_plugin_register(clean_args)
            mock_print.assert_called()

    @pytest.mark.asyncio
    async def test_handle_plugin_unregister_missing(self, clean_args, tmp_dir):
        clean_args.path = "any.py"
        with patch("builtins.print") as mock_print:
            await handlers.handle_plugin_unregister(clean_args)
            mock_print.assert_called()

        manifest_dir = Path(".aes")
        manifest_dir.mkdir(exist_ok=True)
        manifest_path = manifest_dir / "plugins.json"
        with open(manifest_path, "w") as f:
            json.dump({"plugins": []}, f)

        clean_args.path = "missing.py"
        with patch("builtins.print") as mock_print:
            await handlers.handle_plugin_unregister(clean_args)
            last_call = mock_print.call_args_list[-1][0][0]
            assert "not found in manifest" in last_call


if __name__ == "__main__":
    unittest.main()
