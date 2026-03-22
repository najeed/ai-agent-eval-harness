# data-to-agentdata: Automated Document Extraction & Formatting

## 1. Feasibility Analysis
A `data-to-agentdata` utility is **highly feasible** by leveraging the existing `dataproc-engine` core. However, the primary challenge is transitioning from deterministic API extraction (structured JSON) to probabilistic document extraction (unstructured PDF/Text).

### Technical Requirements:
*   **Parsing**: Integration with `unstructured` or `pypdf` for raw text recovery.
*   **LLM Extraction**: Using an LLM (e.g., Gemini) to locate and normalize specific fields (Metric, Value, Period) from the recovered text.
*   **Existing Infrastructure**: We can reuse the `Orchestrator`, `Validator`, and `AESFormatter` (CSV/JSONL) layers already built in `dataproc-engine`.

## 2. Proposed Architecture

### [New] FileProvider
A new `BaseProvider` implementation that:
1.  **Extracts**: Reads files from a local `--input-dir`.
2.  **Transforms**: Sends text chunks to an LLM with a strict schema prompt to extract the high-signal metrics.
3.  **Validates**: Applies the same domain-specific logic (e.g., Balance Sheet check) to ensure LLM extraction was hallucination-free.

## 3. Workflow Example
1.  **User provides**: Annual Report PDF (internal/unlisted).
2.  **Command**: `python dataproc-cli extract --provider file --input-dir ./my_reports --format csv --target-industries finance`
3.  **Engine outputs**: A high-signal `finance_records.csv` derived from the user's proprietary docs.

## 4. Practical Roadmap
1.  **v1 (Current)**: Deterministic API sources (SEC/FRED).
2.  **v2 (Proposed)**: Local file ingestion with simple regex/keyword extraction.
3.  **v3 (Pro)**: Intelligent LLM-powered extraction for truly complex, unstructured documentation.
