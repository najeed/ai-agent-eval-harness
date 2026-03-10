# AES v0.2: Architectural Proposals

Based on the initial design of AES v0.1, here are the proposed enhancements to increase portability and enterprise utility.

## 1. Strongly Typed Tool Definitions
**Current**: `tools: ["refund_api"]` (Vague string-based tracking)  
**Proposed**: Full function-calling schemas within the AES file.  
> [!NOTE]
> This allows the harness to automatically mock or validate tool signatures without external dependencies.
```yaml
tools:
  - name: refund_api
    description: Processes a refund for a given flight.
    parameters:
      type: object
      properties:
        flight_number: { type: string }
```

## 2. Infrastructure Lifecycle Hooks
**Current**: Environment is just a simulator string.  
**Proposed**: Support for `pre_eval` and `post_eval` commands.
```yaml
environment:
  simulator: airline_support_env:v1
  hooks:
    pre_eval: "scripts/db_reset.sh --seed airline_data"
    post_eval: "scripts/cleanup.py"
```

## 3. Parametric & Composite Metrics
**Current**: Simple name-based list.  
**Proposed**: Configurable metrics with weights and nested parameters.
```yaml
metrics:
  - name: semantic_similarity
    params:
      model: "text-embedding-3-large"
      threshold: 0.92
    weight: 1.5
```

## 4. Expected State Assertions (Ground Truth)
**Current**: `expected_outcome` is a flat object.  
**Proposed**: Structured assertions against the environment state.
```yaml
expected_state:
  - path: "sql://refunds"
    assertion: "exists"
    filter: { flight: "UA483" }
```

## 5. Golden Path Reference (Few-Shot/Alignment)
**Current**: No trajectory reference.  
**Proposed**: Embedding a reference `run.jsonl` segment.
```yaml
reference_trajectory:
  - { event: "agent_response", content: "Checking flight status..." }
  - { event: "tool_call", tool: "flight_db", arguments: { flight: "UA483" } }
```

## 6. Negative Task Constraints (Safety/Red Teaming)
**Current**: Focused on successful completion.  
**Proposed**: `policies` section to define forbidden behaviors.
```yaml
policies:
  - id: p1
    description: "Never disclose customer PII to unauthorized roles."
    severity: CRITICAL
```
