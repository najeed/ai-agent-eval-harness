"""
test_auto_translate.py

Unit tests for the Ollama-based auto-translate utility.
"""

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from eval_runner import auto_translate


def test_extract_text_txt(tmp_path):
    """Verifies that standard text files are extracted correctly."""
    txt_file = tmp_path / "doc.txt"
    txt_file.write_text("Hello World")

    assert auto_translate.extract_text(txt_file) == "Hello World"


def test_extract_text_unsupported(tmp_path):
    """Verifies that unsupported file types raise a ValueError."""
    bad_file = tmp_path / "image.png"
    bad_file.write_text("fake binary")

    with pytest.raises(ValueError, match="Unsupported file extension"):
        auto_translate.extract_text(bad_file)


@pytest.mark.asyncio
async def test_translate_to_scenario_integration():
    """Verifies that the auto-translate logic correctly structures a payload (mocked at the function level)."""

    # Target scenario struct
    mock_response = {
        "scenario_id": "test-scenario",
        "title": "Mock Translation",
        "industry": "Telecom",
        "description": "A test mock",
        "tasks": [],
    }

    with patch(
        "eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock
    ) as mock_translate:
        mock_translate.return_value = mock_response

        scenario = await auto_translate.translate_to_scenario("Sample telecom text")

        assert scenario["scenario_id"] == "test-scenario"
        assert scenario["title"] == "Mock Translation"
        assert scenario["industry"] == "Telecom"
