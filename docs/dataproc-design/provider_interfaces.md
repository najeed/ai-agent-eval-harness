# Provider Interface Specification

## Base Provider Class
All industrial data providers must inherit from the `BaseProvider` abstract class to ensure compatibility with the `DatasetEngine`.

```python
from abc import ABC, abstractmethod

class BaseProvider(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.allow_simulation = config.get("allow_simulation", True)
        self.rate_limit = config.get("rate_limit", 1) # Default 1 req/s
        
    @abstractmethod
    async def extract(self) -> list[RawArtifact]:
        """
        Fetch raw documents from external source. 
        MUST trigger simulate() if source is unreachable and allow_simulation is True.
        """
        pass
        
    async def simulate(self, artifacts: list[RawArtifact]) -> list[RawArtifact]:
        """
        Global fallback: Creates high-fidelity artifacts using the internal factory.
        Injected automatically when the primary extraction returns an empty set.
        """
        if not artifacts and self.allow_simulation:
             # Implementation-specific simulation logic
             pass
        return artifacts

    def create_simulated_artifact(self, id: str, content: Any, source_url: str, metadata: dict) -> RawArtifact:
        """Standardized factory for high-fidelity mock artifact creation."""
        pass
        
    @abstractmethod
    async def transform(self, raw_data: list[RawArtifact]) -> list[StandardSchema]:
        """Convert raw artifacts into the normalized industry schema (Async)."""
        pass
        
    @abstractmethod
    def validate(self, normalized_data: list[StandardSchema]) -> bool:
        """Perform industry-specific integrity and business logic checks."""
        pass
```

## Industrial Implementation Registry
The framework currently supports **16 hardened industrial sectors**, each implementing the lifecycle above:

### 1. Anchor Foundations
*   **Finance, Healthcare, Energy, Transportation**: Deep API integrations (SEC, CMS, EIA, BTS).
*   **Matching**: Uses `DataCorrelator` for fuzzy identity resolution (e.g., linking CIKs to industry signatures).
*   **Infrastructure**: Fully asynchronous transformation supporting tiered LLM failover.

### 2. UnstructuredProvider
*   **Universal Input**: Handles Local Paths, URLs, and PDF files.
*   **Intelligence**: Integrates `LLMManager` for heuristic or probabilistic metric extraction.

## Extensibility for New Industries
Adding a new industry requires zero changes to the `DatasetEngine`. The developer only needs to:
1.  Implement a new class inheriting from `BaseProvider`.
2.  Specify the industry-specific transformation logic (async).
3.  Register the new class in the CLI orchestrator.
