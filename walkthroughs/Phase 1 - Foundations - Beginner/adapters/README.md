# README: Native Adapters 

Learn how to connect the evaluation harness to different agentic endpoints using the built-in adapter framework.

## 🎯 Objectives
- Understand the difference between `http`, `socket`, `local`, `sse`, and `openapi` adapters.
- Modify `.env` to change the agent endpoint.
- Evaluate a local Python script using the `local` adapter.

## 🚀 Steps

### Step 1: The Config File
The harness looks at `.env` for its current connection settings.
- **`AGENT_API_URL`**: The endpoint (URL or Local Path).
- **`ADAPTER_TYPE`**: (Inferred from the URL scheme: `http`, `socket`, `local`, `sse`, `openapi`).
- **`AGENT_API_SPEC`**: Required for `openapi` adapter (local path or URL to JSON/YAML spec).

### Step 2: The Local Switch
To evaluate a script residing directly in this repository, we use the `local` adapter. Perform this by running:
```bash
python walkthroughs/Phase 1 - Foundations - Beginner/adapters/Step_1_Configure_Adapters.py
```

### Step 3: Run the Local Evaluation
Once configured, execute a scenario against our `local_agent_shim.py` mock.
```bash
agentv evaluate --path scenarios/cross_industry/disputed_claim.json
```

## 📊 Key Concepts
- **Shimming**: The `local` adapter "shims" your Python script, allowing it to respond to evaluation requests without needing a web server.
- **SSE Streaming**: The `sse` adapter automatically accumulates streaming chunks from the agent into a unified response for the evaluator.
- **OpenAPI Synthesis**: The `openapi` adapter dynamically generates an industrial client from a Swagger/OpenAPI spec, enabling evaluation of production-ready APIs with zero manual boilerplate.
- **Protocol Agnosticism**: Most scenarios are written without knowing which adapter will run them, ensuring high portability across environments.

---
*Ready to build the bridge? Run the [Step_1_Configure_Adapters.py](./Step_1_Configure_Adapters.py) script next!*
