# data-to-agentdata: Automated Document Extraction & Formatting

## 1. Implementation Overview
The `data-to-agentdata` utility is **fully implemented** as a core component of the `dataproc-engine`. It facilitates the transition from raw, unstructured documents (PDF, Text, Web) to high-signal metrics for the Agent Evaluation System (AES).

### Technical Capabilities:
*   **Parsing**: Native PDF extraction via `pypdf` and raw text/web retrieval via `aiohttp`.
*   **Tiered LLM Extraction**: 
    1. **Cloud**: High-precision extraction (Gemini, Claude, GPT, Grok).
    2. **Local**: Privacy-first extraction (Ollama: DeepSeek, Qwen).
    3. **Heuristics**: Zero-cost regex fallback for structured logs and KV pairs.
*   **Unified Orchestration**: Uses the same `DatasetEngine` and `DataCorrelator` layers as the deterministic API providers.

## 2. Architecture: UnstructuredProvider
The `UnstructuredProvider` implements the `BaseProvider` interface with a unified asynchronous transformation pipeline:
1.  **Extracts**: Recovers text from documents or URIs.
2.  **Transforms**: Utilizes the `LLMManager` tiers to map text to the AES-compliant schema.
3.  **Correlates**: Automatically links extracted entities with existing industrial datasets (e.g., matching a document's company name with an SEC CIK).

## 3. Workflow Example
1.  **Input**: Annual Report PDF (internal) or raw text dump.
2.  **Command**: `python dataproc_engine/cli/main.py extract --source file --input-uri ./reports/apple_q1.pdf --industry finance`
3.  **Output**: A correlated Finance record enriched with infrastructure signals discovered in `/industries/telecom/datasets/`.

## 4. Operational Status
- [x] **v1**: Deterministic API sources (SEC/FRED/EIA).
- [x] **v2**: Local file ingestion and regex heuristics.
- [x] **v3**: Intelligent LLM-powered extraction with fuzzy cross-vertical correlation.
