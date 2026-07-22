# Adapter Extensions Registry (`adapters.d/`)

This directory supports **Cumulative Infrastructure Governance**. Files placed here are automatically merged into the authoritative adapters policy, allowing for environment-specific overrides without modifying the master `policy.json`.

## 📂 Configuration Mapping

The `adapters.d/` folder follows the tripartite taxonomy:
- **Protocols**: Infrastructure transport (HTTP, Subprocess).
- **Providers**: Model-specific handlers (OpenAI, Gemini).
- **Frameworks**: High-level orchestrators (AG2, LangGraph).

## 🔀 Override Precedence

1.  **Environment Variables**: `AES_ADAPTER_POLICY_OVERRIDE` (Highest)
2.  **Cumulative Extensions**: Files in `adapters.d/` (Sorted alphabetically)
3.  **Master Policy**: `adapters/policy.json` (Baseline)

## 🛠️ Usage Example

To enable a local development adapter without changing the production baseline, create `01_dev_override.json`:
```json
{
  "adapters": {
    "active_protocols": ["http", "local"],
    "settings": {
      "frameworks": {
        "ag2": {
          "use_docker": false
        }
      }
    }
  }
}
```
