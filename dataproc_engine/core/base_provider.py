from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("BaseProvider")

@dataclass
class RawArtifact:
    id: str
    source_url: str
    content: Any
    metadata: Dict[str, Any]
    timestamp: str

@dataclass
class StandardSchema:
    id: str
    industry: str
    data: Dict[str, Any]
    provenance: Dict[str, Any]
    checksum: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a flat dictionary for pandas/CSV exports."""
        record = {
            "record_id": self.id,
            "industry": self.industry,
            "checksum": self.checksum,
            **self.provenance
        }
        # Flatten the data dict into the root for CSV compatibility
        for k, v in self.data.items():
            record[f"{k}"] = v
        return record

    @classmethod
    def create(cls, industry: str, data: Dict[str, Any], provenance: Dict[str, Any], record_id: str = None, checksum: str = None) -> "StandardSchema":
        """Factory method for consistent record creation."""
        import hashlib
        import json
        
        final_id = record_id or hashlib.md5(json.dumps(data).encode()).hexdigest()[:16]
        final_checksum = checksum or hashlib.sha256(json.dumps(data).encode()).hexdigest()
        
        return cls(
            id=final_id,
            industry=industry,
            data=data,
            provenance=provenance,
            checksum=final_checksum
        )

    @classmethod
    def from_pandas(cls, row: Any, industry: str) -> "StandardSchema":
        """Create a StandardSchema instance from a pandas Series/Row."""
        data = row.to_dict()
        record_id = str(data.pop("record_id", data.pop("id", "generated-id")))
        checksum = str(data.pop("checksum", ""))
        
        # Provenance keys often stored in CSVs
        provenance = {}
        for k in ["source", "retrieved_at", "source_url", "timestamp"]:
            if k in data:
                provenance[k] = data.pop(k)
        
        return cls(
            id=record_id,
            industry=industry,
            data=data,
            provenance=provenance,
            checksum=checksum
        )

class BaseProvider(ABC):
    """
    Abstract base class for all FHS industrial data providers.
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        import asyncio
        self.config = config
        self.llm_manager = llm_manager
        self.rate_limit = config.get("rate_limit", 1.0) # Requests per second
        
        # Performance: Bounded Concurrency
        self.concurrency_limit = config.get("concurrency_limit", 5)
        self.semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        # Resiliency State
        self._circuit_open = False
        self._failure_count = 0
        self._max_failures = config.get("max_failures", 3)
        
        # Hardening: Standardized Simulation Control
        self.allow_simulation = config.get("allow_simulation", True)

    def create_simulated_artifact(self, id: str, content: Any, source_url: str = "simulation://local", metadata: Dict = None) -> RawArtifact:
        """
        Standardized factory for high-fidelity simulations. 
        Ensures strict tagging for Zero-Bundling compliance.
        """
        import datetime
        final_metadata = metadata or {}
        final_metadata["simulation"] = True
        final_id = id if id.startswith("sim-") else f"sim-{id}"
        return RawArtifact(
            id=final_id,
            source_url=source_url,
            content=content,
            metadata=final_metadata,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        
    def scrub_pii(self, text: str) -> str:
        """
        Regex-based PII scrubbing for sensitive data (Emails, Phones).
        """
        import re
        if not isinstance(text, str):
            text = str(text)
            
        # Email pattern
        text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
        # Phone pattern (Basic US/International)
        text = re.sub(r"(\+?\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", "[PHONE]", text)
        
        return text

    async def request_with_retry(self, func, *args, **kwargs):
        """
        Execute an async request with exponential backoff and circuit breaker protection.
        """
        import asyncio
        import random
        
        if self._circuit_open:
            logger.error("circuit_open_abort", provider=self.__class__.__name__)
            return None
            
        async with self.semaphore:
            max_retries = self.config.get("max_retries", 3)
            for attempt in range(max_retries):
                try:
                    result = await func(*args, **kwargs)
                    self._failure_count = 0 # Reset on success
                    return result
                except Exception as e:
                    self._failure_count += 1
                    logger.warning("request_attempt_failed", 
                                   provider=self.__class__.__name__, 
                                   attempt=attempt+1, 
                                   error=str(e))
                    
                    if self._failure_count >= self._max_failures:
                        self._circuit_open = True
                        logger.critical("circuit_breaker_tripped", 
                                        provider=self.__class__.__name__, 
                                        failures=self._failure_count)
                        break
                    
                    # Exponential backoff: 1s, 2s, 4s... with jitter
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(wait_time)
        
        return None

    def load_raw_data(self, path: str) -> Any:
        """
        Universal data loader supporting Web URLs and Local Paths.
        Abstracted to BaseProvider for consistent acquisition across industries.
        Supports CSV and Excel formats.
        """
        import pandas as pd
        import os
        
        if not path:
            return None
            
        is_url = str(path).startswith(("http://", "https://"))
        if is_url or os.path.exists(path):
            try:
                logger.info("loading_external_data", path=path, provider=self.__class__.__name__)
                # Pandas handles both local paths and URLs natively
                if str(path).endswith((".xls", ".xlsx")):
                    df = pd.read_excel(path)
                else:
                    df = pd.read_csv(path)
                return df
            except Exception as e:
                logger.error("data_load_failed", path=path, error=str(e))
                return None
        return None

    @abstractmethod
    async def extract(self) -> List[RawArtifact]:
        """
        Fetch raw artifacts from the industry source (e.g., SEC EDGAR, FRED).
        """
        pass

    @abstractmethod
    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        """
        Transform raw artifacts into a normalized, high-signal schema.
        """
        pass

    @abstractmethod
    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        """
        Validate the integrity and factual consistency of the transformed data.
        """
        pass

    def heuristic_transform(self, raw_content: str, target_schema: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Tier 3: Heuristic Fallback. 
        Regex-based pattern extraction when LLM verification fails.
        Should be overridden by providers with domain-specific patterns.
        """
        return None





