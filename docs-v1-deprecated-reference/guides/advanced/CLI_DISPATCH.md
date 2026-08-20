# Dynamic CLI Dispatch: The RoutingRegistry

AgentV uses a **Dynamic CLI Dispatch** system to ensure that the core engine remains lightweight while allowing industrial plugins to inject their own namespaced commands.

---

## 1. The `RoutingRegistry` Architecture

The `RoutingRegistry` is the central authority for command discovery. It decouples the CLI front-end from the actual handler implementation.

### Key Benefits:
- **Lazy Loading**: Plugin logic is only loaded when their specific command is invoked.
- **Namespace Isolation**: Prevents third-party plugins from accidentally overriding core commands.
- **Cross-Platform Consistency**: Provides a unified dispatch layer for Windows, Linux, and macOS.

---

## 2. Dynamic Command Injection

Plugins hook into the dispatch lifecycle via the `on_register_commands` hook.

```python
def on_register_commands(self, registry):
    # This command is automatically registered as 'agentv plugin <name> scan'
    registry.register_command("scan", self.handle_scan)
```

### Handler Protocol
Handlers receive the parsed `args` namespace and are responsible for execution. The `RoutingRegistry` provides built-in error handling for common dispatch failures (e.g., missing dependencies).

---

## 3. Industrial Aliasing

To support heritage workflows, the dispatch system allows for high-level aliasing of complex task sequences (e.g., `agentv gate` aliasing to a specific set of verification and audit-log checks).
