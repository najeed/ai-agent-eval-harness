import hashlib
import json
import asyncio
import aiohttp
import os
import pandas as pd
import datetime
from typing import List, Dict, Any, Optional
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("DemographicsProvider")

class DemographicsProvider(BaseProvider):
    """
    Provider for Demographics data (US Census & World Bank Population).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.demographics_mode = config.get("demographics_mode", "census")
        self.api_key = config.get("census_api_key")
        
    async def extract(self) -> List[RawArtifact]:
        if self.demographics_mode == "worldbank":
            # Gold Standard: World Bank Population Data
            indicator = self.config.get("indicator", "SP.POP.TOTL") # Total Population
            country = self.config.get("country", "all")
            url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json"
            
            async with aiohttp.ClientSession() as session:
                async def fetch_wb():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        return None
                
                try:
                    data = await self.request_with_retry(fetch_wb)
                    if data and len(data) > 1:
                        records = data[1][:self.config.get("limit", 20)]
                        return [RawArtifact(
                            id=f"WB-POP-{indicator}",
                            source_url=url,
                            content=records,
                            metadata={"indicator": indicator, "source": "World Bank"},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception as e:
                    logger.error("wb_demographics_extraction_failed", error=str(e))
            
            if self.allow_simulation:
                sim_wb = [
                    {"country": {"id": "USA", "value": "United States"}, "date": "2022", "value": 333287557},
                    {"country": {"id": "CHN", "value": "China"}, "date": "2022", "value": 1412175000}
                ]
                return [self.create_simulated_artifact(
                    id=f"WB-POP-{indicator}",
                    content=sim_wb,
                    source_url=url,
                    metadata={"indicator": indicator}
                )]
            return []

        # Default: US Census Bureau API
        year = self.config.get("year", 2022)
        dataset = self.config.get("dataset", "acs/acs5") # American Community Survey
        url = f"https://api.census.gov/data/{year}/{dataset}?get=NAME,B01001_001E&for=state:*"
        
        if self.allow_simulation:
            sim_census = [
                ["NAME", "B01001_001E", "state"],
                ["California", "39029342", "06"]
            ]
            return [self.create_simulated_artifact(
                id=f"CENSUS-{year}",
                content=sim_census,
                source_url=url,
                metadata={"dataset": dataset, "year": year}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        is_strict = self.llm_manager.strategy not in ["heuristic", "mock"]
        
        if self.demographics_mode == "worldbank":
            TARGET_SCHEMA = {"country": "string", "year": "integer", "population": "number"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "country": row.get("country", {}).get("value", "Unknown"),
                        "year": int(row.get("date", 0)),
                        "population": float(row.get("value") or 0)
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"WB-DEM-{raw_data['country']}-{raw_data['year']}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="demographics",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "World Bank"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        # US Census (Tabular Census API format)
        TARGET_SCHEMA = {"state": "string", "population": "number", "year": "integer"}
        for raw in raw_artifacts:
            # Census API and Parity Mocks use different formats (List-of-Lists vs List-of-Dicts)
            is_list_format = isinstance(raw.content, list) and len(raw.content) > 0 and isinstance(raw.content[0], list)
            data_rows = raw.content[1:] if is_list_format else raw.content
            
            for row in data_rows:
                if is_list_format:
                    raw_data = {
                        "state": str(row[0]),
                        "population": float(row[1]),
                        "year": int(raw.metadata.get("year", 2022))
                    }
                else:
                    # Defensive mapping for dictionary results
                    raw_data = {
                        "state": str(row.get("NAME") or row.get("state") or "Unknown"),
                        "population": float(row.get("B01001_001E") or row.get("population") or 0),
                        "year": int(raw.metadata.get("year") or row.get("year", 2022))
                    }
                
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = hashlib.md5(f"CENSUS-{raw_data['state']}-{raw_data['year']}".encode()).hexdigest()[:16]
                    results.append(StandardSchema(
                        id=record_id,
                        industry="demographics",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": "US Census"},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        return all(r.data.get("population", 0) >= 0 for r in normalized_data)





