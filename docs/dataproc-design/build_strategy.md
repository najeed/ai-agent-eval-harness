# dataproc-engine Build & Distribution Strategy

## 1. Standalone Package Architecture
The `dataproc-engine` is designed as a **standalone Python package** located in the `dataproc_engine/` directory. It has its own `pyproject.toml` to ensure:
*   **Decoupling**: The engine can be versioned, tested, and distributed independently of the `multiagent-eval` framework.
*   **Minimal Dependencies**: It only requires `click`, `pydantic`, `aiohttp`, `pandas`, and `pyarrow`, avoiding the bloat of the root harness (e.g., `Flask`, `sentence-transformers`).
*   **CLI Registration**: The `dataproc-cli` is registered as a project script within this sub-package.

## 2. Monorepo Integration
While the package is standalone, it can be integrated into the root development environment using **Editable Installs**.

### Recommended Development Workflow:
From the repository root:
```bash
pip install -e ./dataproc_engine
```
This registers the `dataproc-cli` in the user's environment and allows the root `eval_runner` to import from `dataproc_engine`.

## 3. Root pyproject.toml Options
There are two ways to handle the engine in the root `pyproject.toml`:

### Option A: Fully Decoupled (Default)
The root `pyproject.toml` remains unchanged. The engine is treated as an external library that the user installs manually if they need data processing capabilities.

### Option B: Optional Dependency (Recommended)
Add `dataproc-engine` as an optional dependency (extra) in the root `pyproject.toml`:
```toml
[project.optional-dependencies]
dataproc = [
    "dataproc-engine @ file://./dataproc_engine"
]
```
Then the user can run `pip install -e ".[dataproc]"` to install everything.

## 4. Zero-Redistribution ETL Principle
To comply with licensing restrictions of original data sources (e.g., restricted third-party benchmarks, **ISO Standards**), `dataproc-engine` follows a **Code-First, Data-Second** philosophy:
*   We **do not** copy or redistribute third-party dataset files in this repository.
*   We **do** distribute the automated `Provider` scripts that allow users to generate their own local copies of the dataset directly from the official source.
*   This ensures the framework is legally unimpeachable and perpetually synchronized with the latest upstream data.
