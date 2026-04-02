import hashlib
import json
import asyncio
import aiohttp
import datetime
from typing import List, Dict, Any
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("LaborProvider")

class LaborProvider(BaseProvider):
    """
    Provider for Labor & Employment data (BLS & ILO).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.labor_mode = config.get("labor_mode", "bls") # bls, ilo
        self.api_key = config.get("bls_api_key")

    async def extract(self) -> List[RawArtifact]:
        if self.labor_mode == "ilo":
            # Gold Standard: ILO (International Labour Organization)
            indicator = self.config.get("indicator", "EMP_TEMP_SEX_AGE_RT")
            url = f"https://www.ilo.org/ilostat-with-db/rest/data/{indicator}"
            
            if self.allow_simulation:
                sim_ilo = [
                    {"ref_area": "USA", "time": "2023", "obs_value": 3.7},
                    {"ref_area": "GBR", "time": "2023", "obs_value": 4.2}
                ]
                return [self.create_simulated_artifact(
                    id="ILO-LABOR",
                    content=sim_ilo,
                    source_url=url,
                    metadata={"indicator": indicator}
                )]
            return []

        # US Bureau of Labor Statistics (BLS)
        series_id = self.config.get("series_id", "LNS14000000") # Unemployment Rate
        url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        
        if self.allow_simulation:
            sim_bls = [
                {"year": "2023", "period": "M01", "value": "3.4"},
                {"year": "2023", "period": "M02", "value": "3.6"}
            ]
            return [self.create_simulated_artifact(
                id=f"BLS-{series_id}",
                content=sim_bls,
                source_url=url,
                metadata={"series_id": series_id}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        TARGET_SCHEMA = {"location": "string", "period": "string", "unemployment_rate": "number"}
        
        for raw in raw_artifacts:
            for row in raw.content:
                if self.labor_mode == "ilo":
                    data = {
                        "location": row.get("ref_area"),
                        "period": row.get("time"),
                        "unemployment_rate": float(row.get("obs_value", 0))
                    }
                else:
                    data = {
                        "location": "USA",
                        "period": f"{row.get('year')}-{row.get('period')}",
                        "unemployment_rate": float(row.get("value", 0))
                    }
                
                verified = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = hashlib.md5(f"LABOR-{data['location']}-{data['period']}".encode()).hexdigest()[:16]
                    results.append(StandardSchema(
                        id=record_id,
                        industry="labor",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": self.labor_mode.upper()},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        return all(0 <= r.data.get("unemployment_rate", 0) <= 100 for r in normalized_data)


