import hashlib
import json
import asyncio
import aiohttp
import os
import datetime
from typing import List, Dict, Any
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("EcommerceProvider")

class EcommerceProvider(BaseProvider):
    """
    Gold Standard Ecommerce provider supporting Olist (Brazil) and UCI (UK) schemas.
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.schema_type = config.get("schema_type", "standard") # olist, uci, standard
        self.input_uris = config.get("input_uris", [config.get("input_uri")] if config.get("input_uri") else [])

    async def extract(self) -> List[RawArtifact]:
        limit = self.config.get("limit", 50)
        artifacts = []
        
        async def fetch_uri(uri):
            # Unified Data Acquisition (Local or Web URL)
            df = self.load_raw_data(uri)
            
            if df is not None:
                # Tabular format (Olist/UCI)
                records = df.head(limit).to_dict(orient="records")
                content_hash = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:12]
                return RawArtifact(
                    id=f"ecom-tabular-{content_hash}",
                    source_url=uri,
                    content=records,
                    metadata={"source_type": self.schema_type},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )
            
            # Raw text fallback (Standard review format)
            try:
                is_remote = str(uri).startswith(("http://", "https://"))
                if is_remote:
                    async with aiohttp.ClientSession() as session:
                        async def fetch_logic():
                            async with session.get(uri) as resp:
                                if resp.status == 200:
                                    return (await resp.text()).splitlines()[:limit]
                                return None
                        lines = await self.request_with_retry(fetch_logic)
                elif uri and os.path.exists(str(uri)):
                    with open(uri, "r", encoding="utf-8") as f:
                        lines = [f.readline().strip() for _ in range(limit)]
                else:
                    lines = None
                    
                if lines:
                    content_hash = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]
                    return RawArtifact(
                        id=f"ecom-stream-{content_hash}",
                        source_url=uri,
                        content=lines,
                        metadata={"source_type": "reviews"},
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                    )
            except Exception as e:
                logger.error("extraction_failed", uri=uri, error=str(e))
            
            if self.allow_simulation:
                # High-fidelity simulation handle
                sim_data = [{"review_text": "Excellent product!", "rating": 5.0, "category": "Electronics"}]
                return self.create_simulated_artifact(id=f"ECOM-{self.schema_type}", content=sim_data, source_url=uri)
            return None

        tasks = [fetch_uri(uri) for uri in self.input_uris]
        results = await asyncio.gather(*tasks)
        artifacts = [r for r in results if r]
        
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        # Define schemas based on gold standard datasets
        SCHEMAS = {
            "uci": {
                "invoice_no": "string", "stock_code": "string", "description": "string",
                "quantity": "integer", "unit_price": "number", "customer_id": "string", "country": "string"
            },
            "olist": {
                "order_id": "string", "product_id": "string", "price": "number",
                "freight_value": "number", "customer_id": "string", "order_status": "string",
                "review_score": "integer"
            },
            "standard": {
                "product_name": "string", "category": "string", "rating": "number",
                "sentiment": "number", "review_text": "string"
            }
        }
        
        target_schema = SCHEMAS.get(self.schema_type, SCHEMAS["standard"])
        
        for artifact in raw_artifacts:
            for item in artifact.content:
                row = item if isinstance(item, dict) else {}
                data = {}
                
                if self.schema_type == "uci":
                    data = {
                        "invoice_no": str(row.get("InvoiceNo", "N/A")),
                        "stock_code": str(row.get("StockCode", "N/A")),
                        "description": row.get("Description", "No description"),
                        "quantity": int(row.get("Quantity", 0)),
                        "unit_price": float(row.get("UnitPrice", 0)),
                        "customer_id": str(row.get("CustomerID", "N/A")),
                        "country": row.get("Country", "Unknown")
                    }
                elif self.schema_type == "olist":
                    data = {
                        "order_id": row.get("order_id"),
                        "product_id": row.get("product_id"),
                        "price": float(row.get("price", 0)),
                        "freight_value": float(row.get("freight_value", 0)),
                        "customer_id": row.get("customer_id"),
                        "order_status": row.get("order_status"),
                        "review_score": int(row.get("review_score", 3))
                    }
                else:
                    # Standard review format (maintained for backward compatibility)
                    text = row.get("review_text") or (item if isinstance(item, str) else "No text")
                    sentiment = await self.llm_manager.analyze_sentiment(text)
                    data = {
                        "product_name": row.get("product_name", "Unknown"),
                        "category": row.get("category", "Uncategorized"),
                        "rating": float(row.get("rating", 3)),
                        "sentiment": sentiment,
                        "review_text": self.scrub_pii(text)
                    }
                    
                    # Decision Support: Weight sentiment by CPI (Inflation Pressure)
                    cpi_impact = self.config.get("cpi_impact", 0) # e.g. 0.05 (5% inflation)
                    if cpi_impact > 0:
                        # Inflation usually dampens perceived value
                        data["sentiment"] = round(data["sentiment"] * (1 - cpi_impact), 2)
                        data["note"] = f"Weighted by inflation pressure ({cpi_impact*100}%)"
                
                verified_data = self.llm_manager._verify_schema(data, target_schema, strict=True)
                if verified_data:
                    # Deterministic ID for each record
                    unique_id_source = str(data.get("order_id") or data.get("invoice_no") or data.get("review_text"))
                    record_id = hashlib.md5(unique_id_source.encode()).hexdigest()[:16]
                    raw_str = json.dumps(verified_data, sort_keys=True)
                    data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()

                    results.append(StandardSchema(
                        id=record_id,
                        industry="ecommerce",
                        data=verified_data,
                        provenance={"source": artifact.source_url, "schema": self.schema_type},
                        checksum=data_checksum
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        # Generic industrial sanity: price/rating should be non-negative
        for record in normalized_data:
            val = record.data.get("price") or record.data.get("unit_price") or record.data.get("rating")
            if val is not None and val < 0:
                return False
        return True





