---
title: CLI Extensions
description: How to register custom subcommands for the AgentV CLI.
---

# CLI Extension Architecture

As of v1.6.0, AgentV supports **Zero-Touch CLI Extensions**. This allows Enterprise teams and external contributors to register custom subcommands (e.g., `agentv enterprise-check`) without modifying the Core `cli.py`.

## Overview

The extension mechanism leverages standard Python **Entry Points**. When the `agentv` CLI starts, it performs a non-blocking scan of the `agentv.extensions` namespace and allows any installed package to register its own subcommands.

## Registration Protocol

To register a new CLI extension, follow these two steps:

### 1. Define the Registration Function

In your package (e.g., `enterprise_extension/cli.py`), define a function that accepts an `argparse` subparsers object.

```python
def register_commands(subparsers):
    """
    Registers custom Enterprise commands.
    """
    enterprise_parser = subparsers.add_parser(
        "enterprise", 
        help="Enterprise-specific evaluation tools"
    )
    
    # Define arguments as usual
    enterprise_parser.add_argument("--audit", action="store_true")
    
    # MANDATORY: Set the functional dispatcher
    from .handlers import handle_enterprise_audit
    enterprise_parser.set_defaults(func=handle_enterprise_audit)
```

### 2. Declare the Entry Point

Add the following to your `pyproject.toml`:

```toml
[project.entry-points."agentv.extensions"]
enterprise = "enterprise_extension.cli:register_commands"
```

## Functional Dispatcher Pattern

All extensions **must** use the `set_defaults(func=...)` pattern. The Core CLI uses this to route the command execution without knowing the internal structure of your extension.

### Handler Signature

Your handler should accept the `args` object and return an integer exit code (0 for success).

```python
async def handle_enterprise_audit(args):
    """
    Example handler. Can be sync or async.
    """
    print("[Enterprise] Running audit...")
    # ... logic ...
    return 0
```

## Best Practices

### Lazy Loading
To ensure the CLI remains fast, **avoid heavy imports** at the top of your `cli.py`. Import your complex logic inside the registration function or the handler itself.

### Isolation
The Core CLI is designed to be "Industrial Grade" and will catch any exceptions raised during the loading of your extension. If your extension fails to load, Core will print a warning to `stderr` but will continue to function.

## Verification
You can verify your extension is loaded by running:
```bash
agentv --help
```
Your custom command should appear in the help output.
