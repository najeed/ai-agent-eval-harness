# `dataproc-engine` Architecture Diagram

The following diagram illustrates the data flow and component interactions within the hardened industrial inference engine.

```mermaid
graph TD
    subgraph CLI[User Interface]
        Main[cli/main.py] -->|--industry| Engine[core/engine.py]
        Main -->|--target-dir| Correlator[core/correlator.py]
    end

    subgraph Core[Orchestator Layer]
        Engine -->|Register| Providers[Industrial Providers]
        Engine -->|Secrets| Config[core/config.py]
        Engine -->|Async Execute| Pipeline[ETL Pipeline]
    end

    subgraph ETL[Unified Pipeline]
        direction TB
        Resiliency[Circuit Breaker / Retry] --> Extract[Async Extraction]
        Extract --> Security[PII Scrubber]
        Security --> Transform[Async Transformation]
        Transform --> Validate[Integrity Validation]
        Validate --> Correlate[Data Correlation]
    end

    subgraph Intelligence[Inference Layer]
        Transform -->|Tiered Fallback| LLM[core/llm_manager.py]
        LLM -->|T1| Cloud[Cloud APIs: Gemini/GPT/Claude]
        LLM -->|T2| Ollama[Local Ollama]
        LLM -->|T3| Heuristic[Regex-based Heuristics]
        
        Correlate -->|Fuzzy Match| CorrelationLayer[DataCorrelator]
        CorrelationLayer -->|RapidFuzz| Identity[Identity Resolution]
        CorrelationLayer -->|Macro| GlobalSignals[Signal Propagation]
    end

    subgraph Storage[Target Datasets]
        Correlate -->|Save| Output[( industries/**/datasets/*.csv )]
        Output -->|Re-Discovery| CorrelationLayer
    end
```

### Key Workflow:
1.  **Unified Async Entry**: The CLI initializes a single async block that handles both API-based and local file-based sources.
2.  **Tiered Extraction**: The `LLMManager` attempts Cloud extraction, falling back to local models or regex heuristics for zero-cost recovery.
3.  **Cross-Vertical Correlation**: The `DataCorrelator` scans the target directory to link new records with existing industry data (e.g., linking Finance to Telecom).
