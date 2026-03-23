import pytest
import asyncio
from dataproc_engine.core.llm_manager import LLMManager

def test_llm_strategy_selection():
    # 1. Mock strategy
    llm = LLMManager({"llm_strategy": "mock"})
    assert llm.strategy == "mock"
    
    # 2. Heuristic strategy
    llm = LLMManager({"llm_strategy": "heuristic"})
    assert llm.strategy == "heuristic"

def test_verify_schema_coercion():
    llm = LLMManager({"llm_strategy": "mock"})
    schema = {"name": "string", "age": "integer", "score": "number"}
    
    # Valid data
    data = {"name": "Test", "age": 25, "score": 9.5}
    assert llm._verify_schema(data, schema, strict=True) == data
    
    # Type Coercion (Expected behavior in current implementation)
    data = {"name": "Test", "age": "25", "score": "9.5"}
    result = llm._verify_schema(data, schema, strict=True)
    assert result["age"] == 25
    assert result["score"] == 9.5
    
    # Missing key in strict mode
    data = {"name": "Test"}
    assert llm._verify_schema(data, schema, strict=True) is None

def test_heuristic_sentiment():
    llm = LLMManager({"llm_strategy": "heuristic"})
    
    # Positive
    high_score = llm._heuristic_sentiment("extremely high profit and robust growth")
    assert high_score > 0.8
    
    # Negative
    low_score = llm._heuristic_sentiment("weak decline and loss")
    assert low_score < 0.3
    
    # Neutral
    assert llm._heuristic_sentiment("nothing here") == 0.5

@pytest.mark.asyncio
async def test_mock_extraction():
    llm = LLMManager({"llm_strategy": "mock"})
    schema = {"id": "string", "value": "number"}
    
    result = await llm.extract_structured_data("some text", schema)
    assert "id" in result
    assert "value" in result
    assert isinstance(result["value"], (int, float))


