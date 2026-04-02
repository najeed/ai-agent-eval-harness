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
        self.ecommerce_mode = config.get("ecommerce_mode") or config.get("schema_type") or "standard"
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
                    metadata={"source_type": self.ecommerce_mode},
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
                return self.create_simulated_artifact(id=f"ECOM-{self.ecommerce_mode}", content=sim_data, source_url=uri)
            return None

        tasks = [fetch_uri(uri) for uri in self.input_uris]
        results = await asyncio.gather(*tasks)
        artifacts = [r for r in results if r]
        
        if not artifacts and self.allow_simulation:
            # High-fidelity Simulation Contract (V2.0 Stabilization)
            sim_content = []
            if self.ecommerce_mode == "uci":
                sim_content = [{
                    "InvoiceNo": "536365", "StockCode": "85123A", "Description": "WHITE HANGING HEART T-LIGHT HOLDER",
                    "Quantity": 6, "UnitPrice": 2.55, "CustomerID": "17850", "Country": "United Kingdom"
                }]
            elif self.ecommerce_mode == "olist":
                sim_content = [{
                    "order_id": "e481f51cbdc54678b7cc49136f2d6af7", "product_id": "87285b1488457224702e07" , "price": 29.99,
                    "freight_value": 8.72, "customer_id": "9ef432eb6251297304e76186b776273d", "order_status": "delivered",
                    "review_score": 4
                }]
            else:
                sim_content = [{"review_text": "Excellent industrial grade performance.", "rating": 5.0, "category": "Office Supplies"}]
            
            logger.info("using_high_fidelity_simulation", mode=self.ecommerce_mode)
            artifacts.append(self.create_simulated_artifact(
                id=f"ECOM-{self.ecommerce_mode}-SIM",
                content=sim_content,
                source_url="https://simulated-ecommerce.example.com/",
                metadata={"mode": self.ecommerce_mode, "simulation_type": "high-fidelity"}
            ))
            
        return artifacts

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        is_strict = self.llm_manager.strategy not in ["heuristic", "mock"]
        
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
        
        target_schema = SCHEMAS.get(self.ecommerce_mode, SCHEMAS["standard"])
        
        for artifact in raw_artifacts:
            for item in artifact.content:
                row = item if isinstance(item, dict) else {}
                data = {}
                
                # Defensive Key Mapping (Case-Resilient)
                def get_field(keys):
                    for k in keys:
                        # Try exact match, then case-insensitive
                        val = row.get(k)
                        if val is not None: return val
                        for r_k in row.keys():
                            if str(r_k).lower() == str(k).lower():
                                return row[r_k]
                    return None

                if self.ecommerce_mode == "uci":
                    data = {
                        "invoice_no": str(get_field(["invoice_no", "InvoiceNo"]) or "N/A"),
                        "stock_code": str(get_field(["stock_code", "StockCode"]) or "N/A"),
                        "description": get_field(["description", "Description"]) or "No description",
                        "quantity": int(get_field(["quantity", "Quantity"]) or 0),
                        "unit_price": float(get_field(["unit_price", "UnitPrice"]) or 0),
                        "customer_id": str(get_field(["customer_id", "CustomerID"]) or "N/A"),
                        "country": get_field(["country", "Country"]) or "Unknown"
                    }
                elif self.ecommerce_mode == "olist":
                    data = {
                        "order_id": get_field(["order_id", "OrderId"]),
                        "product_id": get_field(["product_id", "ProductId"]),
                        "price": float(get_field(["price", "Price"]) or 0),
                        "freight_value": float(get_field(["freight_value", "FreightValue"]) or 0),
                        "customer_id": get_field(["customer_id", "CustomerId"]),
                        "order_status": get_field(["order_status", "OrderStatus"]),
                        "review_score": int(get_field(["review_score", "ReviewScore"]) or 3)
                    }
                else:
                    # Standard review format
                    text = get_field(["review_text", "text"]) or (item if isinstance(item, str) else "No text")
                    sentiment = await self.llm_manager.analyze_sentiment(text)
                    # Macro Level 2: Inflation Impact (CPI Weighting)
                    cpi_impact = self.config.get("cpi_impact", 0)
                    if cpi_impact > 0:
                        sentiment = round(max(0.0, float(sentiment) - float(cpi_impact)), 2)
                        
                    data = {
                        "product_name": get_field(["product_name", "name"]) or "Unknown",
                        "category": get_field(["category", "type"]) or "Uncategorized",
                        "rating": float(get_field(["rating", "score"]) or 3),
                        "sentiment": sentiment,
                        "review_text": self.scrub_pii(text),
                        "note": "inflation pressure" if cpi_impact > 0 else "standard"
                    }
                
                verified_data = self.llm_manager._verify_schema(data, target_schema, strict=is_strict)
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
                        provenance={"source": artifact.source_url, "schema": self.ecommerce_mode},
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





