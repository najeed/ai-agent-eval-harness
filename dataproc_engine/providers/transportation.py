import aiohttp
import os
import hashlib
import json
from typing import List, Dict, Any
import datetime
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("TransportationProvider")

class TransportationProvider(BaseProvider):
    """
    Gold Standard provider for Transportation (U.S. DOT BTS).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.api_key = config.get("dot_api_key")
        self.mode = config.get("transit_mode", "air") # air, rail, road, osm, eurostat
        
    async def extract(self) -> List[RawArtifact]:
        """Fetch Transportation stats (Local, OSM, or Eurostat)."""
        if self.mode == "osm":
            # Overpass API for high-resolution geospatial benchmarks
            bbox = self.config.get("bbox", "51.47,-0.15,51.51,-0.10") # Sample London BBox
            url = f"https://overpass-api.de/api/interpreter?data=[out:json];node({bbox});way({bbox})['highway'];out;"
            
            async with aiohttp.ClientSession() as session:
                async def fetch_osm():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        raise Exception(f"OSM API Error: {resp.status}")
                
                try:
                    content = await self.request_with_retry(fetch_osm)
                    if content and "elements" in content:
                        return [RawArtifact(
                            id=f"OSM-{bbox}",
                            source_url=url,
                            content=content["elements"][: self.config.get("limit", 20)],
                            metadata={"bbox": bbox, "source": "Overpass-API"},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception as e:
                    logger.error("osm_extraction_failed", bbox=bbox, error=str(e))
            
            if self.allow_simulation:
                return [self.create_simulated_artifact(
                    id=f"OSM-{bbox}",
                    content=[{"id": 12345, "type": "way", "tags": {"highway": "primary", "name": "Global Way"}}],
                    source_url=url,
                    metadata={"bbox": bbox}
                )]
            return []

        if self.mode == "eurostat":
            # Eurostat API for international maritime/road logistics
            indicator = self.config.get("indicator", "ttr00002") # Road freight transport
            url = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/wfs/v2.1/json?indicator={indicator}"
            
            if self.allow_simulation:
                simulated_eurostat = [
                    {"geo": "FR", "mode": "Road", "value": 150.5, "unit": "Mio TKM", "time": "2021"},
                    {"geo": "DE", "mode": "Road", "value": 180.2, "unit": "Mio TKM", "time": "2021"}
                ]
                return [self.create_simulated_artifact(
                    id=f"EURO-{indicator}",
                    content=simulated_eurostat,
                    source_url=url,
                    metadata={"indicator": indicator}
                )]
            return []

        input_path = self.config.get("input_uri") or ""
        default_local = "industries/airline/datasets/airline_performance.csv"
        path = input_path or default_local
        
        df = self.load_raw_data(path)
        if df is not None:
            records = df.head(self.config.get("limit", 10)).to_dict(orient="records")
            return [RawArtifact(
                id="DOT-BTS-EXT",
                source_url=str(path),
                content=records,
                metadata={"mode": "airline_on_time", "is_external": True},
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]
        
        if self.allow_simulation:
            sim_bts = [
                {"carrier": "AA", "on_time_pct": 85.5, "canceled_pct": 1.2, "period": "2023-01"},
                {"carrier": "DL", "on_time_pct": 88.2, "canceled_pct": 0.8, "period": "2023-01"}
            ]
            return [self.create_simulated_artifact(
                id="sim-BTS-airline",
                content=sim_bts,
                source_url="https://www.transtats.bts.gov/",
                metadata={"mode": "airline_performance"}
            )]

        logger.error("dot_no_data_source_found")
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        TARGET_SCHEMA = {
            "entity": "string",
            "metric_name": "string",
            "metric_value": "number",
            "period": "string",
            "status": "string"
        }
        
        for raw in raw_artifacts:
            if self.mode == "osm":
                OSM_SCHEMA = {"id": "string", "type": "string", "highway": "string", "name": "string"}
                for item in raw.content:
                    tags = item.get("tags", {})
                    data = {
                        "id": str(item.get("id")),
                        "type": item.get("type"),
                        "highway": tags.get("highway", "unknown"),
                        "name": tags.get("name", "Unnamed")
                    }
                    verified = self.llm_manager._verify_schema(data, OSM_SCHEMA, strict=True)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(f"OSM-{data['id']}".encode()).hexdigest()[:16],
                            industry="transportation",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "OpenStreetMap"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
                continue

            if self.mode == "eurostat":
                EURO_SCHEMA = {"geo": "string", "mode": "string", "value": "number", "unit": "string", "time": "string"}
                for item in raw.content:
                    verified = self.llm_manager._verify_schema(item, EURO_SCHEMA, strict=True)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(f"EURO-{item['geo']}-{item['time']}".encode()).hexdigest()[:16],
                            industry="transportation",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "Eurostat"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
                continue

            for item in raw.content:
                data = {
                    "entity": item.get("carrier") or item.get("operator"),
                    "metric_name": "on_time_performance_pct",
                    "metric_value": float(item.get("on_time_pct", 0)),
                    "period": item.get("period"),
                    "status": "Operational" if float(item.get("canceled_pct", 100)) < 10 else "Disrupted"
                }
                
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
                if verified_data:
                    unique_str = f"{data['entity']}-{data['period']}"
                    record_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="transportation",
                        data=verified_data,
                        provenance={"source": raw.source_url, "provider": "US-DOT"},
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        if not normalized_data:
            return True
            
        for record in normalized_data:
            if self.mode == "osm":
                if not record.data.get("id"): return False
            elif self.mode == "eurostat":
                if record.data.get("value") is None: return False
            else:
                # Default BTS logic
                val = record.data.get("metric_value", 0)
                if not (0 <= val <= 100): return False
        return True





