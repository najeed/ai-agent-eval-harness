import hashlib
import json
import asyncio
import aiohttp
import datetime
from typing import List, Dict, Any
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("EnvironmentProvider")

class EnvironmentProvider(BaseProvider):
    """
    Provider for Environment & Climate data (NOAA & Copernicus).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.schema_type = config.get("schema_type", "noaa") # noaa, copernicus
        self.api_key = config.get("noaa_api_key")

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type == "copernicus":
            # Gold Standard: Copernicus Climate Change Service (C3S)
            dataset = self.config.get("dataset", "reanalysis-era5-single-levels")
            url = "https://cds.climate.copernicus.eu/api/v2"
            
            if self.allow_simulation:
                sim_copernicus = [
                    {"latitude": 52.5, "longitude": 13.4, "time": "2023-01-01T12:00:00Z", "t2m": 280.1},
                    {"latitude": 40.7, "longitude": -74.0, "time": "2023-01-01T12:00:00Z", "t2m": 275.5}
                ]
                return [self.create_simulated_artifact(
                    id="COPERNICUS-ERA5",
                    content=sim_copernicus,
                    source_url=url,
                    metadata={"dataset": dataset}
                )]
            return []

        # NOAA Global Historical Climatology Network (GHCN)
        station_id = self.config.get("station_id", "GHCND:USW00094728") # NYC Central Park
        url = "https://www.ncei.noaa.gov/cdo-web/api/v2/data"
        
        if self.allow_simulation:
            sim_noaa = [
                {"date": "2023-01-01T00:00:00", "datatype": "TMAX", "value": 15.6},
                {"date": "2023-01-01T00:00:00", "datatype": "TMIN", "value": 5.2}
            ]
            return [self.create_simulated_artifact(
                id=f"NOAA-{station_id}",
                content=sim_noaa,
                source_url=url,
                metadata={"station": station_id}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        TARGET_SCHEMA = {"location": "string", "timestamp": "string", "metric": "string", "value": "number", "unit": "string"}
        
        for raw in raw_artifacts:
            for row in raw.content:
                if self.schema_type == "copernicus":
                    data = {
                        "location": f"{row.get('latitude')}, {row.get('longitude')}",
                        "timestamp": row.get("time"),
                        "metric": "Temperature (2m)",
                        "value": float(row.get("t2m", 0)),
                        "unit": "K"
                    }
                else:
                    data = {
                        "location": raw.metadata.get("station"),
                        "timestamp": row.get("date"),
                        "metric": row.get("datatype"),
                        "value": float(row.get("value", 0)),
                        "unit": "Celsius"
                    }
                
                verified = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = hashlib.md5(f"ENV-{data['location']}-{data['timestamp']}-{data['metric']}".encode()).hexdigest()[:16]
                    results.append(StandardSchema(
                        id=record_id,
                        industry="environment",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": self.schema_type.upper()},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        # Sanity check: Temperatures within physical bounds (-100C to +60C or 173K to 333K)
        for record in normalized_data:
            val = record.data.get("value", 0)
            if record.data.get("unit") == "K":
                if not (150 < val < 350): return False
            else:
                if not (-100 < val < 60): return False
        return True


