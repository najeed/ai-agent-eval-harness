import hashlib
import json
import asyncio
import aiohttp
import os
import pandas as pd
import datetime
from typing import List, Dict, Any, Optional
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("UnstructuredProvider")

class UnstructuredProvider(BaseProvider):
    """
    Consumer for Unstructured Data (PDFs, Images, Web URLs, CommonCrawl).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.input_uri = config.get("input_uri", "")

    async def extract(self) -> List[RawArtifact]:
        # Priority 1: Common Crawl
        if self.input_uri.startswith("common_crawl://") or self.config.get("unstructured_mode") == "common_crawl":
            snapshot = self.config.get("snapshot", "2024-10")
            url = f"https://index.commoncrawl.org/CC-MAIN-{snapshot}-index"
            
            async with aiohttp.ClientSession() as session:
                async def fetch_cc():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        return None
                
                try:
                    content = await self.request_with_retry(fetch_cc)
                    if content:
                        return [RawArtifact(
                            id=f"CC-{snapshot}",
                            content=content[:5000],
                            source_url=url,
                            metadata={"warc_type": "index", "snapshot": snapshot},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception:
                    pass
            
            if self.allow_simulation:
                return [RawArtifact(
                    id=f"CC-{snapshot}-SIM",
                    content="<html><body><h1>Global AI Trends 2024</h1></body></html>",
                    source_url=url,
                    metadata={"warc_type": "response", "target_uri": "https://example.com/trends"},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]
            return []

        # Priority 2: Web URLs
        if self.input_uri.startswith(("http://", "https://")):
            url = self.input_uri
            async with aiohttp.ClientSession() as session:
                async def fetch_url():
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        return None
                try:
                    content = await self.request_with_retry(fetch_url)
                    if content:
                        return [RawArtifact(
                            id=f"UNSTR-{hashlib.md5(url.encode()).hexdigest()[:8]}",
                            source_url=url,
                            content=content,
                            metadata={"source": "web_url"},
                            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )]
                except Exception:
                    pass
            
            if self.allow_simulation:
                return [RawArtifact(
                    id="UNSTR-WEB-SIM",
                    content="<html><body><h1>Web Content Simulation</h1></body></html>",
                    source_url=url,
                    metadata={"source": "web_url", "simulation": True},
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
                )]
            return []

        # Priority 3: Local Files
        path = self.input_uri
        content = None
        doc_metadata = {}

        if path and os.path.isdir(path):
            files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            if files:
                path = os.path.join(path, files[0])

        if path and os.path.exists(path):
            if path.lower().endswith(".pdf"):
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(path)
                    text_parts = [p.extract_text() for p in reader.pages if p.extract_text()]
                    content = "\n\n".join(text_parts)
                    doc_metadata = {"pages": len(reader.pages)}
                except Exception:
                    pass
            elif path.lower().endswith((".png", ".jpg", ".jpeg")):
                try:
                    import pytesseract
                    from PIL import Image
                    content = pytesseract.image_to_string(Image.open(path))
                    doc_metadata = {"type": "image", "engine": "tesseract"}
                except Exception:
                    try:
                        import easyocr
                        reader = easyocr.Reader(['en'])
                        results = reader.readtext(path)
                        content = " ".join([res[1] for res in results])
                        doc_metadata = {"type": "image", "engine": "easyocr"}
                    except Exception:
                        pass
            else:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    pass
        
        if content:
            filename = os.path.basename(path)
            return [RawArtifact(
                id=f"UNSTR-{filename}",
                source_url=path,
                content=content,
                metadata=doc_metadata,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]

        # Fallout Branch: Simulation
        if self.allow_simulation:
            return [RawArtifact(
                id="UNSTR-SIM-FALLBACK",
                source_url=self.input_uri or "simulation://unstructured",
                content="Deepened unstructured simulation content for industrial validation.",
                metadata={"simulation": True, "reason": "No local or remote source found"},
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )]
            
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        TARGET_SCHEMA = {"title": "string", "summary": "string", "web_source": "string"}
        industry = self.config.get("industry", "unstructured")
        
        for raw in raw_artifacts:
            # 1. Verification with LLM Manager (Check-API-First)
            raw_data = await self.llm_manager.extract_structured_data(
                raw.content, 
                TARGET_SCHEMA,
                source_hint="Industry: unstructured"
            )
            
            if not raw_data:
                # Heuristic Fallback for local/simulation paths
                raw_data = {
                    "title": "Document Analysis",
                    "summary": str(raw.content)[:100],
                    "web_source": raw.source_url
                }
            
            verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=False)
            if verified:
                record_id = hashlib.md5(f"UNSTR-{raw.id}".encode()).hexdigest()[:16]
                provider_label = "Common Crawl" if "CC-" in raw.id else (raw.metadata.get("engine") or "Unstructured-PDF-OCR")
                results.append(StandardSchema(
                    id=record_id,
                    industry=industry,
                    data=verified,
                    provenance={"source": raw.source_url, "provider": provider_label},
                    checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        return len(normalized_data) > 0
