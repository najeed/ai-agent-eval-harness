import pytest
import os
from unittest.mock import patch, MagicMock
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.core.base_provider import RawArtifact

@pytest.mark.asyncio
async def test_unstructured_extraction():
    """Verify local file extraction for unstructured data."""
    config = {"input_uri": "README.md", "allow_simulation": False}
    provider = UnstructuredProvider(config)
    
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", MagicMock()):
            raw = await provider.extract()
            assert len(raw) == 1
            assert raw[0].id == "UNSTR-README.md"
