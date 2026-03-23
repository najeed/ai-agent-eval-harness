import pytest
import os
import json
import pandas as pd
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.base_provider import StandardSchema

@pytest.mark.asyncio
async def test_llm_manager_perfection():
    """Targeted coverage for every remaining line in LLMManager."""
    llm = LLMManager({"llm_strategy": "auto", "llm_provider": "openai"})
    schema = {"revenue": "number"}
    
    # 1. Cloud API except blocks (Lines 169-171, 189-191, 215-217, 236-238)
    with patch("aiohttp.ClientSession.post", side_effect=Exception("API Down")):
        # OpenAI
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            await llm._call_openai("test", schema, "test")
        # Gemini
        llm.preferred_provider = "gemini"
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            await llm._call_gemini("test", schema, "test")
        # Claude
        llm.preferred_provider = "claude"
        with patch.dict(os.environ, {"CLAUDE_API_KEY": "test"}):
            await llm._call_claude("test", schema, "test")
        # Grok
        llm.preferred_provider = "grok"
        with patch.dict(os.environ, {"GROK_API_KEY": "test"}):
            await llm._call_grok("test", schema, "test")

    # 2. Sentiment LLM Success (Lines 65-67)
    with patch.object(llm, "_call_sentiment_llm", AsyncMock(return_value=0.9)):
        assert await llm.analyze_sentiment("happy") == 0.9

    # 3. Ollama Sentiment Fallback (Lines 84-89)
    llm.strategy = "ollama"
    with patch.object(llm, "_try_cloud_providers", AsyncMock(return_value=None)):
        with patch.object(llm, "_try_ollama", AsyncMock(return_value={"sentiment_score": 0.8})):
            assert await llm._call_sentiment_llm("test") == 0.8

    # 4. _try_cloud_providers return None (Line 150)
    llm.preferred_provider = "invalid"
    with patch.dict(os.environ, {"INVALID_API_KEY": "test"}):
        assert await llm._try_cloud_providers("test", schema) is None

    # 5. Ollama Text Fallback (Lines 258-260)
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"response": '{"revenue": 100}'})
        mock_post.return_value.__aenter__.return_value = mock_resp
        assert await llm._try_ollama("test", schema) == {"revenue": 100}

    # 6. Heuristic Fail Signal Ratio < 0.5 (Line 307)
    # schema has 10 keys, we find 0
    big_schema = {f"k{i}": "string" for i in range(10)}
    assert llm._try_heuristics("empty", big_schema) is None

    # 7. ValueError for non-numbers (Line 353)
    # Trigger line 353: 'Not a number'
    assert llm._verify_schema({"revenue": []}, schema) is None

    # 8. Number Regex Inference (Lines 293-297)
    # schema has 'revenue', content has 'revenue 123'
    assert llm._try_heuristics("revenue 123", {"revenue": "number"}) == {"revenue": "123"}

@pytest.mark.asyncio
async def test_correlator_perfection(tmp_path):
    """Targeted coverage for DataCorrelator missing lines."""
    correlator = DataCorrelator()
    target_dir = str(tmp_path / "fail_correlate")
    os.makedirs(target_dir)
    
    # Create a directory where a file is expected (pd.read_csv will fail)
    bad_file = os.path.join(target_dir, "bad_file.csv")
    os.makedirs(bad_file)
        
    datasets = {}
    correlator.correlate(datasets, target_dir=target_dir)
    # Hits line 43: logger.warning
    assert "bad" not in datasets or len(datasets["bad"]) == 0
