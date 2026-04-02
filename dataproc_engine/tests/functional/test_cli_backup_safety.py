import pytest
import os
import glob
from click.testing import CliRunner
from dataproc_engine.cli.main import cli

def test_cli_extract_no_args():
    """Verify that CLI shows help when no args are provided."""
    runner = CliRunner()
    result = runner.invoke(cli, ["extract", "--help"])
    assert result.exit_code == 0
    assert "Run the extraction and transformation pipeline" in result.output

def test_cli_requires_input_uri_for_file_source():
    """Verify that --input-uri is mandatory for --source file."""
    runner = CliRunner()
    result = runner.invoke(cli, ["extract", "--source", "file"])
    assert result.exit_code == 1
    assert "Error: --input-uri" in result.output

def test_cli_rotational_backup_integration(tmp_path):
    """Verify that the CLI correctly triggers the rotational backup logic."""
    runner = CliRunner()
    target_dir = str(tmp_path / "output")
    os.makedirs(target_dir)
    output_file = os.path.join(target_dir, "finance_kb.jsonl")
    
    # 1. Create initial file
    with open(output_file, "w") as f: f.write('{"id": "old"}')
    
    # 2. Run extract with --overwrite (Mocking the pipeline to produce no results is fine here)
    # Run twice to trigger rotation message (max-backups=1 means 1st run creates 1st bak, 2nd run triggers rotation log if logic matches)
    # Actually, main.py prints message if total_backups >= max_backups.
    # So with max_backups=1:
    # 1st run: Rename old to Bak1. glob finds 1 bak. 1 >= 1 -> Prints message.
    result = runner.invoke(cli, [
        "extract", 
        "--industry", "finance", 
        "--llm-strategy", "mock", 
        "--limit", "1", 
        "--target-dir", target_dir, 
        "--overwrite",
        "--max-backups", "1"
    ])
    
    assert result.exit_code == 0
    assert "Archived existing file" in result.output
    assert "Rotation Policy Active" in result.output # New hardening log string
    
    # 3. Verify exactly 1 backup exists
    backups = glob.glob(f"{output_file}.*.bak")
    assert len(backups) == 1

def test_cli_unsupported_industry():
    """Verify graceful failure for unsupported industries."""
    runner = CliRunner()
    result = runner.invoke(cli, ["extract", "--industry", "unknown_industry"])
    assert result.exit_code == 1 # Now it returns 1 for unsupported industry
    assert "Error: API Source for 'unknown_industry' not supported" in result.output
