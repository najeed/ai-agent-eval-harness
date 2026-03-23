import pytest
import asyncio
from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.base_provider import StandardSchema

@pytest.mark.asyncio
@pytest.mark.parametrize("industry, custom_config", [
    ("finance", {"schema_type": "sec_edgar"}),
    ("finance", {"schema_type": "credit_risk"}),
    ("energy", {"schema_type": "eia"}),
    ("energy", {"schema_type": "energy_balances"}),
    ("healthcare", {"schema_type": "cms"}),
    ("healthcare", {"schema_type": "clinical"}),
    ("telecom", {"schema_type": "fcc"}),
    ("telecom", {"schema_type": "ookla"}),
    ("ecommerce", {"schema_type": "olist"}),
    ("ecommerce", {"schema_type": "uci"}),
    ("agriculture", {"schema_type": "standard"}),
    ("transportation", {"schema_type": "standard"}),
    ("unstructured", {"schema_type": "standard"}),
    ("demographics", {"schema_type": "standard"}),
    ("labor", {"schema_type": "standard"}),
    ("environment", {"schema_type": "standard"}),
    ("education", {"schema_type": "standard"}),
    ("housing", {"schema_type": "standard"}),
    ("manufacturing", {"schema_type": "standard"}),
    ("media_entertainment", {"schema_type": "standard"}),
    ("decision_support", {"schema_type": "standard"}),
])
async def test_industry_parity(industry, custom_config):
    """
    Ensure all industrial providers adhere to the mission-critical architectural standards.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    
    base_dir = "."
    config = {"limit": 1}
    config.update(custom_config)
    
    # Industry-specific input overrides
    if industry == "finance":
        if config.get("schema_type") == "sec_edgar":
             config["ciks"] = ["0000320193"]
    elif industry == "energy":
        config["series_id"] = "ELEC.GEN.ALL-US-99.M"
    elif industry == "transportation":
         config["input_uri"] = f"{base_dir}/industries/transportation/datasets/airline_delays.csv"
    elif industry == "telecom":
         config["input_uri"] = f"{base_dir}/industries/telecom/datasets/telecom_records.csv"
    elif industry == "unstructured":
        config["input_uri"] = f"{base_dir}/industries/unstructured/datasets/sample_document.txt"

    provider = engine.get_provider(industry, config)
    
    # 1. Integration Level Verification
    raw = await provider.extract()
    assert isinstance(raw, list), f"{industry} extract() must return a list"
    
    if raw:
        transformed = await provider.transform(raw)
        assert isinstance(transformed, list), f"{industry} transform() must return a list"
        
        # Hardening check for all sectors (ensures simulation or local data production)
        if industry in [
            "transportation", "agriculture", "unstructured", "demographics", 
            "labor", "environment", "education", "housing", "manufacturing", 
            "media_entertainment", "decision_support", "finance", "energy", "healthcare", "telecom", "ecommerce"
        ]:
             assert len(transformed) > 0, f"{industry} failed to produce records from dummy data."

        for record in transformed:
            assert isinstance(record, StandardSchema), f"{industry} must produce StandardSchema"
            assert record.industry == industry, f"{industry} output industry mismatch"
            assert "record_id" in record.to_dict(), f"{industry} missing record_id in dict"
            assert record.checksum is not None, f"{industry} missing checksum"
            assert provider.validate([record]), f"{industry} failed domain validation"

def test_pii_scrubbing_parity():
    """
    Verify that PII scrubbing is consistent across the framework.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    provider = engine.get_provider("finance", {}) # Any provider works as it's in BaseProvider
    
    test_text = "Contact me at nudge@example.com or (555) 001-0199."
    scrubbed = provider.scrub_pii(test_text)
    
    assert "[EMAIL]" in scrubbed
    assert "[PHONE]" in scrubbed
    assert "nudge@example.com" not in scrubbed
    assert "(555) 001-0199" not in scrubbed

@pytest.mark.asyncio
async def test_resiliency_layer():
    """
    Verify that the request_with_retry layer handles failures correctly.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    provider = engine.get_provider("finance", {"max_retries": 2})
    
    count = 0
    async def failing_func():
        nonlocal count
        count += 1
        raise Exception("Transient Error")

    result = await provider.request_with_retry(failing_func)
    
    assert result is None
    assert count == 2 # Max retries reached

def test_backup_rotation(tmp_path):
    """
    Verify that the rotational backup logic preserves data and prunes old versions.
    """
    from dataproc_engine.cli.main import run_rotational_backup
    import os
    import glob
    
    output_file = str(tmp_path / "test_data.jsonl")
    with open(output_file, "w") as f:
        f.write("original data")
    
    # 1. Trigger first backup
    archive1 = run_rotational_backup(output_file, max_backups=2)
    assert os.path.exists(archive1)
    
    # 2. Trigger multiple backups to test rotation (max=2)
    with open(output_file, "w") as f: f.write("data 2")
    archive2 = run_rotational_backup(output_file, max_backups=2)
    
    with open(output_file, "w") as f: f.write("data 3")
    archive3 = run_rotational_backup(output_file, max_backups=2)
    
    backups = sorted(glob.glob(f"{output_file}.*.bak"))
    assert len(backups) == 2
    assert archive1 not in backups
    assert archive2 in backups
    assert archive3 in backups


