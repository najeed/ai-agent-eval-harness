---
title: CLI Extensions
description: How to register custom subcommands for the AgentV CLI.
---

Register external CLI commands through `agentv_runtime.cli_extensions` entry
points. The CLI imports these only when invoked with an explicit command outside
its built-in set. Built-in commands, top-level `--help` and `--version` skip
third-party CLI imports.

```toml
[project.entry-points."agentv_runtime.cli_extensions"]
enterprise = "enterprise_extension.cli:register_commands"
```

```python
def register_commands(subparsers):
    parser = subparsers.add_parser("enterprise", help="Enterprise evaluation tools")
    parser.add_argument("--audit", action="store_true")
    parser.set_defaults(func=handle_enterprise)


def handle_enterprise(args):
    print("Enterprise audit requested:", args.audit)
    return 0
```

After installing that package, invoke `agentv enterprise --help`. Top-level help
does not discover external commands. Registration/import is synchronous; keep
heavy imports inside handlers. The CLI logs registration exceptions and continues.

Choose distinct command names. The callback receives argparse subparsers
directly; it is not automatically placed under `agentv plugin <name>` and should
not attempt to redefine built-ins. `BaseEvalPlugin.on_register_commands` is a
plugin hook declaration, not this CLI entry-point discovery mechanism.
