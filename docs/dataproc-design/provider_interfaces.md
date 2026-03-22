# Provider Interface Specification

## Base Provider Class
All industrial data providers must inherit from the `BaseProvider` abstract class to ensure compatibility with the `DatasetEngine`.

```python
from abc import ABC, abstractmethod

class BaseProvider(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.rate_limit = config.get("rate_limit", 1) # Default 1 req/s
        
    @abstractmethod
    async def extract(self) -> list[RawArtifact]:
        """Fetch raw documents from external source."""
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

## Industrial Implementation Examples

### 1. FinanceProvider
*   **Sources**: SEC EDGAR, EIA API, Market Trends.
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
