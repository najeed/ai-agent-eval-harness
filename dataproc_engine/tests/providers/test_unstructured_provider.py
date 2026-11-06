from unittest.mock import MagicMock, patch

import pytest

from dataproc_engine.core.base_provider import RawArtifact
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider


@pytest.mark.asyncio
async def test_document_fallback_requires_permission_and_preserves_simulation_label():
    raw = RawArtifact("document", "test://document", "unstructured input", {}, "2026-01-01")
    for allowed in (False, True):
        provider = UnstructuredProvider(
            {"allow_simulation": allowed}, LLMManager({"llm_strategy": "heuristic"})
        )
        records = await provider.transform([raw])
        if allowed:
            assert records[0].provenance["execution_mode"] == "simulated"
        else:
            assert records == []


@pytest.mark.asyncio
async def test_common_crawl_sample_requires_explicit_permission():
    assert await UnstructuredProvider({"unstructured_mode": "common_crawl"}).extract() == []
    provider = UnstructuredProvider({"unstructured_mode": "common_crawl", "allow_simulation": True})
    raw = await provider.extract()
    assert raw[0].metadata["execution_mode"] == "simulated"


@pytest.mark.asyncio
async def test_document_provider_denies_permitted_model_synthesis_without_provider_permission():
    provider = UnstructuredProvider(
        {}, LLMManager({"llm_strategy": "mock", "allow_simulation": True})
    )
    raw = RawArtifact("document", "test://document", "input", {}, "2026-01-01")
    with pytest.raises(PermissionError, match="provider allow_simulation"):
        await provider.transform([raw])


@pytest.mark.asyncio
async def test_unstructured_hegemony():
    """Exhaustive coverage for UnstructuredProvider branches (PDF, Text, Directory) - Hardened."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    modes = [{"input_uri": "test.pdf"}, {"input_uri": "test.txt"}, {"input_uri": "test_folder/"}]
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
