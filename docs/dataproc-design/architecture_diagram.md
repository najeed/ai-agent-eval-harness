# `dataproc-engine` Architecture Diagram

The following diagram illustrates the data flow and component interactions within the hardened 16-sector industrial fleet.

```mermaid
graph TD
    subgraph CLI[User Interface]
        Main[cli/main.py] -->|--industry| Engine[core/engine.py]
        Main -->|--target-dir| Correlator[core/correlator.py]
    end

    subgraph Core[Execution Layer]
        Engine -->|Register| Providers[16x Industrial Providers]
        Engine -->|Secrets| Config[core/config.py]
        Engine -->|Async Execute| Pipeline[ETL Pipeline]
    end

    subgraph ETL[Unified Pipeline]
        direction TB
        Resiliency[Circuit Breaker / Retry] --> Extract[Async Extraction]
        Extract --> Security[PII Scrubber / Zero-Bundling]
        Security --> Transform[Async Logic / Tiered Fallback]
        Transform --> Validate[Schema Integrity / SHA-256]
        Validate --> Correlate[Cross-Sector Correlation]
    end

    subgraph Intelligence[Inference & Fallback]
        Transform -->|LLM Gating| LLM[core/llm_manager.py]
        LLM -->|T1| Cloud[Gemini/GPT/Claude]
        LLM -->|T2| Local[Ollama/Llama-CPP]
        LLM -->|T3| Heuristic[Regex Heuristics]
        
        Correlate -->|Fuzzy Match| CorrelationLayer[DataCorrelator]
        CorrelationLayer -->|RapidFuzz| Identity[Identity Resolution]
    end

    subgraph Storage[16-Sector Fleet]
        Correlate -->|Save| Output[( industries/**/datasets/*.{jsonl,csv} )]
        Output -->|Metadata| Audit[Data Veracity Logs]
    end
```

### 🎯 Industrial Parity Implementation
The engine achieves "Parity" by comparing extracted records against "Gold Standard" benchmarks (e.g., SEC EDGAR, World Bank). 

**Parity Scenarios**:
1.  **Anchor Parity**: Direct field-for-field mapping for Finance, Healthcare, Energy (Anchor Sectors).
2.  **Fidelity Simulation**: High-fidelity synthetic records used when commercial/restricted licenses prohibit redistribution (Clinical Database V2, Industrial Statistics Agency).
3.  **Cross-Sector Linking**: Verifying that IDs (e.g., Ticker symbols) resolve consistently across different industrial providers.
