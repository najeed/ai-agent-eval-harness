import pytest
from unittest.mock import patch
from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
from dataproc_engine.providers.public_sector.labor import LaborProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_public_sector_resiliency():
    """Harden Public Sector components by hitting no-simulation error paths."""
    # Demographics
    config_d = {"industry": "public_sector", "allow_simulation": False}
    p_d = DemographicsProvider(config_d, llm_manager=LLMManager({}))
    assert await p_d.extract() == []
    
    # Labor
    config_l = {"industry": "public_sector", "allow_simulation": False}
    p_l = LaborProvider(config_l, llm_manager=LLMManager({}))
    assert await p_l.extract() == []
