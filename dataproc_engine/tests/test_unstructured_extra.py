import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_unstructured_error_branches():
    """Harden error branches in UnstructuredProvider (Lines 50-108)."""
    # 1. No input URI (Line 50-51)
    p1 = UnstructuredProvider({"allow_simulation": False}, llm_manager=LLMManager({}))
    assert await p1.extract() == []
    
    # 2. Web fetch failure (Lines 57-72)
    p2 = UnstructuredProvider({"input_uri": "https://invalid.com", "allow_simulation": False}, llm_manager=LLMManager({}))
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Timeout")):
        assert await p2.extract() == []
        
    # 3. Path not found (Lines 108)
    p3 = UnstructuredProvider({"input_uri": "/non/existent/path", "allow_simulation": False}, llm_manager=LLMManager({}))
    assert await p3.extract() == []

@pytest.mark.asyncio
async def test_unstructured_pdf_corruption():
    """Harden PDF corruption catch block (Lines 101-103)."""
    p = UnstructuredProvider({"input_uri": "corrupt.pdf", "allow_simulation": False}, llm_manager=LLMManager({}))
    with patch("os.path.exists", return_value=True):
        with patch("pypdf.PdfReader", side_effect=Exception("Corrupt PDF Payload")):
            assert await p.extract() == []
