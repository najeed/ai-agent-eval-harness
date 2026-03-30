# Implementation Plan: Transitioning Stubs to Real Logic

This plan outlines the steps required to replace the remaining "Bad Stubs" and hardcoded placeholders with robust, data-driven patterns, including a full audit and reconciliation of public documentation.

## User Review Required

> [!IMPORTANT]
> The transition involves moving hardcoded simulated data into external files within the `industries/` directory. This will clean the codebase but requires ensuring the `industries/` folder is packaged correctly with the library.

## Proposed Changes

### 1. Externalize Provider Simulation Data
Replace hardcoded dictionaries in industry providers with external file loading.

#### [NEW] [mock_datasets](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/industries/mock_data)
- Create `industries/healthcare/mock_cms.csv`
- Test persistent registration/unregistration to `.aes/plugins.json`.
- Test `trigger_interceptor` ensuring correct boolean aggregation.

### Coverage Enhancement Target 7: Session Lifecycle & Execution Loop
The `SessionManager` is the core execution engine of the harness.

#### [NEW] `tests/unit/core/test_session.py`
- Test `execute_tasks`: workflow DAG traversal, topological sort (including cycle detection), and empty workflow handling.
- Test turn-loop logic: Agent adapters calls, tool handling (single/multiple), and HITL (CI vs TTY vs Non-interactive).
- Test `_calculate_metrics`: Comprehensive validation of state hygiene (eq, exists, not_exists, contains) and metric function invocation.
- Test `fork`: Verified fork depth limits and state cloning.

### Coverage Enhancement Target 8: CLI Handlers (Environment)
Handlers in `eval_runner/handlers/environment.py` bridge the CLI to core logic.

#### [NEW] `tests/unit/handlers/test_environment_handlers.py`
- Test all command wrappers (`handle_init`, `handle_analyze`, `handle_registry_sync`, etc.) with dependency mocking.
- Test `detect_framework` with various project structures (LangGraph, CrewAI, Custom) in temporary directories.
- Test plugin registration persistence handlers.

### Coverage Enhancement Target 9: Console Backend (Flask Routes)
The REST API in `eval_runner/console/routes.py` powers the web interface.

#### [NEW] `tests/unit/console/test_routes.py`
- Utilize `flask.Flask.test_client()` for full endpoint verification.
- Test `execute_demo_command` with subprocess mocking and prefix whitelist validation.
- Test `list_scenarios` and `save_scenario` (v1.2 compliant JSON generation).
- Test `debugger/state` lifecycle and historical trace loading from `.jsonl`.
- Test `docs` retrieval and path traversal protection.

#### [MODIFY] [healthcare.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/dataproc_engine/providers/healthcare.py)
#### [MODIFY] [telecom.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/dataproc_engine/providers/telecom.py)
#### [MODIFY] [finance.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/dataproc_engine/providers/finance.py)
- Update `extract` methods to load from `industries/` if `allow_simulation` is True.

---

### 2. Robust JSON Serialization
Implement a unified encoder to handle non-standard types like `Mock` and `Path`.

#### [MODIFY] [trace_utils.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/trace_utils.py)
- Implement `AESJsonEncoder(json.JSONEncoder)`.

#### [MODIFY] [session.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/session.py)
- Replace ad-hoc mock checks in `_serialize_log` with the new encoder.

---

### 3. Configurable LLM Endpoints
Enable full endpoint customization to avoid patching URLs in tests.

#### [MODIFY] [llm_providers.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/llm_providers.py)
- Ensure `AnthropicProvider`, `GeminiProvider`, etc., use `api_base` or `base_url` from config if provided.

---

### 4. Dynamic Plugin Discovery
Remove hardcoded registry entries.

#### [NEW] [discovery.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/discovery.py)
- Implement logic to scan directories for subclasses of `BaseAdapter` and `BaseProvider`.

#### [MODIFY] [engine.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/engine.py)
- Use `discovery.py` to populate the `AgentAdapterRegistry` and `DatasetProviderRegistry`.

---

---

---

### 5. Package Manifest Update
Ensure all necessary data files are included in the distribution.

#### [MODIFY] [pyproject.toml](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/pyproject.toml)
- Update `[tool.setuptools]` to include the `industries/` directory.

---

### 6. Absolute Path Elimination
Strict removal of all absolute platform-specific paths from code and documentation.

#### [MODIFY] [config.py](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/eval_runner/config.py)
- Replace hardcoded `C:/tmp` with `Path.home() / ".aes" / "tmp"` or a relative traversal within `PROJECT_ROOT`.

#### [AUDIT] [Entire Repository]
- Scan all `.md`, `.py`, and `.json` files for `C:\`, `/Users/`, or `/home/` and replace with relative paths or environment-variable-backed defaults.

---

### 7. Comprehensive Documentation Audit & Reconciliation
Perform a full-system review of all documentation (including nested files) to ensure technical accuracy and alignment with AES v1.2 and the current engine architecture.

#### [MODIFY] [README.md](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/README.md)
- Update "At a Glance" and "Zero-Touch Core Architecture" sections.
- Ensure all CLI examples match the current command set.

#### [MODIFY] [docs/](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/docs)
- **Nested Audit**: Review all files in `docs/guides/`, `docs/api/`, and `docs/source/` for codebase reconciliation.
- [MODIFY] [architecture.md](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/docs/architecture.md): Document dynamic discovery and externalized mock data.
- [MODIFY] [guides/](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/docs/guides/): Synchronize `00_COMPREHENSIVE_GUIDE.md` and `04_AES_SPECIFICATION.md` with current workflow logic (Gating, DAGs).
- **Check**: Confirm that the **AES v1.2 specification** and **Engine Architecture** capabilities are fully documented across all nested files.

#### [MODIFY] [TESTING.md](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/TESTING.md)
- Reflect changes in test infrastructure and simplified serialization.

---

### 8. Final Workspace Cleanup
Ensure a clean, production-ready workspace by removing temporary orchestration files.

#### [DELETE] [implementation_plan.md](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/implementation_plan.md)
#### [DELETE] [task.md](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/task.md)
#### [CLEANUP] [Scripts]
- Identify and remove any one-off scratch scripts created during this session.

## Open Questions
- None. (Confirmed: `industries/` should be in the manifest).

## Verification Plan

### Automated Tests
- Run `pytest` to ensure all 508 tests pass with the new data loading and serialization logic.
- Add a new test in `test_trace_recorder.py` specifically for Mock object serialization.

### Manual Verification
- Run `multiagent-eval list-plugins` to verify dynamic discovery is working.
- Trigger a healthcare extraction with missing files to verify mock data loads from the CSV.
