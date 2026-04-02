import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from dataproc_engine.cli.main import cli, run_rotational_backup

def test_cli_backup_rotation_zenith():
    """Target CLI lines 17-41, 169-192."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        # 1. Create a dummy output file
        with open("test.jsonl", "w") as f:
            f.write("{}")
            
        # 2. Test rotation logic manually (Lines 17-41)
        archive = run_rotational_backup("test.jsonl", 2)
        assert archive is not None
        assert os.path.exists(archive)
        
        # 3. Test CLI conflict handling (Lines 169-185)
        with open("output.jsonl", "w") as f:
            f.write("{}")
            
        # Mock click.confirm to True
        with patch("click.confirm", return_value=True):
            result = runner.invoke(cli, ["extract", "--industry", "finance", "--source", "api", "--target-dir", ".", "--output-name", "output.jsonl"])
            assert "Archived existing file" in result.output

def test_cli_error_graceful_zenith():
    """Target CLI lines 210-212 (Graceful Error)."""
    runner = CliRunner()
    # Trigger exception in LLMManager init
    with patch("dataproc_engine.core.llm_manager.LLMManager.__init__", side_effect=Exception("CLAM_FAIL")):
        result = runner.invoke(cli, ["extract", "--industry", "finance"])
        assert "Error: Pipeline failed gracefully" in result.output
        assert result.exit_code == 1

def test_cli_file_source_validation_zenith():
    """Target CLI lines 70-72."""
    runner = CliRunner()
    result = runner.invoke(cli, ["extract", "--source", "file"]) # Missing --input-uri
    assert "Error: --input-uri" in result.output
    assert result.exit_code == 1

@pytest.mark.asyncio
async def test_unstructured_path_traversal_gap():
    """Target Unstructured lines 80-84 (Directory processing)."""
    from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
    from dataproc_engine.core.llm_manager import LLMManager
    
    config = {"industry": "unstructured", "unstructured_mode": "document", "input_uri": "test_dir", "allow_simulation": True}
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    with patch("os.path.isdir", return_value=True):
        with patch("os.listdir", return_value=["doc.txt"]):
                with patch("os.path.isfile", return_value=True):
                    with patch("os.path.exists", return_value=True):
                        with patch("builtins.open", MagicMock()):
                            artifacts = await provider.extract()
                            assert len(artifacts) > 0
