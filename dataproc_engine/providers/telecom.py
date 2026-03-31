import hashlib
import json
import asyncio
import aiohttp
import os
import pandas as pd
from typing import List, Dict, Any
import datetime
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
        self.telecom_mode = config.get("telecom_mode", "fcc") # fcc, ookla, itu

    async def extract(self) -> List[RawArtifact]:
        if self.telecom_mode == "itu":
            # Gold Standard: ITU ICT Statistics (UN International Telecommunication Union)
            indicator = self.config.get("indicator", "i271") # Individuals using the Internet
            url = f"https://www.itu.int/itu-d/sites/ictdata/api/v1/indicators/{indicator}"
            
            if self.allow_simulation:
                mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "industries", "telecom", "mock_itu.json")
                if os.path.exists(mock_path):
                    with open(mock_path, "r") as f:
                        simulated_itu = json.load(f)
                else:
                    simulated_itu = [
                        {"Country": "USA", "Year": 2022, "Value": 91.8, "Unit": "%"},
                        {"Country": "CHN", "Year": 2022, "Value": 75.6, "Unit": "%"}
                    ]
                return [self.create_simulated_artifact(
                    id=f"ITU-{indicator}",
                    content=simulated_itu,
                    source_url=url,
                    metadata={"indicator": indicator}
                )]
            return []
        
        if self.telecom_mode == "ookla":
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
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]
            
            if self.api_key:
                logger.info("using_ookla_api_key", key_preview=self.api_key[:4] + "...")
                # In a real scenario, we would fetch from Ookla API here
            
            if self.allow_simulation:
                mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "industries", "telecom", "mock_ookla.json")
                if os.path.exists(mock_path):
                    with open(mock_path, "r") as f:
                        simulated_tiles = json.load(f)
                else:
                    simulated_tiles = [
                        {"quadkey": "02313013", "avg_d_kbps": 150400, "avg_u_kbps": 45000, "avg_lat_ms": 12, "tests": 50, "devices": 12},
                        {"quadkey": "02313014", "avg_d_kbps": 98000, "avg_u_kbps": 22000, "avg_lat_ms": 24, "tests": 120, "devices": 45}
                    ]
                return [self.create_simulated_artifact(
                    id="OOKLA-TILE",
                    content=simulated_tiles,
                    source_url="https://github.com/ookla/speedtest-datasets",
                    metadata={"dataset": "Ookla Speedtest Global Performance Tiles", "type": "fixed_broadband"}
                )]
            return []

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
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]
            
        # FCC Data streams
        urls = self.config.get("fcc_urls", ["https://opendata.fcc.gov/resource/8fkb-shkv.json"])
        artifacts = []
        
        async with aiohttp.ClientSession() as session:
            async def fetch_fcc(url):
                limit = self.config.get("limit", 100)
                async def fetch_logic():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("features", [])[:limit]
                        
                        mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "industries", "telecom", "mock_fcc.json")
                        if os.path.exists(mock_path):
                            with open(mock_path, "r") as f:
                                return json.load(f)
                        return [{
                            "id": "SIM_FCC_1", 
                            "technology_type": "Fiber", 
                            "max_ad_down": 1000, 
                            "max_ad_up": 1000,
                            "provider_name": "Simulated Fiber Co",
                            "location": "Nationwide"
                        }]
                
                try:
                    logger.info("queuing_fcc_fetch", url=url)
                    features = await self.request_with_retry(fetch_logic)
                    if not features: return None
                    
                    return RawArtifact(
                        id=f"fcc-stream-{hashlib.md5(url.encode()).hexdigest()[:8]}",
                        source_url=url,
                        content=features,
                        metadata={"type": "geojson", "source": "FCC"},
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                    )
                except Exception as e:
                    logger.error("fcc_extraction_failed", url=url, error=str(e))
                return None

            tasks = [fetch_fcc(url) for url in urls]
            results = await asyncio.gather(*tasks)
            artifacts = [r for r in results if r]
            
        if not artifacts and self.allow_simulation:
            mock_path = os.path.join(os.path.dirname(__file__), "..", "..", "industries", "telecom", "mock_fcc.json")
            if os.path.exists(mock_path):
                with open(mock_path, "r") as f:
                    content = json.load(f)
            else:
                content = [{"id": "sim_fcc_1", "technology_type": "Fiber", "max_ad_down": 1000, "max_ad_up": 1000, "provider_name": "Simulated Fiber Co"}]
            
            return [self.create_simulated_artifact(
                id="sim-FCC-broadband",
                content=content,
                source_url="https://opendata.fcc.gov/",
                metadata={"source": "FCC-Simulation"}
            )]
            
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        is_strict = self.llm_manager.strategy not in ["heuristic", "mock"]

        if self.telecom_mode == "itu":
            TARGET_SCHEMA = {"country": "string", "year": "integer", "usage_value": "number", "unit": "string"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "country": row.get("Country", "Unknown"),
                        "year": int(row.get("Year", 0)),
                        "usage_value": float(row.get("Value", 0)),
                        "unit": row.get("Unit", "Unknown")
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=is_strict)
                    if verified:
                        results.append(StandardSchema(
                            id=hashlib.md5(f"ITU-{raw_data['country']}-{raw_data['year']}".encode()).hexdigest()[:16],
                            industry="telecom",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "ITU"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results
        
        if self.telecom_mode == "ookla":
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
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=is_strict)
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
                
                # Defensive Key Mapping (Case-Resilient)
                def get_field(keys):
                    for k in keys:
                        val = row.get(k)
                        if val is not None: return val
                    return 0

                data = {
                    "provider_name": name,
                    "service_type": row.get("technology_type") or row.get("type", "Standard"),
                    "download_speed": float(get_field(["max_ad_down", "download_speed", "value"])),
                    "upload_speed": float(get_field(["max_ad_up", "upload_speed", "value"])),
                    "location": self.scrub_pii(str(row.get("location") or "State-level"))
                }
                
                # Strict Schema Verification
                verified_data = self.llm_manager._verify_schema(data, TARGET_SCHEMA, strict=is_strict)
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
            if self.telecom_mode == "ookla":
                if record.data.get("avg_download_speed", 0) < 0: return False
            elif self.telecom_mode == "itu":
                if record.data.get("usage_value", 0) < 0: return False
            else:
                # Industrial sanity: speeds should be non-negative
                if record.data["download_speed"] < 0 or record.data["upload_speed"] < 0:
                    logger.warning("anomaly_detected", record_id=record.id, reason="Negative speed")
                    return False
        return True





