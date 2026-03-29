import pytest
from unittest.mock import patch, MagicMock
from eval_runner.handlers import environment

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.id = "std-1"
    args.name = "New Standard"
    args.industry = "finance"
    args.description = "No description provided"
    args.pack = "base-pack"
    args.force = False
    return args

def test_handle_registry_add(mock_args):
    """Test 'registry add' command handler. Forensic: Verify sync method call."""
    with patch("eval_runner.registry_sync.add_standard_to_registry") as mock_add:
        environment.handle_registry_add(mock_args)
        mock_add.assert_called_once_with("std-1", "New Standard", "finance", "No description provided")

def test_handle_registry_sync(mock_args):
    """Test 'registry sync' command handler. Forensic: Schema enforcement."""
    with patch("eval_runner.registry_sync.ensure_schema_sync") as mock_sync:
        environment.handle_registry_sync(mock_args)
        mock_sync.assert_called_once_with(force=True)

def test_handle_ci_generate(mock_args):
    """Test 'ci generate' command handler. Forensic: YAML manifest creation."""
    with patch("eval_runner.scaffold.generate_github_action") as mock_gen:
        environment.handle_ci_generate(mock_args)
        mock_gen.assert_called_once()

def test_handle_install(mock_args):
    """Test 'install' command handler. Forensic: Remote catalog fetch."""
    with patch("eval_runner.catalog.install_pack") as mock_install:
        environment.handle_install(mock_args)
        mock_install.assert_called_once_with("base-pack")
