"""
test_gen_demo_assets.py

Unit tests for the generate_assets utility.
Verifies file generation and timestamp shifting for demo traces.
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch
from eval_runner.console import gen_demo_assets

def test_generate_assets_success(tmp_path):
    """Verifies that demo assets are physically created in the runs directory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    
    # Patch config.RUN_LOG_DIR to point to our temp runs dir
    with patch("eval_runner.config.RUN_LOG_DIR", str(runs_dir)):
        gen_demo_assets.generate_assets()
        
    # Verify files created
    files = list(runs_dir.glob("*.json"))
    assert len(files) > 0
    
    # Check one file content
    first_file = files[0]
    content = first_file.read_text()
    assert "timestamp" in content
    assert "event" in content
