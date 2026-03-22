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
    def transform(self, raw_data: list[RawArtifact]) -> list[StandardSchema]:
        """Convert raw artifacts into the normalized industry schema."""
        pass
        
    @abstractmethod
    def validate(self, normalized_data: list[StandardSchema]) -> bool:
        """Perform industry-specific integrity and business logic checks."""
        pass
```

## Modular Components

### 1. FinanceProvider (Pilot)
*   **Sources**: `SEC_EDGAR`, `FRED_API`.
*   **Extraction**: REST API calls (SEC) and `fredapi` library.
*   **Transformation**: XBRL to JSON conversion; time-series alignment of macro vs corporate data.

### 2. Provider Registration
Providers are registered in a centralized `registry.json`:

```json
{
  "industries": {
    "finance": {
      "provider": "dataproc_engine.providers.finance.FinanceProvider",
      "config": {
        "sec_user_agent": "...",
        "fred_api_key": "..."
      }
    }
  }
}
```

## Extensibility for New Industries
Adding a new industry requires zero changes to the `DatasetEngine`. The developer only needs to:
1.  Implement a new class inheriting from `BaseProvider`.
2.  Specify the industry-specific transformation logic.
3.  Register the new class in the `Registry`.
