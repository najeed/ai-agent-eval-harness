# Modular Routing Extensions
This directory supports the **Cumulative Registry Protocol**.

Any `.json` or `.yaml` file placed here will be deep-merged into the base routing manifest at runtime.

## Usage
- Drop environment-specific tool definitions here (e.g., `50-stg-tools.json`).
- Use this to extend routing without modifying the core `routing/manifest.json`.
- Files are loaded in alphanumeric order.
