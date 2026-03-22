# 📄 Unstructured Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The unstructured sector handles arbitrary PDF, DocX, and Web sources with a tiered "LLM-Gated" approach.

### 1. Multi-Document Ingestion
*   **Role**: Ingest raw project reports, manuals, and regulatory PDFs.
*   **Logic**: 
    *   **PDF**: Integrated `pypdf` for text layer extraction.
    *   **DocX**: XML-based paragraph parsing.
    *   **Web**: Asynchronous `aiohttp` fetching with HTML-to-Markdown normalization.

### 2. Tiered Extraction Logic
*   **Tier 1 (Cloud)**: Gemini/OpenAI for complex reasoning.
*   **Tier 2 (Ollama)**: Local models (`deepseek-v3`) for privacy-safe text logic.
*   **Tier 3 (Heuristics)**: Hardened Regex for structured key-value extraction.

## 🛠️ ETL & Transformation
1.  **Schema Enforcement**: Force unstructured data into deterministic `StandardSchema` fields via LLM prompts.
2.  **PII Scrubbing**: Mission-critical protection for proprietary documents.
3.  **Context Truncation**: Intuitively handle tokens limits by prioritizing high-signal paragraphs.

## 🛡️ Robustness & Compliance
*   **Provenance**: Digital fingerprinting of the source document (SHA-256).
*   **Safety**: Prompt-injection guardrails and schema verification active.
*   **Fallback**: Automated Tier 3 heuristic fallback prevents extraction failure.
