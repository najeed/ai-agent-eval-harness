# Compliance & Third-Party Licenses

This document outlines the license obligations and compliance steps for the MultiAgent Verification Framework (`multiagent-verify`), as of **April 2026**.

## 1. Core Framework License
The MultiAgent Verification Framework is distributed under the **Apache License 2.0**. See the [LICENSE](LICENSE) file in the root directory for details.

## 2. Third-Party Dependency Licenses
The following table summarizes the licenses of our core dependencies. All used licenses are permissive (MIT, BSD, Apache 2.0).

| Package | Version | License | License File |
| :--- | :--- | :--- | :--- |
| **aiohttp** | 3.13.5 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **Flask** | 3.1.3 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **flask-cors** | 6.0.2 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **requests** | 2.33.1 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **jsonschema** | 4.26.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **PyYAML** | 6.0.3 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **sentence-transformers** | 5.3.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **numpy** | 2.4.4 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **datasets** | 4.8.4 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **PyJWT** | 2.12.1 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **cryptography** | 46.0.6 | Apache 2.0 / BSD | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **opentelemetry-api** | 1.40.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **opentelemetry-sdk** | 1.40.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **google-genai** | 1.70.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |

## 3. Obligations & Compliance Steps
To remain compliant with these licenses, the following steps are handled automatically by this repository:

### Attribution
- [x] **NOTICE File**: A [NOTICE](NOTICE) file is maintained in the root directory to acknowledge all third-party contributors.
- [x] **LICENSE Preservation**: Original license texts are preserved in the `LICENSES/` directory.

### Security & Safety
- [x] **PyYAML**: The framework exclusively uses `yaml.safe_load()` to mitigate arbitrary code execution risks.
- [x] **Cryptography**: Binary distributions include the required Apache 2.0 / BSD dual-license notices.

### Datasets (Hugging Face)
> [!WARNING]
> While the `datasets` library is Apache 2.0, individual datasets (e.g., loaded via `load_dataset`) may have their own licenses (CC-BY, GPL, etc.). **Always verify the specific dataset terms before commercial use.**

## 4. Practical Implementation
Developers should maintain this structure by:
1. Updating the versions in `pyproject.toml` and this document simultaneously.
2. Adding any new third-party dependency licenses to the `LICENSES/` directory.
3. Updating the [NOTICE](NOTICE) file when adding new dependencies.
