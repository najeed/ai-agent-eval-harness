import pytest
import os
import aiohttp
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.providers.agriculture import AgricultureProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_agriculture_exception_handler():
    """Trigger the catch block in AgricultureProvider.extract (Line 97)."""
    config = {"industry": "agriculture", "usda_api_key": "FAIL_KEY", "allow_simulation": False}
    provider = AgricultureProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Network Blowup")):
        artifacts = await provider.extract()
        assert len(artifacts) == 0

@pytest.mark.asyncio
async def test_finance_sec_parsing_error():
    """Trigger the catch block in FinanceProvider.extract (Lines 129-131)."""
    config = {"industry": "finance", "finance_mode": "sec_edgar", "ciks": ["0000320193"], "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        # Corrupt JSON to trigger generic Exception in process_cik
        mock_resp.json.side_effect = Exception("Malformed JSON Facts")
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) == 0

@pytest.mark.asyncio
async def test_healthcare_api_error_branches():
    """Trigger various error branches in HealthcareProvider."""
    config = {"industry": "healthcare", "healthcare_mode": "cms", "allow_simulation": False}
    provider = HealthcareProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        # Test CMS 500
        artifacts = await provider.extract()
        assert len(artifacts) == 0

def test_cli_rotation_policy_message(tmp_path):
    """Exercise the 'Rotation Policy Active' message (Line 183)."""
    from click.testing import CliRunner
    from dataproc_engine.cli.main import cli
    
    runner = CliRunner()
    target_dir = str(tmp_path / "output")
    os.makedirs(target_dir)
    output_file = os.path.join(target_dir, "finance_kb.jsonl")
    
    # Create 3 backups to trigger the policy message when max-backups is 2
    for i in range(3):
        with open(f"{output_file}.{i}.bak", "w") as f: f.write("bak")
    with open(output_file, "w") as f: f.write("current")
        
    with patch("dataproc_engine.core.engine.DatasetEngine.run_industry_pipeline", AsyncMock(return_value=[MagicMock(to_dict=lambda: {"id": "new"})])):
        # Use overwrite so we don't block on prompt
        result = runner.invoke(cli, ["extract", "--industry", "finance", "--target-dir", target_dir, "--overwrite", "--max-backups", "2"])
        assert "Rotation Policy Active" in result.output
