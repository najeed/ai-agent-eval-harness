"""
test_auto_translate.py

Unit tests for the Ollama-based auto-translate utility.
"""

import pytest
import json
import sys
import aiohttp
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
from eval_runner import auto_translate


def test_extract_text_txt(tmp_path):
    """Verifies that standard text files are extracted correctly."""
    txt_file = tmp_path / "doc.txt"
    txt_file.write_text("Hello World", encoding="utf-8")
    assert auto_translate.extract_text(txt_file) == "Hello World"


def test_extract_text_unsupported(tmp_path):
    """Verifies that unsupported file types raise a ValueError."""
    bad_file = tmp_path / "image.png"
    bad_file.write_text("fake binary")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        auto_translate.extract_text(bad_file)


def test_extract_text_pdf_success(tmp_path):
    """Verifies successful PDF text extraction via PyPDF2 mocking."""
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_text("fake pdf content")

    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Extracted PDF Text"
    mock_reader.pages = [mock_page]

    with patch.dict("sys.modules", {"PyPDF2": MagicMock()}):
        import PyPDF2
        with patch("PyPDF2.PdfReader", return_value=mock_reader):
            assert auto_translate.extract_text(pdf_file) == "Extracted PDF Text"


def test_extract_text_docx_success(tmp_path):
    """Verifies successful DOCX text extraction via python-docx mocking."""
    docx_file = tmp_path / "doc.docx"
    docx_file.write_text("fake docx content")

    mock_doc = MagicMock()
    mock_para = MagicMock()
    mock_para.text = "Extracted DOCX Text"
    mock_doc.paragraphs = [mock_para]

    with patch.dict("sys.modules", {"docx": MagicMock()}):
        import docx
        with patch("docx.Document", return_value=mock_doc):
            assert auto_translate.extract_text(docx_file) == "Extracted DOCX Text"


def test_extract_text_pdf_import_error(tmp_path):
    """Verifies that an ImportError is raised when PyPDF2 is missing."""
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_text("fake pdf")
    with patch.dict("sys.modules", {"PyPDF2": None}):
        with pytest.raises(ImportError, match="PyPDF2 is required"):
            auto_translate.extract_text(pdf_file)


def test_extract_text_docx_import_error(tmp_path):
    """Verifies that an ImportError is raised when python-docx is missing."""
    docx_file = tmp_path / "doc.docx"
    docx_file.write_text("fake docx")
    with patch.dict("sys.modules", {"docx": None}):
        with pytest.raises(ImportError, match="python-docx is required"):
            auto_translate.extract_text(docx_file)


@pytest.mark.asyncio
async def test_translate_to_scenario_success():
    """Verifies successful translation with aiohttp mocking."""
    mock_json = {
        "response": json.dumps(
            {"scenario_id": "auto-123", "title": "Mock Title", "tasks": [{"task_id": "t1", "description": "do thing"}]}
        )
    }

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await auto_translate.translate_to_scenario("some text")
        assert result["scenario_id"] == "auto-123"
        assert result["title"] == "Mock Title"
        assert len(result["tasks"]) == 1


@pytest.mark.asyncio
async def test_translate_to_scenario_repair_missing_id():
    """Verifies that the logic repairs a missing scenario_id."""
    mock_json = {"response": json.dumps({"title": "No ID", "tasks": []})}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await auto_translate.translate_to_scenario("some text")
        assert result["scenario_id"].startswith("auto-")
        assert result["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_translate_to_scenario_missing_id_repair():
    """Verifies that translate_to_scenario repairs a missing scenario_id (line 108)."""
    mock_json = {"response": '{"title": "No ID"}'}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await auto_translate.translate_to_scenario("some text")
        assert result["scenario_id"].startswith("auto-")


@pytest.mark.asyncio
async def test_translate_to_scenario_markdown_json():
    """Verifies that the logic can extract JSON from markdown blocks."""
    mock_json = {"response": 'Here is the JSON:\n```json\n{"scenario_id": "md-123", "title": "MD"}\n```'}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value.__aenter__.return_value = mock_resp

        result = await auto_translate.translate_to_scenario("some text")
        assert result["scenario_id"] == "md-123"


@pytest.mark.asyncio
async def test_translate_to_scenario_connection_error():
    """Verifies error handling for connection failures."""
    with patch("aiohttp.ClientSession.post", side_effect=aiohttp.ClientConnectorError(MagicMock(), MagicMock())):
        with pytest.raises(ConnectionError, match="Could not connect to Ollama"):
            await auto_translate.translate_to_scenario("some text")


@pytest.mark.asyncio
async def test_translate_to_scenario_invalid_json():
    """Verifies error handling for invalid JSON response."""
    mock_json = {"response": "not a json"}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(ValueError, match="Ollama returned invalid JSON"):
            await auto_translate.translate_to_scenario("some text")


@pytest.mark.asyncio
async def test_translate_to_scenario_api_error():
    """Verifies error handling for non-200 API responses."""
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text.return_value = "Internal Server Error"
        mock_post.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Ollama API error"):
            await auto_translate.translate_to_scenario("some text")


def test_save_scenario(tmp_path):
    """Verifies that save_scenario correctly writes JSON to disk."""
    scenario = {"id": "test", "val": 1}
    out_file = tmp_path / "subdir" / "scen.json"

    auto_translate.save_scenario(scenario, out_file)

    assert out_file.exists()
    with open(out_file, "r") as f:
        data = json.load(f)
        assert data == scenario


def test_save_scenario_error(tmp_path):
    """Verifies that save_scenario handles writing errors gracefully (line 123)."""
    scenario = {"scenario_id": "test"}
    # Use a directory path as if it were a file to trigger an OSError
    bad_path = tmp_path / "a_directory"
    bad_path.mkdir()
    # This should not crash but just print (per the implementation in auto_translate.py:123)
    auto_translate.save_scenario(scenario, bad_path)
