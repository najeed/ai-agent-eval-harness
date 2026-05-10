from unittest.mock import MagicMock, patch

from eval_runner.publication_suite.bundle import Bundler


def test_bundler_create_bundle_success(tmp_path):
    batch_dir = tmp_path / "batch_1"
    batch_dir.mkdir()

    # Mock manager and ArtifactPlugin
    mock_plugin = MagicMock()
    mock_plugin.bundle_artifacts.return_value = {"status": "success", "bundle_path": "bundle.zip"}

    with patch("eval_runner.publication_suite.bundle.manager") as mock_manager:
        # We need manager.plugins to contain our mock_plugin
        mock_manager.plugins = [mock_plugin]

        # We also need to mock the ArtifactPlugin class check
        # Since we can't easily mock isinstance(p, ArtifactPlugin) without the actual class,
        # we'll mock the next() call or just ensure the mock is compatible.
        with patch("eval_runner.publication_suite.bundle.ArtifactPlugin"):
            # This makes isinstance(mock_plugin, ArtifactPlugin) return True
            with patch("eval_runner.publication_suite.bundle.isinstance", return_value=True):
                bundler = Bundler(str(batch_dir))
                bundler.create_bundle()

                mock_plugin.bundle_artifacts.assert_called_once()
                args, kwargs = mock_plugin.bundle_artifacts.call_args
                assert kwargs["target_dir"] == str(batch_dir)


def test_bundler_plugin_not_found(tmp_path):
    batch_dir = tmp_path / "batch_1"
    batch_dir.mkdir()

    with patch("eval_runner.publication_suite.bundle.manager") as mock_manager:
        mock_manager.plugins = []  # No plugins

        bundler = Bundler(str(batch_dir))
        with patch("eval_runner.publication_suite.bundle.print") as mock_print:
            bundler.create_bundle()
            mock_print.assert_any_call(
                "\u274c [Bundler CLI] Error: ArtifactPlugin not found in core."
            )


def test_bundler_failure_status(tmp_path):
    batch_dir = tmp_path / "batch_1"
    batch_dir.mkdir()

    mock_plugin = MagicMock()
    mock_plugin.bundle_artifacts.return_value = {"status": "error", "message": "Failed"}

    with patch("eval_runner.publication_suite.bundle.manager") as mock_manager:
        mock_manager.plugins = [mock_plugin]
        with patch("eval_runner.publication_suite.bundle.isinstance", return_value=True):
            bundler = Bundler(str(batch_dir))
            with patch("eval_runner.publication_suite.bundle.print") as mock_print:
                bundler.create_bundle()
                mock_print.assert_any_call("\u274c [Bundler CLI] Failure: Failed")
