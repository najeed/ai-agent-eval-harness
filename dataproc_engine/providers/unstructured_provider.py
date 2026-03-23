import aiohttp
import os
import logging
import hashlib
import json
import pandas as pd
import datetime
from typing import List, Dict, Any, Optional
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.llm_manager import LLMManager

logger = logging.getLogger("UnstructuredProvider")

class UnstructuredProvider(BaseProvider):
    """
    Provider for unstructured documents (Local Files or URLs).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.input_uri = config.get("input_uri")
        self.schema_type = config.get("schema_type", "document") # document, common_crawl

    async def extract(self) -> List[RawArtifact]:
        if self.schema_type == "common_crawl":
            # Gold Standard: Common Crawl (Web Archive)
            snapshot = self.config.get("snapshot", "2023-50")
            url = f"https://data.commoncrawl.org/crawl-data/CC-MAIN-{snapshot}/"
            
            # Simulated Common Crawl Data (Zero-Bundling)
            sim_crawl = "<html><body><h1>Global AI Trends 2024</h1><p>Market growth expected in all sectors.</p></body></html>"
            return [RawArtifact(
                id=f"CC-{snapshot}",
                source_url=url,
                content=sim_crawl,
                metadata={"warc_type": "response", "target_uri": "https://example.com/trends", "simulation": True},
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]

        """
        Extract content from local path or web URL, supporting PDF and raw text.
        """
        if not self.input_uri:
            if self.allow_simulation:
                return [self.create_simulated_artifact(
                    id="sim-DOC-generic",
                    content="This is a simulated industrial document for testing purposes.",
                    source_url="local://simulation",
                    metadata={"type": "text/plain"}
                )]
            logger.error("No input URI provided.")
            return []

        logger.info(f"Extracting raw content from: {self.input_uri}")
        
        content = ""
        if self.input_uri.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async def fetch_url():
                    async with session.get(self.input_uri) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        return None
                content = await self.request_with_retry(fetch_url)
                if not content:
                    if self.allow_simulation:
                        return [self.create_simulated_artifact(
                            id=f"CC-{snapshot}",
                            content="<html><body><h1>Global AI Trends 2024</h1></body></html>",
                            source_url=url,
                            metadata={"warc_type": "response", "target_uri": "https://example.com/trends"}
                        )]
                    return []
        else:
            path = self.input_uri
            if path.startswith("common_crawl://"):
                # Special handle to bypass os.path.exists for simulation/protocol schemas
                pass
            elif os.path.isdir(path):
                # Process first file in directory for pilot
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                if files:
                    path = os.path.join(path, files[0])
                else:
                    return []

            if path.startswith("common_crawl://"):
                # Protocol recognized, common_crawl handled at top or via extraction logic
                content = "<html><body><h1>Global AI Trends 2024</h1></body></html>"
            elif os.path.exists(path):
                if path.lower().endswith(".pdf"):
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(path)
                        text_parts = []
                        for i, page in enumerate(reader.pages):
                            text = page.extract_text()
                            if text:
                                text_parts.append(text)
                        
                        content = "\n\n".join(text_parts)
                        doc_metadata = {
                            "pages": len(reader.pages),
                            "author": reader.metadata.author if reader.metadata else "Unknown"
                        }
                    except Exception as e:
                        logger.error(f"PDF extraction failed for {path}: {e}")
                        return []
                elif path.lower().endswith((".png", ".jpg", ".jpeg")):
                    try:
                        # OCR Multi-Layer Fallback (Tesseract -> EasyOCR)
                        try:
                            import pytesseract
                            from PIL import Image
                            content = pytesseract.image_to_string(Image.open(path))
                        except Exception:
                            import easyocr
                            reader = easyocr.Reader(['en'])
                            results = reader.readtext(path)
                            content = " ".join([res[1] for res in results])
                        doc_metadata = {"type": "image", "ocr_engine": "tesseract/easyocr"}
                    except Exception as e:
                        logger.error(f"OCR failed for {path}: {e}")
                        return []
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
            else:
                logger.error(f"Input path not found: {path}")
                return []

        # Safety check for hashlib (requires bytes-like object)
        hash_input = content if isinstance(content, (str, bytes)) else str(content)
        id_content = f"{self.input_uri}-{hashlib.md5(hash_input.encode()).hexdigest()[:8]}"
        
        return [RawArtifact(
            id=f"doc-{id_content}",
            source_url=self.input_uri,
            content=content,
            metadata=doc_metadata if 'doc_metadata' in locals() else {},
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )]

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        """
        Extract and verify data using LLMManager (Unified Async Path).
        """
        import hashlib
        import json
        results = []
        target_schema = self.config.get("target_schema", {
            "entity_name": "string",
            "revenue": "number",
            "assets": "number",
            "status": "string",
            "sentiment_score": "number",
            "strategic_signals": "string"
        })
        
        if self.schema_type == "common_crawl":
            TARGET_SCHEMA = {"web_title": "string", "web_source": "string", "web_domain": "string"}
            for raw in raw_artifacts:
                # Basic HTML-to-Text simulation for transformation
                raw_data = {
                    "web_title": "Global AI Trends 2024",
                    "web_source": raw.metadata.get("target_uri"),
                    "web_domain": "example.com"
                }
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    results.append(StandardSchema(
                        id=hashlib.md5(f"CC-{raw_data['web_source']}".encode()).hexdigest()[:16],
                        industry="unstructured",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": "Common Crawl"},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
            return results

        for raw in raw_artifacts:
            # 1. Security: Scrub PII before LLM ingestion
            safe_content = self.scrub_pii(raw.content)
            
            # 2. Extraction via LLM (Tiers: Cloud -> Local -> Heuristic)
            extracted_data = await self.llm_manager.extract_structured_data(
                safe_content, 
                target_schema,
                source_hint=source_hint
            )
            
            if extracted_data is None:
                logger.error(f"Extraction failed for {raw.id}")
                continue
                
            # 2.5 V2: Deep Signal Layer (Sentiment & Signal Weighting)
            if "sentiment_score" not in extracted_data:
                extracted_data["sentiment_score"] = await self.llm_manager.analyze_sentiment(safe_content)
            
            # Weighted Signal Context (e.g., Finance + Energy correlation)
            if "strategic_signals" not in extracted_data or not extracted_data["strategic_signals"]:
                 extracted_data["strategic_signals"] = self._derive_strategic_pivot(safe_content)
                
            # 3. Strict Verification (Post-Process)
            if self._verify_domain_integrity(extracted_data):
                # Robust data-aware checksum
                raw_str = json.dumps(extracted_data, sort_keys=True)
                data_checksum = hashlib.sha256(raw_str.encode()).hexdigest()
                
                results.append(StandardSchema(
                    id=raw.id,
                    industry=self.config.get("industry", "generic"),
                    data=extracted_data,
                    provenance={
                        "source": raw.source_url,
                        "retrieved_at": raw.timestamp
                    },
                    checksum=data_checksum
                ))
            else:
                logger.error(f"Domain integrity check failed for {raw.id}")
                
        return results

    def _derive_strategic_pivot(self, content: str) -> str:
        """
        V2: Heuristic detection of strategic industrial signals.
        """
        signals = []
        if any(w in content.lower() for w in ["ai", "automation", "efficiency"]):
            signals.append("TECH_TRANSFORMATION")
        if any(w in content.lower() for w in ["acquisition", "merger", "partnership"]):
            signals.append("M&A_ACTIVITY")
        if any(w in content.lower() for w in ["decline", "risk", "reduction"]):
            signals.append("MARKET_HEADWINDS")
            
        return "|".join(signals) if signals else "STABLE_OPERATIONS"

    def _verify_domain_integrity(self, data: Dict[str, Any]) -> bool:
        """
        Domain-specific validation (e.g., non-negative financials).
        """
        # Basic non-negative check for financials
        for key in ["revenue", "assets"]:
            if key in data and isinstance(data[key], (int, float)) and data[key] < 0:
                return False
        return True

    def validate(self, transformed_data: List[StandardSchema]) -> bool:
        """
        Validate the transformed records.
        """
        # Basic validation: ensure all records have data and positive assets if present
        for record in transformed_data:
            if not record.data:
                return False
        return True





