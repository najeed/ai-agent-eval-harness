# Algorithm Overview: dataproc-engine

The `dataproc-engine` follows a high-signal ETL (Extract, Transform, Load) lifecycle designed for industrial data portability and semantic integrity.

## 🌀 1. The Core Lifecycle
The `DatasetEngine` orchestrates the following sequential algorithm for each registered industry:

1.  **Initialize**: Load sector-specific configurations (API keys, input URIs, LLM strategies).
2.  **Extract**: Execute the `Universal Source Acquisition` algorithm (see below).
3.  **Transform**: Map raw artifacts to the `StandardSchema` using sector-specific parsers.
4.  **Validate**: Verify semantic integrity (e.g., Financial balance sheet checks, Healthcare schema constraints, Manufacturing productivity bounds).
5.  **Correlate**: Run the `Fuzzy Identity Resolution` algorithm to link records across the 16 industrial sectors.
6.  **Persist**: Serialize to `JSONL` or `CSV` with integrity SHA-256 checksums.

---

## 🛰️ 2. Universal Source Acquisition Algorithm
This algorithm abstracts the complexity of data retrieval into a single resilient call: `BaseProvider.load_raw_data(uri)`.

**Input**: A string `uri` (Can be a local file path or a web URL).

| Step | Action | Logic |
| :--- | :--- | :--- |
| **1. Protocol Detection** | Identify source type | Check if string starts with `http://` or `https://`. |
| **2. Format Resolution** | Identify data structure | Detect `.csv` or `.xlsx`/`.xls` via file extension or MIME type. |
| **3. Resilient Fetch** | Retrieve payload | If Remote: `aiohttp` with **Exponential Backoff** & **Circuit Breaker**. If Local: Direct `pandas` read. |
| **4. Fail-Safe Parsing** | Handle missing data | If fetch fails, return `None` (triggering the `High-Fidelity Simulation` fallback). |
| **5. Standard Output** | Return structured data | Return a `pandas.DataFrame` or `List[str]` for downstream transformation. |

---

## 🧩 3. Fuzzy Identity Resolution Algorithm
To link a "Finance" record (e.g., Apple Inc.) with a "Telecom" record (e.g., Apple), the engine uses the following fuzzy matching algorithm:

1.  **Extraction**: Pull `entity_id` and `location` from both records.
2.  **Normalization**: Strip legal suffixes (LLC, Inc, Corp) and convert to lowercase.
3.  **Similarity Scoring**: Utilize `rapidfuzz.process.extractOne` (Levenshtein Distance).
4.  **Cutoff Threshold**: 
    *   **Score > 90**: Exact match (Auto-link).
    *   **Score 80-89**: Potential match (Tag for manual/LLM review).
    *   **Score < 80**: Disjoint entities.
5.  **Location Grounding**: If scores are close, use `location` (latitude/longitude) or `date` to confirm the link.

---

## 🛡️ 4. Security & Integrity Layer
Every record produced by the engine passes through two final algorithms:

*   **PII Scrubbing**: Regex-based pattern matching to mask emails, phone numbers, and IP addresses before any LLM processing.
*   **Zero-Bundling Compliance**: For restricted-license benchmarks (e.g., Clinical Database V2, Industrial Statistics Agency), the engine utilizes **High-Fidelity Simulation** to generate schema-compliant records without redistributing protected data. Users must explicitly provide local paths (BYOD) to unlock real-world data extraction.
*   **SHA-256 Verification**: A deterministic hash of the final JSON content is generated and stored in `record.integrity_hash`, ensuring the data is tamper-evident.
