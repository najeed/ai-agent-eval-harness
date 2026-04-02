import aiohttp
import os
import hashlib
import json
from typing import List, Dict, Any
import datetime
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("AgricultureProvider")

class AgricultureProvider(BaseProvider):
    """
    Gold Standard provider for Agriculture (USDA NASS Quick Stats).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.api_key = config.get("usda_api_key")
        self.commodity = config.get("commodity", "CORN")
        self.year = config.get("year", datetime.datetime.now().year - 1)
        self.agriculture_mode = config.get("agriculture_mode") or config.get("schema_type") or "usda"
        
    async def extract(self) -> List[RawArtifact]:
        artifacts = []
        if self.agriculture_mode == "faostat":
            # Gold Standard: FAOStat (UN Food and Agriculture Organization)
            domain = self.config.get("domain", "QCL") # Crops and livestock products
            url = f"https://fenixservices.fao.org/faostat/api/v1/en/data/{domain}"
            
            if self.allow_simulation:
                simulated_faostat = [
                    {"Area": "World", "Item": "Wheat", "Year": 2022, "Value": 770000000, "Unit": "tonnes"},
                    {"Area": "World", "Item": "Rice", "Year": 2022, "Value": 510000000, "Unit": "tonnes"}
                ]
                return [self.create_simulated_artifact(
                    id=f"sim-FAOSTAT-{domain}",
                    content=simulated_faostat,
                    source_url=url,
                    metadata={"domain": domain}
                )]
            return []

        """Fetch Agriculture yield/pricing data from USDA."""
        # URI: https://quickstats.nass.usda.gov/api/api_GET/?key=API_KEY&commodity_desc=CORN&year__GE=2023&state_alpha=IA
        url = "https://quickstats.nass.usda.gov/api/api_GET/"
        params = {
            "key": self.api_key,
            "commodity_desc": self.commodity,
            "year__GE": self.year,
            "format": "JSON"
        }
        
        # Unified Data Acquisition (Local or Web URL)
        input_path = self.config.get("input_uri") or ""
        default_local = "industries/agriculture/datasets/commodity_prices.csv"
        path = input_path or default_local
        
        if not self.api_key:
            df = self.load_raw_data(path)
            if df is not None:
                # Filter by commodity and limit
                records = df[df["commodity_desc"] == self.commodity].head(self.config.get("limit", 10)).to_dict(orient="records")
                return [RawArtifact(
                    id=f"USDA-{self.commodity}-EXT",
                    source_url=str(path),
                    content=records,
                    metadata={"commodity": self.commodity, "is_external": True},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]
            if self.allow_simulation:
                sim_usda = [
                    {"commodity_desc": self.commodity, "year": self.year, "Value": "180.5", "unit_desc": "BU / ACRE", "state_alpha": "IA"},
                    {"commodity_desc": self.commodity, "year": self.year, "Value": "175.2", "unit_desc": "BU / ACRE", "state_alpha": "IL"}
                ]
                return [self.create_simulated_artifact(
                    id=f"sim-USDA-{self.commodity}",
                    content=sim_usda,
                    source_url=url,
                    metadata={"commodity": self.commodity, "simulation": True}
                )]
            logger.error("usda_no_data_source_found")
            return []

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        records = data.get("data", [])[:self.config.get("limit", 10)]
                        artifacts = [RawArtifact(
                            id=f"USDA-{self.commodity}",
                            source_url=str(resp.url),
                            content=records,
                            metadata={"commodity": self.commodity},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
            except Exception as e:
                logger.error("usda_extraction_failed", error=str(e))
        
        if not artifacts and self.allow_simulation:
            # High-fidelity Simulation Contract (V2.0 Stabilization)
            sim_content = []
            if self.agriculture_mode == "faostat":
                sim_content = [
                    {"Area": "World", "Item": "Wheat", "Year": 2022, "Value": 770000000, "Unit": "tonnes"},
                    {"Area": "World", "Item": "Rice", "Year": 2022, "Value": 510000000, "Unit": "tonnes"}
                ]
            else:
                sim_content = [
                    {"commodity_desc": self.commodity, "year": self.year, "Value": "180.5", "unit_desc": "BU / ACRE", "state_alpha": "IA"},
                    {"commodity_desc": self.commodity, "year": self.year, "Value": "175.2", "unit_desc": "BU / ACRE", "state_alpha": "IL"}
                ]
            
            logger.info("using_high_fidelity_simulation", mode=self.agriculture_mode)
            artifacts.append(self.create_simulated_artifact(
                id=f"sim-FAOSTAT",
                content=sim_content,
                source_url="https://simulated-agriculture.example.org/",
                metadata={"mode": self.agriculture_mode}
            ))

        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        is_strict = self.llm_manager.strategy not in ["heuristic", "mock"]
        
        TARGET_SCHEMA = {
            "commodity": "string",
            "year": "integer",
            "yield_value": "number",
            "unit": "string",
            "location": "string"
        }
        
        if self.agriculture_mode == "faostat":
            TARGET_SCHEMA = {"location": "string", "item": "string", "year": "integer", "value": "number", "unit": "string"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "location": row.get("Area", "Unknown"),
                        "item": row.get("Item", "Unknown"),
                        "year": int(row.get("Year", 0)),
                        "value": float(row.get("Value", 0)),
                        "unit": row.get("Unit", "Unknown")
                    }
                    # 3. Decision Support: Apply Yield Elasticity if climate anomaly present
                    climate_anomaly = self.config.get("climate_anomaly", 0) # e.g. +2.5C
                    if climate_anomaly > 0:
                        # Simple linear elasticity: -5% yield for every degree above norm
                        elasticity_factor = 1 - (climate_anomaly * 0.05)
                        raw_data["value"] = round(raw_data.get("value", 0) * elasticity_factor, 2)
                        raw_data["note"] = f"Adjusted for climate anomaly (+{climate_anomaly}C)"
                    
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=is_strict)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(f"FAO-{raw_data['location']}-{raw_data['item']}-{raw_data['year']}".encode()).hexdigest()[:16],
                            industry="agriculture",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "FAOStat"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        for raw in raw_artifacts:
            for item in raw.content:
                data = {
                    "commodity": item.get("commodity_desc"),
                    "year": int(item.get("year", 0)),
                    "yield_value": float(str(item.get("Value", "0")).replace(",", "")),
                    "unit": item.get("unit_desc"),
                    "location": item.get("state_alpha")
                }
                
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=is_strict)
                if verified_data:
                    unique_str = f"{item.get('commodity_desc')}-{item.get('year')}-{item.get('state_alpha')}"
                    record_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="agriculture",
                        data=verified_data,
                        provenance={"source": raw.source_url, "provider": "USDA-NASS"},
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            # Handle both USDA yield_value and FAOStat value
            val = record.data.get("yield_value") or record.data.get("value")
            if val is not None and val < 0:
                return False
        return True





