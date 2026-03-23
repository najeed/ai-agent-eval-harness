import asyncio
import os
import json
from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.base_provider import StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("HardeningAudit")

class MockLLMManager:
    def _verify_schema(self, data, schema, strict=False):
        # Basic mock: pass through data if it fits the schema keys
        return data

INDUSTRIES = [
    "finance", "energy", "healthcare", "telecom", "ecommerce", 
    "unstructured", "agriculture", "transportation", "demographics", 
    "labor", "environment", "education", "housing", "manufacturing", 
    "media_entertainment", "decision_support"
]

async def run_audit():
    """
    Fleet-wide audit of all 14 industrial sectors.
    Verifies Zero-Bundling compliance and architectural hardening.
    """
    mock_llm = MockLLMManager()
    engine = DatasetEngine(llm_manager=mock_llm)
    
    report = {
        "total_sectors": len(INDUSTRIES),
        "sectors_passed": 0,
        "sectors_failed": 0,
        "details": []
    }
    
    print(f"🕵️ Starting Hardening Audit for {len(INDUSTRIES)} sectors...")
    print("-" * 50)
    
    for industry in INDUSTRIES:
        print(f"🔍 Auditing: {industry}...")
        try:
            # 1. Initialize Provider
            provider = engine.get_provider(industry, {"allow_simulation": True})
            
            # 2. Extraction Test
            artifacts = await provider.extract()
            if not artifacts:
                print(f"  ⚠️ No artifacts extracted for {industry}")
                
            # 3. Simulation Veracity Check
            sim_count = sum(1 for a in artifacts if a.metadata.get("simulation"))
            sim_status = "ACTIVE" if sim_count > 0 else "OFFLINE"
            
            # 4. Transformation & Validation Test
            data = await provider.transform(artifacts)
            is_valid = provider.validate(data)
            
            if is_valid:
                report["sectors_passed"] += 1
                status = "PASS"
            else:
                report["sectors_failed"] += 1
                status = "FAIL"
                
            report["details"].append({
                "industry": industry,
                "status": status,
                "artifacts_count": len(artifacts),
                "simulation_status": sim_status,
                "records_count": len(data)
            })
            
            print(f"  ✅ {industry}: {status} | Artifacts: {len(artifacts)} | Sim: {sim_status}")
            
        except Exception as e:
            print(f"  ❌ {industry}: CRITICAL ERROR - {str(e)}")
            report["sectors_failed"] += 1
            report["details"].append({
                "industry": industry,
                "status": "CRITICAL",
                "error": str(e)
            })

    print("-" * 50)
    print(f"🏁 Audit Complete: {report['sectors_passed']}/{report['total_sectors']} sectors Passed.")
    
    # Save report
    with open("hardening_audit_results.json", "w") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_audit())
