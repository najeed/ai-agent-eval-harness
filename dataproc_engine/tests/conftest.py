import pytest
from unittest.mock import MagicMock, AsyncMock
from dataproc_engine.core.llm_manager import LLMManager

class IndustryHeuristicMock:
    """
    A state-aware mock for LLM operations that generates deterministic, 
    industry-compliant StandardSchema records and simulates failure modes.
    """
    def __init__(self):
        self.failure_mode = None
        self.call_count = 0

    def set_failure_mode(self, mode):
        """Supported: 'api_error', 'rate_limit', 'schema_violation', 'drift_detected'"""
        self.failure_mode = mode

    def _check_failure(self):
        if self.failure_mode == "api_error":
            raise Exception("Simulated Cloud Provider API Failure")
        if self.failure_mode == "rate_limit":
            raise Exception("Rate limit reached for model tier")

    async def mock_extract_structured_data(self, prompt, schema, industry="finance", **kwargs):
        self.call_count += 1
        self._check_failure()

        # Deterministic industry-based generation
        records = []
        limit = kwargs.get("limit", 1)
        for i in range(limit):
            record = {
                "id": f"mock_{industry}_{i}",
                "timestamp": "2024-01-01T00:00:00Z",
                "industry": industry,
                "data": {"signal": 0.85, "status": "stable", "index": i},
                "metadata": {"source": "heuristic_mock", "version": "v2.0"},
                "integrity_hash": "sha256_mock_hash"
            }
            if self.failure_mode == "schema_violation":
                del record["id"]
            records.append(record)
        return records

    def mock_verify_schema(self, data, schema, strict=False):
        self._check_failure()
        return data

@pytest.fixture
def heuristic_mock():
    return IndustryHeuristicMock()

@pytest.fixture
def patched_llm_manager(heuristic_mock):
    """Fixture that patches LLMManager to use our IndustryHeuristicMock."""
    mock_mgr = MagicMock(spec=LLMManager)
    # Patch main entry points
    mock_mgr.extract_structured_data = AsyncMock(side_effect=heuristic_mock.mock_extract_structured_data)
    mock_mgr._verify_schema = MagicMock(side_effect=heuristic_mock.mock_verify_schema)
    return mock_mgr
