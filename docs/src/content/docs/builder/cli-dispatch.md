---
title: Dynamic CLI Dispatch
description: Understanding the RoutingRegistry and exhaustive command verification.
---

# Command Orchestration

AgentV uses a **Unified Functional Dispatcher** to manage its expansive CLI interface. This architecture separates the **CLI Parsing** (handled by `argparse`) from the **Internal Handler Execution**. This decoupling allows for modular extensions, plugin-injected commands, and exhaustive automated testing.

## The Functional Dispatcher Pattern

The `eval_runner.cli` module serves as the central entry point. Instead of a monolithic `if/elif` block, the harness uses `argparse` subparsers combined with the `set_defaults(func=...)` pattern to map commands to modular handler namespaces:

```python
# Core command registration (eval_runner/cli.py)
run_parser = subparsers.add_parser("run", help="Execute single scenario evaluation")
run_parser.set_defaults(func=_dispatch_evaluation)

console_parser = subparsers.add_parser("console", help="Launch the Visual Debugger")
console_parser.set_defaults(func=_dispatch_console)
```

### Handler Dispatch Namespaces
Commands route through categorized dispatcher functions:
- `_dispatch_evaluation`: Routes `run`, `replay`, `record`, `playground`, `quickstart`, `hitl-resume`, `gate`, `verify`, `certify`.
- `_dispatch_scenarios`: Routes `list`, `inspect`, `mutate`, `catalog-search`, `catalog-refresh`, `spec-to-eval`, `aes`, `lint`.
- `_dispatch_analysis`: Routes `report`, `leaderboard`, `calibrate`, `trend`, `list-metrics`, `taxonomy`.
- `_dispatch_environment`: Routes `ci`, `registry`, `export`, `plugin`, `list-plugins`, `analyze`, `auto-translate`.
- `_dispatch_extension`: Routes standalone extension lifecycle commands (`publish`, `activate`, `rollback`, `unpublish`, `verify`, `repair`) with zero web server dependencies.
- `_dispatch_console`: Routes `console` server launch and legacy `console extension` aliases.

---

## ⚡ High-Performance Zero-Touch Architecture

To maintain sub-10ms CLI startup times across enterprise environments:

### 1. Static vs. Dynamic Protocol Resolution
- **`STATIC_PROTOCOLS`**: Default protocol choices (`http`, `local`, `socket`, `sse`, `openapi`) are resolved statically without initiating network calls or scanning packages.
- **`DISCOVERY_COMMANDS`**: Dynamic adapter discovery is deferred until a command explicitly requires adapter inspection, calling `AgentAdapterRegistry.get_available_protocols(eager=False)`.

### 2. Extension Isolation Gating (`_should_load_cli_extensions`)
- External Python entry point extensions (`agentv_runtime.cli_extensions`) are loaded **only** if the invoked command is not in `BUILTIN_COMMANDS`.
- Built-in commands run with zero external import overhead, protecting core CLI execution from slow or faulty third-party packages.

### 3. Singleton Parser Caching
- `get_parser()` hashes `sys.argv` and caches the configured parser in `_parser_cache`.
- Cache invalidation is available via `_invalidate_parser_cache()` for unit test isolation and dynamic plugin reconfiguration.

---

## 🔒 Exhaustive CLI Testing

To ensure industrial-grade reliability, AgentV enforces an **Exhaustive Testing Standard** for the CLI layer. Every registered command must have a corresponding unit test that verifies:
1. **Successful Dispatch**: The command reaches the handler with the correct parameters.
2. **Error Handling**: Invalid arguments or environment failures are caught and reported with meaningful exit codes.
3. **Namespace Integrity**: CLI entry-point callbacks choose distinct command names and register handlers explicitly; argparse registration has no automatic namespace protection.

### Example: Testing a Dispatcher
We use `unittest.mock` to verify that the CLI correctly routes to the `eval_runner` engine handlers:

```python
from unittest.mock import patch
import pytest
from eval_runner.cli import _invalidate_parser_cache, main


def test_cli_routing_run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["agentv", "run", "--path", "my_path"])
    _invalidate_parser_cache()
    try:
        with patch("eval_runner.cli._dispatch_evaluation", return_value=0) as handler:
            with pytest.raises(SystemExit) as exit_info:
                main()
            assert exit_info.value.code == 0
            handler.assert_called_once()
    finally:
        _invalidate_parser_cache()
```

---

## 🔌 Plugin Commandments

External CLI entry points can register commands through argparse. See the [CLI extension guide](/extender/cli-extensions/) for explicit-command discovery:

1. **Scoping**: Registration callbacks must choose distinct command names; the CLI does not automatically namespace their parsers.
2. **Lifecycle**: Use `agentv <external-command> --help`; top-level `agentv --help` deliberately skips external imports.

:::tip
**Architectural Invariant**: This functional dispatch model is what allows AgentV to scale to hundreds of sub-commands without becoming a maintenance nightmare. It leverages Python's native `argparse` capabilities to provide a robust, typesafe, and testable interface.
:::
