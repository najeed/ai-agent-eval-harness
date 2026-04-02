import pytest
from dataproc_engine.providers.education import EducationProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_education_provider_no_sim():
    """Harden EducationProvider by hitting 'allow_simulation=False' branches (Lines 37, 53, 69, 84)."""
    modes = ["unesco", "mooc", "kaggle", "nces"]
    for mode in modes:
        config = {"industry": "education", "education_mode": mode, "allow_simulation": False}
        provider = EducationProvider(config, llm_manager=LLMManager({}))
        artifacts = await provider.extract()
        assert artifacts == []
