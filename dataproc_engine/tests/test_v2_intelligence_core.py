import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_llm_manager_v2_token_guard_interception():
    config = {"llm_strategy": "auto"}
    manager = LLMManager(config)
    
    # 1. Test Interception (SEC domain)
    content = "SEC FILING CONTENT"
    schema = {"revenue": "number"}
    source_hint = "https://www.sec.gov/edgar/123.pdf"
    
    # This should trigger _token_guard_intercept and set strategy to heuristic
    result = await manager.extract_structured_data(content, schema, source_hint=source_hint)
    assert manager.strategy == "heuristic"

@pytest.mark.asyncio
async def test_llm_manager_v2_cost_tracking():
    config = {"llm_strategy": "cloud", "llm_provider": "openai"}
    manager = LLMManager(config)
    
    mock_usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 500
    }
    
    with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"}):
        with patch("dataproc_engine.core.llm_manager.LLMManager._call_openai", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"revenue": 1000.0}
            
            # Manually trigger record_usage since we are mocking the call
            manager._record_usage(mock_usage, "gpt-4o")
            
            # gpt-4o: ($0.50 * 1) + ($1.50 * 0.5) = 0.5 + 0.75 = 1.25 cents
            economics = manager.get_session_economics()
            assert economics["total_cost_cents"] == 1.25
            assert economics["roi_status"] == "positive"

def test_parity_synthesizer_conservative_logic():
    from dataproc_engine.core.synthesis_engine import ParitySynthesizer
    engine = ParitySynthesizer()
    
    # 1. Test Public Domain (SEC)
    sec_data = engine.generate_statistical_twin("sec_fundamentals", count=5)
    assert len(sec_data) == 5
    assert sec_data[0]["_synthesis_audit"]["source_license"] == "Public Domain"
    assert sec_data[0]["_synthesis_audit"]["conservative_status"] == "embedded"
    
    # 2. Test Restricted (Clinical)
    clinical_data = engine.generate_statistical_twin("clinical", count=5)
    assert len(clinical_data) == 5
    assert clinical_data[0]["_synthesis_audit"]["conservative_status"] == "local_only"
    assert "heart_rate" in clinical_data[0]

def test_dataset_engine_v2_integration():
    from dataproc_engine.core.engine import DatasetEngine
    engine = DatasetEngine(config={"llm_strategy": "mock"})
    assert engine.synthesis_engine is not None
    assert engine.llm_manager.config["llm_strategy"] == "mock"
