# Configuration & Secret Management Strategy

## Overview
To ensure security and flexibility, `dataproc-engine` follows a hierarchical configuration strategy that prioritizes environment variables for sensitive secrets (API keys) while using standard configuration files for non-sensitive parameters.

## 1. Secret Handling (API Keys)
Secrets must **never** be hardcoded or stored in version-controlled config files.

### Recommended Pattern: Environment Variables
The engine will look for industry-specific environment variables:
*   `SEC_USER_AGENT`: Required for SEC EDGAR access.
*   `FRED_API_KEY`: Required for FRED macro data.

### Local Development: `.env` Support
For local runs, the engine will automatically load keys from a `.env` file in the project root:
```bash
# .env file
SEC_USER_AGENT="YourName (your.email@example.com)"
FRED_API_KEY="your_alphanumeric_key_here"
```

## 2. Hierarchical Configuration
The `DatasetEngine` loads a base configuration (e.g., `config.yaml`) and merges it with industry-specific overrides.

### Precedence Order (Lowest to Highest):
1.  **Defaults**: Hardcoded in the `BaseProvider` or `DatasetEngine`.
2.  **Config File**: `config.yaml` (e.g., `rate_limit: 10`).
3.  **CLI Arguments**: (e.g., `--limit 100`).
4.  **Environment Variables**: (e.g., `DATAPROC_LIMIT=50`).

## 3. Implementation in Code
The `DatasetEngine` will utilize a `ConfigLoader` utility to inject secrets into providers during instantiation.

```python
# Generic injection pattern
class FinanceProvider(BaseProvider):
    def __init__(self, config: dict):
        super().__init__(config)
        # Secrets are injected from ENV or .env by the Orchestrator
        self.api_key = config.get("fred_api_key")
        self.user_agent = config.get("sec_user_agent")
```

## 4. Security Auditing
*   **Secret Masking**: Logs must never print the values of keys.
*   **Validation**: The `validate()` step in the provider should check for the presence of required keys before starting extraction.
