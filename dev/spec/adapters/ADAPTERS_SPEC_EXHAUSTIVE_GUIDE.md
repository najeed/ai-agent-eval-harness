# Adapters Specification Masterclass: Governance & Tripartite Activation

This guide provides an exhaustive inventory of the **AgentV Adapters Specification** (v1.5.0). It details how administrators can granularly control the communication landscape of the evaluation engine.

---

## 🏗️ The Tripartite Taxonomy

To ensure industrial-grade governance, AgentV distinguishes between three layers of agent communication. This separation allows for "Zero-Inference" security, where high-risk local execution can be disabled while maintaining cloud model connectivity.

### 1. Infrastructure Protocols (`active_protocols`)
The bedrock of communication. These handle the literal transport of bits between the engine and the agent.
- **`http`**: The standard REST interface.
- **`sse`**: Server-Sent Events.
- **`local`**: **[HIGH RISK]** Spawns local subprocesses. Should be disabled in multi-tenant or untrusted environments.
- **`socket`**: High-performance Unix/TCP streaming.
- **`openapi`**: Automated rest-standard negotiation.

### 2. Model Providers (`active_providers`)
Adapters that handle the specific payload formats and authentication requirements of LLM backend providers.
- **`openai`**: GPT-5.4/o1 class communication.
- **`claude`**: Anthropic XML-based protocols.
- **`gemini`**: Google Vertex/AI-Studio integration.
- **`grok`**: xAI adversarial benchmarks.
- **`ollama`**: Local model parity testing.

### 3. Orchestration Frameworks (`active_frameworks`)
High-level SDKs that wrap agents. These often involve complex state management and autonomous loop logic.
- **`autogen`**: Microsoft multi-agent dialogue.
- **`crewai`**: Role-playing task orchestration.
- **`langgraph`**: State-machine-based agent logic.
- **`langchain`**: Classic chain/agent abstractions.

---

## Lesson 1: Administrative Whitelisting

By default, AgentV attempts to discover all available adapters. In enterprise deployments, you MUST specify an authoritative policy in `.aes/config/adapters/policy.json`.

### Policy Example: The Hardened Perimeter
```json
{
  "adapters": {
    "active_protocols": ["http", "openapi"],
    "active_providers": ["openai", "gemini"],
    "active_frameworks": ["langgraph"]
  }
}
```
**Effect**: 
- The `local` protocol is disabled (preventing subprocess execution).
- `autogen` and `crewai` logic cannot be loaded (reducing SDK overhead).
- Only `openai` and `gemini` endpoints are reachable.

---

## Lesson 2: Enforcement & Error Resolution

If a scenario specifies a protocol that is not whitelisted, the engine will raise a `ValueError` immediately upon turn initialization:

> `ValueError: Protocol 'autogen' is currently disabled by administrative policy (active_frameworks).`

### Overriding for Local Dev
To bypass these restrictions during local development without modifying the project policy, use the environment override:
```bash
$env:AES_ADAPTER_POLICY_OVERRIDE="frameworks:autogen,protocols:local"
```

---

## Lesson 3: Zero-Trust Baseline & Security-by-Default

In AES v1.4, the engine adopts a **Zero-Trust Baseline**. If no administrative policy (`policy.json`) is detected, the engine defaults to a hardened posture:
- **Whitelisted Protocols**: `http`, `openapi` (Standard communication only).
- **Blacklisted Infrastructure**: `local` (Subprocess) is disabled.
- **Blacklisted Ecosystem**: All Providers and Frameworks are disabled.

This ensures that misconfiguration results in a **Safe Lockdown** rather than an unauthorized opening of the execution surface.

---

## Lesson 4: Core Immutability (Anti-Hijacking)

To prevent third-party plugins from accidentally or maliciously overwriting core communication logic, the engine enforces **Core Immutability**.
- **Standard Core**: `http`, `local`, `socket`, `openapi`.
- **Enforcement**: Any attempt to re-register these protocols via the `on_discover_adapters` hook will be blocked with a system warning.
- **Overriding**: For advanced research scenarios, core protocols can only be overwritten by passing `allow_override=True` to the `register()` method.

---

## Lesson 5: The Custom Adapter Hook (`on_discover_adapters`)

When implementing a custom plugin that injects a new adapter, you MUST specify its category during registration to pass the whitelist gates.

```python
def on_discover_adapters(self, registry):
    # Industrial Standard: Always provide category metadata
    registry.register("my_proto", self.handler, category="framework")
```

---

## Lesson 6: Behavioral Configuration (The Settings Mesh)

As of AES v1.5.0, adapters can be granularly configured via the `settings` block in the mesh. This allows you to define behavioral defaults (like Docker usage or custom endpoints) that are mathematically bound to the evaluation environment.

### Structured Settings Example
In `.aes/config/adapters.d/autogen_policy.json`:
```json
{
  "adapters": {
    "settings": {
      "frameworks": {
        "autogen": {
          "use_docker": false,
          "api_url": "http://production-autogen:5002/execute"
        }
      }
    }
  }
}
```

### Hierarchy of Authority
To ensure operational flexibility, settings are resolved in the following order:
1. **Environment Variables**: `AUTOGEN_USE_DOCKER=true` (Ultimate Authority).
2. **Mesh Configuration**: `.aes/config/adapters.d/*.json` (Shared Policy).
3. **Internal Baselines**: Hardcoded defaults (System Safety).

This allows Enterprise IT to set a global "No-Docker" policy in the mesh while allowing specialized researchers to override it for a single run via environment variables.
