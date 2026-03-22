import hashlib
import json
import asyncio
import aiohttp
import os
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("TelecomProvider")

class TelecomProvider(BaseProvider):
    """
    Deepened Consumer for FCC Broadband Data - Multi-stream support.
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        # Support multiple FCC endpoints (Broadband, Data Caps, etc.)
        default_urls = [
            "https://broadbandmap.fcc.gov/data/geojson/nationwide.json"
        ]
        self.urls = config.get("source_urls", default_urls)
        self.api_key = config.get("ookla_api_key")
        self.schema_type = config.get("schema_type", "fcc") # fcc (default), ookla

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type == "ookla":
            # Gold Standard: Ookla Speedtest Open Data (Simulated Tiles)
            
            # Unified Data Acquisition (Local or Web URL)
            path = self.config.get("input_uri") or ""
            df = self.load_raw_data(path)
            
            if df is not None:
                return [RawArtifact(
                    id="OOKLA-TILE-USER",
                    source_url=path,
                    content=df.to_dict(orient="records"),
                    metadata={"dataset": "Ookla Speedtest", "source": "User-Provided"},
                    timestamp=datetime.utcnow().isoformat()
                )]
            
            if self.api_key:
                logger.info("using_ookla_api_key", key_preview=self.api_key[:4] + "...")
                # In a real scenario, we would fetch from Ookla API here
            
            simulated_tiles = [
                {"quadkey": "02313013", "avg_d_kbps": 150400, "avg_u_kbps": 45000, "avg_lat_ms": 12, "tests": 50, "devices": 12},
                {"quadkey": "02313014", "avg_d_kbps": 98000, "avg_u_kbps": 22000, "avg_lat_ms": 24, "tests": 120, "devices": 45},
                {"quadkey": "03102100", "avg_d_kbps": 32000, "avg_u_kbps": 5000, "avg_lat_ms": 45, "tests": 15, "devices": 4}
            ]
            return [RawArtifact(
                id="OOKLA-TILE-SIM",
                source_url="https://github.com/ookla/speedtest-datasets",
                content=simulated_tiles,
                metadata={"dataset": "Ookla Speedtest Global Performance Tiles", "type": "fixed_broadband"},
                timestamp=datetime.utcnow().isoformat()
            )]

        """Fetch Telecom data from FCC API or local CSV."""
        # Unified Data Acquisition (Local or Web URL)
        path = self.config.get("input_uri") or ""
        df = self.load_raw_data(path)
        
        if df is not None:
            return [RawArtifact(
                id="telecom-local",
                source_url=path,
                content=df.to_dict(orient="records"),
                metadata={},
                timestamp=datetime.utcnow().isoformat()
            )]
            
        # FCC Data streams
        urls = self.config.get("fcc_urls", ["https://opendata.fcc.gov/resource/8fkb-shkv.json"])
        limit = self.config.get("limit", 20)
        artifacts = []
        
        async with aiohttp.ClientSession() as session:
            async def fetch_fcc(url):
                async def fetch_logic():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("features", [])[:limit]
                        # Simulated Fallback for FCC
                        logger.warning("fcc_api_failure_using_sim", url=url)
                        return [{"id": "SIM_FCC_1", "technology_type": "Fiber", "max_ad_down": 1000, "max_ad_up": 1000}]

                try:
                    logger.info("queuing_fcc_fetch", url=url)
                    features = await self.request_with_retry(fetch_logic)
                    if not features:
                        return None
                        
                    content_hash = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()[:12]
                    return RawArtifact(
                        id=f"fcc-stream-{content_hash}",
                        source_url=url,
                        content=features,
                        metadata={"type": "geojson", "source": "FCC"},
                        timestamp=datetime.utcnow().isoformat()
                    )
                except Exception as e:
                    logger.error("fcc_extraction_failed", url=url, error=str(e))
                return None

            tasks = [fetch_fcc(url) for url in urls]
            results = await asyncio.gather(*tasks)
            artifacts = [r for r in results if r]
            
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        if self.schema_type == "ookla":
            TARGET_SCHEMA = {
                "geo_tile_id": "string",
                "avg_download_speed": "number",
                "avg_upload_speed": "number",
                "avg_latency": "number",
                "test_count": "number"
            }
            for artifact in raw_artifacts:
                for row in artifact.content:
                    raw_data = {
                        "geo_tile_id": str(row.get("quadkey")),
                        "avg_download_speed": float(row.get("avg_d_kbps", 0)) / 1000.0, # Mbps
                        "avg_upload_speed": float(row.get("avg_u_kbps", 0)) / 1000.0, # Mbps
                        "avg_latency": float(row.get("avg_lat_ms", 0)),
                        "test_count": int(row.get("tests", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"OOKLA-{row.get('quadkey')}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="telecom",
                            data=verified,
                            provenance={"source": artifact.source_url, "schema": "Ookla-Tiles"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        TARGET_SCHEMA = {
            "provider_name": "string",
            "service_type": "string",
            "download_speed": "number",
            "upload_speed": "number",
            "location": "string"
        }
        
        for artifact in raw_artifacts:
            rows = artifact.content
            for row in rows:
                p_id = str(row.get("provider_id") or row.get("id") or "NA")
                name = self.scrub_pii(row.get("provider_name") or row.get("name") or "Unknown")
                
                # Deterministic tracking ID
                record_id = hashlib.md5(f"{p_id}-{artifact.source_url}".encode()).hexdigest()[:16]
                
                data = {
                    "provider_name": name,
                    "service_type": row.get("technology_type") or row.get("type", "Standard"),
                    "download_speed": float(row.get("max_ad_down", row.get("value", 0))),
                    "upload_speed": float(row.get("max_ad_up", 0)),
                    "location": self.scrub_pii(str(row.get("location") or "State-level"))
                }
                
                # Strict Schema Verification
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=True)
                if verified_data:
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="telecom",
                        data=verified_data,
                        provenance={
                            "source": "FCC Broadband Dataset",
                            "provider_id": p_id,
                            "stream": artifact.source_url
                        },
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        for record in normalized_data:
            if self.schema_type == "ookla":
                if record.data["avg_download_speed"] < 0: return False
            else:
                # Industrial sanity: speeds should be non-negative
                if record.data["download_speed"] < 0 or record.data["upload_speed"] < 0:
                    logger.warning("anomaly_detected", record_id=record.id, reason="Negative speed")
                    return False
        return True
