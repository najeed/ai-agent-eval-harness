import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
import aiohttp

@pytest.fixture(autouse=True)
def mock_network_and_llm():
    """
    Global mock for all network calls and LLM provider endpoints.
    Ensures tests can hit extraction logic branches without real tokens.
    """
    with patch("aiohttp.ClientSession.post") as mock_post, \
         patch("aiohttp.ClientSession.get") as mock_get:
        
        # Helper to generate industry-specific valid data
        def get_mock_json(url=""):
            # 1. SEC Fact Structure (Special Case)
            if "sec.gov" in url:
                return {
                    "facts": {
                        "us-gaap": {
                            "Assets": {"units": {"USD": [{"val": 1000000}]}},
                            "Revenues": {"units": {"USD": [{"val": 500000}]}},
                            "NetIncomeLoss": {"units": {"USD": [{"val": 100000}]}}
                        }
                    }
                }
            
            # 2. Standard valid values to pass domain validation
            return {
                "status": "mocked",
                "entity_name": "Mock Corp",
                "total_assets": 1000000,
                "total_liabilities": 500000,
                "net_income": 100000,
                "revenue": 500000,
                "revenues": 500000, # Finance Alias
                "value": 100,
                "sentiment_score": 0.8,
                "cik": "0000320193",
                "ticker": "AAPL",
                "date": "2023-01-01"
            }

        def create_mock_resp(url):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            payload = get_mock_json(url)
            # Support both .json() and .text()
            mock_resp.json.return_value = payload
            mock_resp.text.return_value = json.dumps(payload)
            
            # Complex LLM support
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}], # OpenAI
                "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}], # Gemini
                "content": [{"text": json.dumps(payload)}], # Claude
                "response": json.dumps(payload) # Ollama
            }
            # Catch-all for SEC case where .json() should return the raw dict
            if "sec.gov" in url:
                mock_resp.json.return_value = payload

            mock_resp.__aenter__.return_value = mock_resp
            return mock_resp

        mock_post.side_effect = lambda url, **kwargs: create_mock_resp(url)
        mock_get.side_effect = lambda url, **kwargs: create_mock_resp(url)
        
        yield


