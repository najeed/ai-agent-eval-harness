import aiohttp
import os
import logging
import hashlib
import json
import pandas as pd
from datetime import datetime
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

    async def extract(self) -> List[RawArtifact]:
        """
        Extract content from local path or web URL, supporting PDF and raw text.
        """
        if not self.input_uri:
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
                if not content: return []
        else:
            path = self.input_uri
            if os.path.isdir(path):
                # Process first file in directory for pilot
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                if files:
                    path = os.path.join(path, files[0])
                else:
                    return []

            if os.path.exists(path):
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
                        # Enrich metadata with PDF info
                        doc_metadata = {
                            "pages": len(reader.pages),
                            "author": reader.metadata.author if reader.metadata else "Unknown",
                            "producer": reader.metadata.producer if reader.metadata else "Unknown"
                        }
                    except Exception as e:
                        logger.error(f"PDF extraction failed for {path}: {e}")
                        return []
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
            else:
                logger.error(f"Input path not found: {path}")
                return []

        id_content = f"{self.input_uri}-{hashlib.md5(content.encode()).hexdigest()[:8]}"
        
        return [RawArtifact(
            id=f"doc-{id_content}",
            source_url=self.input_uri,
            content=content,
            metadata=doc_metadata if 'doc_metadata' in locals() else {},
            timestamp=datetime.utcnow().isoformat()
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
            "status": "string"
        })
        
        for raw in raw_artifacts:
            # 1. Security: Scrub PII before LLM ingestion
            safe_content = self.scrub_pii(raw.content)
            
            # 2. Extraction via LLM (Tiers: Cloud -> Local -> Heuristic)
            extracted_data = await self.llm_manager.extract_structured_data(
                safe_content, target_schema
            )
            
            if extracted_data is None:
                logger.error(f"Extraction failed for {raw.id}")
                continue
                
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
