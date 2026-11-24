---
title: Authoritative Discovery Engine
description: Understanding shim activation policies, strict relevance, and environment discovery in AgentV v1.6.0.
---

Shim activation is controlled by `ToolSandbox.get_active_simulators()` after
merging built-in, configured and plugin simulator classes.

## Activation rules

1. `GLOBAL_ENABLED_SHIMS` is the outer gate. A shim must be named there or the
   global list must include `*`.
2. If the scenario omits `enabled_shims`, activate only shims identified as
   relevant from its tools/assertion contract.
3. If the scenario provides `enabled_shims`, activate only names in that list,
   or all globally allowed shims when the list includes `*`. An explicit empty
   list activates none. Relevance does not override an explicit list.

`metadata.capabilities` selects agent routing capabilities; it does not activate
simulators. Declare tool requirements and valid assertion targets, or explicitly
list the shims needed for execution.

## Explicit configuration

This scenario fragment permits the database shim, subject to global policy:

```json
{"enabled_shims": ["database"]}
```

Custom shim configurations live in `.aes/config/shims.d/`. The registry's `type`
can select a registered simulator class. Plugins add simulator classes through
`on_register_simulators`; the sandbox constructs them with `config=shim_cfg`.
See [world shimming](/extender/shimming/) for a complete dispatch example.

## Diagnose missing shims

Check both the global gate and the scenario's explicit list. When the list is
absent, inspect whether the scenario's actual tool/assertion syntax is recognized
as relevant. Run `agentv doctor --registry` to inspect resolved configuration.
An explicit list is the clearest way to request a custom shim.
