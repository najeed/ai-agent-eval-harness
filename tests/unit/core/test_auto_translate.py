"""
test_auto_translate.py

Unit tests for the Ollama-based auto-translate utility.
Refactored for high-fidelity (mock-less) verification using real dependencies and local server stubs.
"""

import pytest
import json
import asyncio
import sys
from aiohttp import web
from pathlib import Path
from eval_runner import auto_translate
from unittest.mock import patch
import pytest_asyncio
import PyPDF2
import docx

@pytest.fixture(scope="session")
def event_loop():
    """Ensure a clean event loop teardown, especially on Windows."""
    if sys.platform == 'win32':
        loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
    else:
        loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def ollama_stub(aiohttp_server):
    """Provides a local aiohttp server that simulates the Ollama /api/generate endpoint."""
    async def handle_generate(request):
        data = await request.json()
        prompt = data.get("prompt", "")
        
        # Determine response based on prompt content (simple routing)
        if "force_500" in prompt:
            return web.Response(text="Internal Server Error", status=500)
        
        if "invalid_json" in prompt:
            return web.json_response({"response": "not a json"})
            
        if "markdown_json" in prompt:
            return web.json_response({
                "response": 'Here is the JSON:\n```json\n{"scenario_id": "md-123", "title": "MD"}\n```'
            })
            
        if "missing_id" in prompt:
            return web.json_response({"response": '{"title": "No ID"}'})
            
        # Default success
        return web.json_response({
            "response": json.dumps({
                "scenario_id": "auto-123",
                "title": "Mock Title",
                "workflow": {
                    "nodes": [{"id": "t1", "task_description": "do thing"}],
                    "edges": []
                }
            })
        })

    app = web.Application()
    app.router.add_post("/api/generate", handle_generate)
    return await aiohttp_server(app)


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
    """Verifies REAL PDF extraction (using PyPDF2)."""
    pdf_file = tmp_path / "doc.pdf"
    
    # Generate a real (empty) PDF
    writer = PyPDF2.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with open(pdf_file, "wb") as f:
        writer.write(f)
        
    # Verify extraction doesn't crash on a real binary file
    res = auto_translate.extract_text(pdf_file)
    assert isinstance(res, str)


def test_extract_text_docx_success(tmp_path):
    """Verifies REAL DOCX extraction (using python-docx)."""
    docx_file = tmp_path / "doc.docx"
    
    # Generate a real DOCX
    doc = docx.Document()
    doc.add_paragraph("Extracted DOCX Text")
    doc.save(docx_file)
    
    assert auto_translate.extract_text(docx_file) == "Extracted DOCX Text"


@pytest.mark.asyncio
async def test_translate_to_scenario_success(ollama_stub):
    """Verifies successful translation using a real local server stub."""
    base_url = f"http://{ollama_stub.host}:{ollama_stub.port}"
    api_url = f"{base_url}/api/generate"
    
    result = await auto_translate.translate_to_scenario("some text", api_url=api_url)
    assert result["scenario_id"] == "auto-123"
    assert result["title"] == "Mock Title"
    assert len(result["workflow"]["nodes"]) == 1


@pytest.mark.asyncio
async def test_translate_to_scenario_repair_missing_id(ollama_stub):
    """Verifies that the logic repairs a missing scenario_id using real server."""
    base_url = f"http://{ollama_stub.host}:{ollama_stub.port}"
    api_url = f"{base_url}/api/generate"
    
    result = await auto_translate.translate_to_scenario("missing_id", api_url=api_url)
    assert result["scenario_id"].startswith("auto-")
    assert result["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_translate_to_scenario_markdown_json(ollama_stub):
    """Verifies extraction of JSON from markdown blocks via real server."""
    base_url = f"http://{ollama_stub.host}:{ollama_stub.port}"
    api_url = f"{base_url}/api/generate"
    
    result = await auto_translate.translate_to_scenario("markdown_json", api_url=api_url)
    assert result["scenario_id"] == "md-123"


@pytest.mark.asyncio
async def test_translate_to_scenario_connection_error():
    """Verifies error handling for real connection failures (port 1)."""
    # Port 1 is usually closed/dead
    with pytest.raises(ConnectionError, match="Could not connect to Ollama"):
        await auto_translate.translate_to_scenario("some text", api_url="http://localhost:1/api/generate")


@pytest.mark.asyncio
async def test_translate_to_scenario_invalid_json(ollama_stub):
    """Verifies error handling for invalid JSON response via real server."""
    base_url = f"http://{ollama_stub.host}:{ollama_stub.port}"
    api_url = f"{base_url}/api/generate"
    
    with pytest.raises(ValueError, match="Ollama returned invalid JSON"):
        await auto_translate.translate_to_scenario("invalid_json", api_url=api_url)


@pytest.mark.asyncio
async def test_translate_to_scenario_api_error(ollama_stub):
    """Verifies error handling for non-200 API responses via real server."""
    base_url = f"http://{ollama_stub.host}:{ollama_stub.port}"
    api_url = f"{base_url}/api/generate"
    
    with pytest.raises(RuntimeError, match="Ollama API error"):
        await auto_translate.translate_to_scenario("force_500", api_url=api_url)


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
    """Verifies that save_scenario handles writing errors gracefully."""
    scenario = {"scenario_id": "test"}
    # Use a directory path as if it were a file to trigger an OSError
    bad_path = tmp_path / "a_directory"
    bad_path.mkdir()
    # This should not crash but just print
    auto_translate.save_scenario(scenario, bad_path)


def test_extract_text_unsupported_extension(tmp_path):
    """Verifies ValueError for unknown extensions."""
    f = tmp_path / "test.unknown"
    f.write_text("ok")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        auto_translate.extract_text(f)


def test_extract_text_pdf_import_error(tmp_path):
    """Verifies ImportError when PyPDF2 is missing."""
    f = tmp_path / "test.pdf"
    f.write_text("ok")
    with patch.dict("sys.modules", {"PyPDF2": None}):
        with pytest.raises(ImportError, match="PyPDF2 is required"):
            auto_translate.extract_text(f)


def test_extract_text_docx_import_error(tmp_path):
    """Verifies ImportError when python-docx is missing."""
    f = tmp_path / "test.docx"
    f.write_text("ok")
    with patch.dict("sys.modules", {"docx": None}):
        with pytest.raises(ImportError, match="python-docx is required"):
            auto_translate.extract_text(f)
