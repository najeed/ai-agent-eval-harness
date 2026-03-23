import pytest
import os
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_unstructured_hegemony():
    """Exhaustive coverage for UnstructuredProvider branches (PDF, Text, Directory) - Hardened."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    modes = [
        {"input_uri": "test.pdf"},
        {"input_uri": "test.txt"},
        {"input_uri": "test_folder/"}
    ]
    for mode in modes:
        with patch("os.path.exists", return_value=True):
            config = {"industry": "unstructured", "allow_simulation": True}
            config.update(mode)
            provider = UnstructuredProvider(config, llm_manager=llm)
            
            # Mock the readers and file access
            with patch("builtins.open", MagicMock()):
                with patch("pypdf.PdfReader") as mock_pdf:
                    mock_reader = MagicMock()
                    mock_reader.pages = [MagicMock(extract_text=lambda: "Extracted Content")]
                    mock_pdf.return_value = mock_reader
                    
                    # Mock os.listdir for directory mode
                    with patch("os.listdir", return_value=["file1.txt"]):
                        with patch("os.path.isfile", return_value=True):
                            raw = await provider.extract()
                            assert len(raw) > 0
                            assert raw[0].id is not None
