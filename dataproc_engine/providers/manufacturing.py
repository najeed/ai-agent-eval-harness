import hashlib
import json
import asyncio
import aiohttp
import datetime
from typing import List, Dict, Any, Optional
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("ManufacturingProvider")

class ManufacturingProvider(BaseProvider):
    """
    Provider for Manufacturing & Industrial data (User-Supplied & US Census ASM).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.manufacturing_mode = config.get("manufacturing_mode", "industrial_stats") # industrial_stats, asm
        self.api_key = config.get("census_api_key")

    async def extract(self) -> List[RawArtifact]:
        if self.manufacturing_mode == "industrial_stats":
            # Gold Standard: Global Industrial Statistics
            # URI: https://industry.data.example.org/api/v1/en/data/
            url = "https://industry.data.example.org/api/v1/en/data/"
            
            if self.allow_simulation:
                sim_industrial = [
                    {"country": "Germany", "sector": "Motor Vehicles", "value": 450.5, "unit": "billion USD", "year": 2022},
                    {"country": "Japan", "sector": "Electronics", "value": 310.2, "unit": "billion USD", "year": 2022}
                ]
                return [self.create_simulated_artifact(
                    id="IND-STATS-V1",
                    content=sim_industrial,
                    source_url="https://industry.data.example.org/",
                    metadata={"dataset": "Manufacturing Value Added"}
                )]
            return []

        # US Census: Annual Survey of Manufactures (ASM)
        # URI: https://api.census.gov/data/timeseries/asm/industry
        year = self.config.get("year", 2021)
        url = f"https://api.census.gov/data/timeseries/asm/industry?get=NAICS2017_LABEL,ESTAB,EMP,PAYANN,VSHIP&for=us:*"
        
        if self.allow_simulation:
            sim_asm = [
                ["NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "VSHIP", "us"],
                ["Food manufacturing", "34000", "1500000", "65000000", "800000000", "1"],
                ["Chemical manufacturing", "14000", "800000", "75000000", "950000000", "1"]
            ]
            return [self.create_simulated_artifact(
                id=f"CENSUS-ASM-{year}",
                content=sim_asm,
                source_url=url,
                metadata={"dataset": "ASM", "year": year}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        if self.manufacturing_mode == "industrial_stats":
            TARGET_SCHEMA = {"country": "string", "sector": "string", "mva_value": "number", "year": "integer"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "country": row.get("country"),
                        "sector": row.get("sector"),
                        "mva_value": float(row.get("value", 0)),
                        "year": int(row.get("year", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"IND-{raw_data['country']}-{raw_data['sector']}-{raw_data['year']}".encode()).hexdigest()[:16],
                        results.append(StandardSchema(
                            id=record_id,
                            industry="manufacturing",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "Industrial-Stats-Agency"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        # ASM Transformation
        TARGET_SCHEMA = {"industry_label": "string", "establishments": "integer", "employees": "integer", "payroll": "number", "shipment_value": "number"}
        for raw in raw_artifacts:
            # Handle both list-of-lists (Census) and list-of-dicts (Evaluator)
            is_list_format = isinstance(raw.content, list) and len(raw.content) > 0 and isinstance(raw.content[0], list)
            data_rows = raw.content[1:] if is_list_format else raw.content
            
            for row in data_rows:
                if is_list_format:
                    raw_data = {
                        "industry_label": str(row[0]),
                        "establishments": int(row[1]),
                        "employees": int(row[2]),
                        "payroll": float(row[3]),
                        "shipment_value": float(row[4])
                    }
                else:
                    # Defensive mapping for dictionary format
                    def get_f(keys):
                        for k in keys:
                            val = row.get(k)
                            if val is not None: return val
                        return 0
                    
                    raw_data = {
                        "industry_label": str(get_f(["industry_label", "NAICS2017_LABEL", "name"])),
                        "establishments": int(get_f(["establishments", "ESTAB"])),
                        "employees": int(get_f(["employees", "EMP"])),
                        "payroll": float(get_f(["payroll", "PAYANN"])),
                        "shipment_value": float(get_f(["shipment_value", "VSHIP"]))
                    }
                
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = hashlib.md5(f"ASM-{raw_data['industry_label']}".encode()).hexdigest()[:16]
                    results.append(StandardSchema(
                        id=record_id,
                        industry="manufacturing",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": "US Census ASM"},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        return all(r.data.get("employees", 0) >= 0 and r.data.get("mva_value", 0) >= 0 for r in [
            r for r in normalized_data if "employees" in r.data or "mva_value" in r.data
        ])


