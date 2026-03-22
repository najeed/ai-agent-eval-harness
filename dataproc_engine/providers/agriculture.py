import aiohttp
import os
import hashlib
import json
from typing import List, Dict, Any
from datetime import datetime
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
        self.year = config.get("year", datetime.now().year - 1)
        
        if not self.api_key:
            logger.warning("usda_api_key_missing", status="Using public access limit if available")

    async def extract(self) -> List[RawArtifact]:
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
                    timestamp=datetime.utcnow().isoformat()
                )]
            logger.error("usda_no_data_source_found")
            return []

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        records = data.get("data", [])[:self.config.get("limit", 10)]
                        return [RawArtifact(
                            id=f"USDA-{self.commodity}",
                            source_url=str(resp.url),
                            content=records,
                            metadata={"commodity": self.commodity},
                            timestamp=datetime.utcnow().isoformat()
                        )]
            except Exception as e:
                logger.error("usda_extraction_failed", error=str(e))
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        TARGET_SCHEMA = {
            "commodity": "string",
            "year": "integer",
            "yield_value": "number",
            "unit": "string",
            "location": "string"
        }
        
        for raw in raw_artifacts:
            for item in raw.content:
                data = {
                    "commodity": item.get("commodity_desc"),
                    "year": int(item.get("year", 0)),
                    "yield_value": float(str(item.get("Value", "0")).replace(",", "")),
                    "unit": item.get("unit_desc"),
                    "location": item.get("state_alpha")
                }
                
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
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
        return all(r.data["yield_value"] >= 0 for r in normalized_data)
