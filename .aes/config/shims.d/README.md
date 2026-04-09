# 🛠️ Cumulative Industrial Registry (.d)

This directory is the **single source of truth** for all project-level and environment-specific shim configurations for the AgentEval Harness (v1.3.0+).

## 🚀 How it Works
1.  **Baseline**: The engine loads immutable core defaults from the package.
2.  **Extensions**: Any `.json` or `.yaml` file added here is merged onto the baseline.
3.  **Alphabetical Priority**: Files are merged in alphabetical order. A file named `99_shims.json` will override values in `01_lab_defaults.json`.

## 🔐 Managing Secrets
To securely manage API keys and private credentials:
1.  Create a file matching the pattern `*.local.json` (e.g., `99_secrets.local.json`).
2.  These files are **automatically ignored by Git** via the root `.gitignore`.
3.  See [99_local.json.example](/shim_resources.d/99_local.json.example) for a template.

## 📁 Standard Naming Convention
- `01-09`: Core infrastructural layers (DB endpoints, Global timeouts).
- `10-49`: Vertical industry extensions (Fintech, Healthcare).
- `50-89`: Team-shared lab overrides.
- `90-99`: Local developer overrides and secrets (Always use `.local.json`).
