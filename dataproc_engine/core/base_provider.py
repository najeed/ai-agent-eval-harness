from abc import ABC, abstractmethod
from typing import Any, Dict, List
from dataclasses import dataclass, asdict

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

class BaseProvider(ABC):
    """
    Abstract base class for all FHS industrial data providers.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.rate_limit = config.get("rate_limit", 1.0) # Requests per second

    @abstractmethod
    async def extract(self) -> List[RawArtifact]:
        """
        Fetch raw artifacts from the industry source (e.g., SEC EDGAR, FRED).
        """
        pass

    @abstractmethod
    def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
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
