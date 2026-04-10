# Cumulative Forensic Extensions
This directory supports the **Cumulative Registry Protocol**. 

Any `.json` or `.yaml` file placed here will be deep-merged into the base forensic policy at runtime.

## Usage
- Use this for environment-specific whitening or custom mandatory patterns (e.g., `99-local-audit.json`).
- Files are loaded in alphanumeric order.
