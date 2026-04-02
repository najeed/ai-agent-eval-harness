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
        mode = config.get("demographics_mode") or config.get("schema_type") or "census"
        self.demographics_mode = mode.lower().replace("_", "")
        self.api_key = config.get("census_api_key")
        
    async def extract(self) -> List[RawArtifact]:
        industry = self.config.get("industry", "public_sector")
        
        if self.demographics_mode == "worldbank":
            indicator = self.config.get("indicator", "SP.POP.TOTL")
            url = f"https://api.worldbank.org/v2/country/all/indicator/{indicator}?format=json&per_page=100"
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # World Bank returns [ {paging}, [records] ]
                            if len(data) > 1 and isinstance(data, list):
                                return [RawArtifact(
                                    id=f"WB-POP-{indicator}",
                                    source_url=url,
                                    content=data[1],
                                    metadata={"indicator": indicator},
                                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                                )]
                except Exception as e:
                    logger.error("wb_demographics_extraction_failed", error=str(e))
            
            if self.allow_simulation:
                sim_wb = [
                    {"country": {"value": "United States"}, "date": "2022", "population": 333287557},
                    {"country": {"value": "China"}, "date": "2022", "population": 1412175000}
                ]
                return [self.create_simulated_artifact(
                    id=f"WB-POP-{indicator}",
                    content=sim_wb,
                    source_url=url,
                    metadata={"indicator": indicator}
                )]
            return []

        # Default: US Census
        url = "https://api.census.gov/data/2021/acs/acs5?get=NAME,B01001_001E&for=state:*"
        if self.api_key:
            url += f"&key={self.api_key}"
            
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return [RawArtifact(
                            id="CENSUS-POP-2021",
                            source_url=url,
                            content=data,
                            metadata={"year": 2021},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
            except Exception as e:
                logger.error("census_extraction_failed", error=str(e))
        
        if self.allow_simulation:
            sim_census = [
                ["NAME", "B01001_001E", "state"],
                ["Alabama", "5024279", "01"],
                ["Alaska", "733391", "02"],
                ["Arizona", "7151502", "04"]
            ]
            return [self.create_simulated_artifact(
                id="CENSUS-POP-SIM",
                content=sim_census,
                source_url=url,
                metadata={"year": 2021}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        industry = self.config.get("industry", "public_sector")
        
        if self.demographics_mode == "worldbank":
            TARGET_SCHEMA = {"country": "string", "year": "integer", "population": "number"}
            for raw in raw_artifacts:
                # Handle potential mixed list from World Bank and simulations
                data_list = raw.content
                # Robust two-tier detection
                if isinstance(data_list, list) and len(data_list) > 0 and isinstance(data_list[0], dict) and "page" in data_list[0]:
                    data_list = data_list[1]
                
                if not isinstance(data_list, list):
                    data_list = [raw.content]
                
                for row in data_list:
                    if not isinstance(row, dict):
                        continue
                    
                    # Robust field extraction (Support simulation AND real WB API)
                    pop_val = row.get("population") or row.get("value")
                    country_val = row.get("country", {}).get("value") if isinstance(row.get("country"), dict) else row.get("country")
                    date_val = row.get("date") or row.get("year") or 0
                    
                    if pop_val is None:
                        continue # Skip paging records if they leaked in
                    
                    raw_data = {
                        "country": country_val or "Unknown",
                        "year": int(date_val),
                        "population": float(pop_val)
                    }
                    
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"WB-DEM-{raw_data['country']}-{raw_data['year']}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry=industry,
                            data=verified,
                            provenance={"source": raw.source_url, "schema": "WorldBank-Population"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        # Census Transformation
        TARGET_SCHEMA = {"state": "string", "population": "number"}
        for raw in raw_artifacts:
            # Handle non-list data from some parity mocks or extract errors
            if not isinstance(raw.content, list) or not raw.content:
                continue
            
            data = raw.content
            if len(data) > 1:
                header = data[0]
                try:
                    pop_idx = header.index("B01001_001E")
                    name_idx = header.index("NAME")
                except (ValueError, AttributeError):
                    logger.warning("invalid_census_header_skipping")
                    continue
                
                for row in data[1:]:
                    if not isinstance(row, list) or len(row) <= max(pop_idx, name_idx):
                        continue
                        
                    raw_data = {
                        "state": row[name_idx],
                        "population": float(row[pop_idx])
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"CENSUS-{verified['state']}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry=industry,
                            data=verified,
                            provenance={"source": raw.source_url, "schema": "US-Census-ACS"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            if record.data.get("population", 0) <= 0:
                return False
        return True
