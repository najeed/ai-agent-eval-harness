import aiohttp
import os
import hashlib
import json
import logging
import pandas as pd
from typing import List, Dict, Any
import datetime
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
import json
import asyncio
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("EnergyProvider")

class EnergyProvider(BaseProvider):
    """
    Deepened Consumer for EIA API - Multi-series (WTI, Brent, NatGas).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.api_key = config.get("eia_api_key")
        # Support multiple series IDs
        default_series = ["PET.RWTC.D", "PET.RBRTE.D", "NG.RNGC1.D"] # WTI, Brent, Henry Hub
        self.series_ids = config.get("series_ids", default_series)
        self.schema_type = config.get("schema_type", "eia") # eia, energy_balances, opsd
        
        # Alias mapping for better usability
        ALIASES = {"balances": "energy_balances", "power": "opsd"}
        if self.schema_type in ALIASES:
            self.schema_type = ALIASES[self.schema_type]
        
        if not self.api_key and self.schema_type == "eia":
            logger.warning("api_key_missing", status="Extraction will use local mock logic if available")

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type == "opsd":
            # Gold Standard: Open Power System Data (OPSD) - European Grid Balances
            region = self.config.get("region", "DE") # Germany default
            url = f"https://data.open-power-system-data.org/time_series/latest/time_series_60min_singleindex.csv"
            
            if self.allow_simulation:
                simulated_opsd = [
                    {"utc_timestamp": "2023-01-01T00:00:00Z", "region": region, "load": 45000, "solar": 0, "wind": 12000},
                    {"utc_timestamp": "2023-01-01T12:00:00Z", "region": region, "load": 55000, "solar": 8000, "wind": 11000}
                ]
                return [self.create_simulated_artifact(
                    id=f"OPSD-{region}",
                    content=simulated_opsd,
                    source_url=url,
                    metadata={"region": region, "source": "OPSD-Time-Series"}
                )]
            return []

        if self.schema_type == "energy_balances":
            # Gold Standard: Global Energy Balances (Simulated)
            
            # Unified Data Acquisition (Local or Web URL)
            path = self.config.get("input_uri") or ""
            df = self.load_raw_data(path)
            
            if df is not None:
                return [RawArtifact(
                    id="ENERGY-BALANCE-USER",
                    source_url=path,
                    content=df.to_dict(orient="records"),
                    metadata={"dataset": "Generic Energy Balances", "source": "User-Provided"},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]
            
            if self.api_key:
                logger.info("using_energy_api_key", key_preview=self.api_key[:4] + "...")
                # Real extraction logic would go here
            
            if self.allow_simulation:
                import random
                countries = ["USA", "CHN", "DEU", "NOR", "FRA", "IND", "BRA", "JPN"]
                simulated_balances = [
                    {"country": random.choice(countries), "flow": "Consumption", "product": "Electricity", "value": 1500.0, "unit": "Mtoe"}
                ]
                return [self.create_simulated_artifact(
                    id="sim-energy-balances",
                    content=simulated_balances,
                    source_url="https://energy.data.example.org/",
                    metadata={"dataset": "Global Energy Balances", "simulation": "Dynamic"}
                )]
            return []

        """Fetch Energy data from EIA API or local CSV."""
        # Unified Data Acquisition (Local or Web URL)
        path = self.config.get("input_uri") or ""
        df = self.load_raw_data(path)
        
        if df is not None:
            return [RawArtifact(
                id="energy-local",
                source_url=path,
                content=df.to_dict(orient="records"),
                metadata={},
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]
        
        # EIA API Extraction
        if not self.api_key:
            if self.allow_simulation:
                simulated_eia = [
                    {"series_id": "PET.RWTC.D", "series_name": "Cushing, OK WTI Spot Price FOB", "value": 75.4, "unit": "USD/BBL", "date": "2023-01-01"},
                    {"series_id": "NG.RNGC1.D", "series_name": "Henry Hub Natural Gas Spot Price", "value": 2.5, "unit": "USD/MMBTU", "date": "2023-01-01"}
                ]
                return [self.create_simulated_artifact(
                    id="sim-EIA-DEFAULT",
                    content=simulated_eia,
                    source_url="https://api.eia.gov/",
                    metadata={"dataset": "EIA Petroleum/Natural Gas", "simulation": "Fallback"}
                )]
            logger.error("eia_api_key_missing_no_fallback")
            return []

        limit = self.config.get("limit", 20)
        artifacts = []
        
        async with aiohttp.ClientSession() as session:
            async def fetch_series(sid):
                url = f"https://api.eia.gov/series/?api_key={self.api_key}&series_id={sid}"
                
                async def fetch_eia():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        logger.error("eia_api_failure", status=resp.status, series_id=sid)
                        return None

                try:
                    logger.info("queuing_eia_fetch", series_id=sid)
                    data = await self.request_with_retry(fetch_eia)
                    if data and "series" in data:
                        metadata = data["series"][0]
                        points = metadata.get("data", [])[:limit]
                        return RawArtifact(
                            id=sid,
                            source_url=url,
                            content=points,
                            metadata={
                                "series_name": metadata.get("name", "Unknown"),
                                "units": metadata.get("units", "Units")
                            },
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )
                except Exception as e:
                    logger.error("eia_extraction_failed", series_id=sid, error=str(e))
                return None

            tasks = [fetch_series(sid) for sid in self.series_ids]
            results = await asyncio.gather(*tasks)
            artifacts = [r for r in results if r]
            
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        import json
        import hashlib
        results = []

        if self.schema_type == "opsd":
            TARGET_SCHEMA = {"region": "string", "utc_timestamp": "string", "load": "number", "solar": "number", "wind": "number"}
            for raw in raw_artifacts:
                for row in raw.content:
                    verified = self.llm_manager._verify_schema(row, TARGET_SCHEMA, strict=True)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(f"OPSD-{row['region']}-{row['utc_timestamp']}".encode()).hexdigest()[:16],
                            industry="energy",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "OPSD"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        if self.schema_type == "energy_balances":
            TARGET_SCHEMA = {
                "country_code": "string",
                "energy_flow": "string",
                "energy_product": "string",
                "flow_value": "number",
                "unit_of_measure": "string"
            }
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "country_code": row.get("country"),
                        "energy_flow": row.get("flow"),
                        "energy_product": row.get("product"),
                        "flow_value": float(row.get("value", 0)),
                        "unit_of_measure": row.get("unit")
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"ENERGY-{row.get('country_code') or row.get('country')}-{row.get('energy_product') or row.get('product')}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="energy",
                            data=verified,
                            provenance={"source": raw.source_url, "schema": "Energy-Balances-V1"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        TARGET_SCHEMA = {
            "series_id": "string",
            "series_name": "string",
            "latest_value": "number",
            "unit": "string",
            "period": "string"
        }
        
        for raw in raw_artifacts:
            for item in raw.content:
                if isinstance(item, dict):
                    row = item
                    data = {
                        "series_id": row.get("series_id") or raw.id,
                        "series_name": row.get("series_name") or raw.metadata.get("series_name", "Local Energy Metric"),
                        "latest_value": float(row.get("value") or 0),
                        "unit": row.get("unit") or raw.metadata.get("units", "Units"),
                        "period": str(row.get("date") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
                    }
                else:
                    # EIA List[date, value] format
                    point = item
                    if len(point) < 2: continue
                    data = {
                        "series_id": raw.id,
                        "series_name": raw.metadata.get("series_name"),
                        "latest_value": float(point[1]),
                        "unit": raw.metadata.get("units", "USD"),
                        "period": str(point[0])
                    }
                
                # Strict Schema Verification
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
                if verified_data:
                    # Deterministic ID based on unique data fields
                    unique_str = f"{raw.id}-{data.get('period', data.get('date'))}"
                    record_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="energy",
                        data=verified_data,
                        provenance={"source": raw.source_url, "retrieved_at": raw.timestamp},
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            if self.schema_type == "energy_balances":
                if record.data.get("flow_value", 0) < 0: return False
            elif self.schema_type == "opsd":
                if record.data.get("load", 0) < 0: return False
            else:
                # Basic industrial sanity check
                if record.data["latest_value"] is not None and record.data["latest_value"] < -50: # Oil went negative once
                    logger.warning("anomaly_detected", record_id=record.id, value=record.data["latest_value"])
                    return False
        return True





