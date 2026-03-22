import aiohttp
import os
import hashlib
import json
from typing import List, Dict, Any
from datetime import datetime
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
        self.mode = config.get("transit_mode", "air") # air, rail, road
        
    async def extract(self) -> List[RawArtifact]:
        """Fetch Transportation stats (Local or URL)."""
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
                timestamp=datetime.utcnow().isoformat()
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
        return all(0 <= r.data["metric_value"] <= 100 for r in normalized_data)
