import asyncio
import json
import os
from datetime import datetime
from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("GlobalAudit")

async def run_global_audit():
    """
    Triggers a unified extraction and correlation run across all industrial sectors.
    """
    logger.info("global_audit_started", timestamp=datetime.utcnow().isoformat())
    
    # Initialize Engine with a mock-capable LLM manager for the audit baseline
    llm = LLMManager({"strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    
    # Industries to audit with their specific schemas
    industries = [
        ("finance", {"schema_type": "sec_edgar"}),
        ("finance", {"schema_type": "credit_risk"}),
        ("energy", {"schema_type": "eia"}),
        ("energy", {"schema_type": "iea_global"}),
        ("healthcare", {"schema_type": "cms"}),
        ("healthcare", {"schema_type": "mimic_iii"}),
        ("healthcare", {"schema_type": "mimic_iv"}),
        ("telecom", {"schema_type": "fcc"}),
        ("telecom", {"schema_type": "ookla"}),
        ("ecommerce", {"schema_type": "olist"}),
        ("ecommerce", {"schema_type": "uci"}),
        ("agriculture", {"schema_type": "standard"}),
        ("transportation", {"schema_type": "standard"}),
        ("unstructured", {"input_uri": "docs/"})
    ]
    
    base_dir = "."
    global_datasets = {}
    
    # 1. Extraction & Transformation
    for industry, custom_config in industries:
        config = {"limit": 10}
        config.update(custom_config)
        
        # Absolute path patching for local datasets
        if industry == "healthcare" and config.get("schema_type") == "cms":
            config["input_uri"] = f"{base_dir}/industries/healthcare/datasets/appointments.csv"
        elif industry == "ecommerce":
            config["input_uri"] = f"{base_dir}/industries/retail/datasets/retail_records.csv"
        elif industry == "energy" and config.get("schema_type") == "eia":
            config["input_uri"] = f"{base_dir}/industries/energy/datasets/energy_records.csv"
        elif industry == "telecom" and config.get("schema_type") == "fcc":
            config["input_uri"] = f"{base_dir}/industries/finance/datasets/telecom_records.csv"
        elif industry == "unstructured":
            config["input_uri"] = f"{base_dir}/docs/"

        try:
            logger.info("auditing_industry", industry=industry, schema=config.get("schema_type", "default"))
            provider = engine.get_provider(industry, config)
            
            raw = await provider.extract()
            standard = await provider.transform(raw)
            
            valid = provider.validate(standard)
            logger.info("industry_audit_complete", industry=industry, records=len(standard), valid=valid)
            
            # Key for global_datasets needs to be unique if there are multiple schemas per industry
            key = f"{industry}_{config.get('schema_type', 'default')}"
            global_datasets[key] = standard if valid else []
            
        except Exception as e:
            logger.error("industry_audit_failed", industry=industry, error=str(e))
            global_datasets[f"{industry}_{config.get('schema_type', 'default')}"] = []
            
    # 2. Cross-Industry Correlation
    logger.info("starting_correlation_phase")
    correlated_data = DataCorrelator.correlate(global_datasets)
    
    # 3. Persistence
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"global_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")
    
    final_output = {
        "audit_timestamp": datetime.utcnow().isoformat(),
        "total_records": sum(len(d) for d in correlated_data.values()),
        "datasets": {ind: [r.to_dict() for r in records] for ind, records in correlated_data.items()}
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    logger.info("global_audit_results_saved", output_path=output_path)

if __name__ == "__main__":
    asyncio.run(run_global_audit())
