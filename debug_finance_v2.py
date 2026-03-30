import asyncio
import json
from unittest.mock import patch
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.core.llm_manager import LLMManager

class MockResponse:
    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or []
    async def json(self): return self._json
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

async def debug_worldbank():
    print("Testing World Bank Tier Logic...")
    config = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({"llm_provider": "mock"}))
    
    mock_wb_data = [
        {"page": 1},
        [
            {"country": {"value": "USA", "id": "US"}, "indicator": {"value": "GDP"}, "value": 1.0, "date": "2023"},
            {"country": {"value": "CAN", "id": "CA"}, "indicator": {"value": "GDP"}, "value": 2.0, "date": "2023"}
        ]
    ]
    
    with patch("aiohttp.ClientSession.get", return_value=MockResponse(200, mock_wb_data)):
        artifacts = await provider.extract()
        print(f"Extracted {len(artifacts)} artifacts.")
        if artifacts:
            results = await provider.transform(artifacts)
            print(f"Transformed {len(results)} records.")
            if results:
                print(f"Sample Data: {results[0].data}")
                return len(results) == 2 and results[0].data["value"] == 1.0
    return False

async def main():
    wb_pass = await debug_worldbank()
    print(f"\nWorld Bank Pilot Logic Pass: {wb_pass}")
    if not wb_pass:
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
