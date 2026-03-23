# 📦 Parity Synthetic Generator

A Python package for generating synthetic datasets that preserve the statistical properties of restricted or licensed datasets, without redistributing raw records.
This tool enables mathematical parity generators for tabular, time‑series, and categorical data.

🚀 Features
- **Profiling**: Extract descriptive statistics, correlations, and distributions.
- **Modeling**: Fit copulas, ARIMA/VAR, or categorical frequency models.
- **Sampling**: Generate synthetic records with identical statistical properties.
- **Validation**: Compare synthetic vs original distributions (KS test, Chi‑square, Wasserstein).
- **Provenance**: Automatic metadata + compliance notes for licensing clarity.
- **CLI Tool**: Run parity generation directly from the command line.

📂 Installation
```bash
git clone https://github.com/your-org/paritygen.git
cd paritygen
pip install -e .
```

🖥️ Usage
**CLI**
```bash
paritygen --input original.csv --output synthetic.csv
```

**Python API**
```python
import pandas as pd
from paritygen.profiling import profile_data
from paritygen.modeling import fit_multivariate_model
from paritygen.sampling import generate_synthetic
from paritygen.validation import validate_parity
from paritygen.provenance import provenance_metadata

df = pd.read_csv("original.csv")
profile = profile_data(df)
model = fit_multivariate_model(df)
synthetic_df = generate_synthetic(model, n_samples=len(df))
report = validate_parity(df, synthetic_df)

print(report)
print(provenance_metadata("Restricted License", note="Statistical samples generated locally"))
```

⚖️ Compliance Policy
- ✅ **Embed** synthetic datasets only if source license permits (Public Domain, CC0, CC BY).
- ❌ **Do not embed** synthetic datasets derived from restricted or paywalled sources.
- ✅ **Provide generator code only** for restricted datasets. Users must run locally under their own credentials and assume all liability for license compliance.
- 📜 **Attribution**: Required for CC BY sources.
- 🔒 **Restricted datasets** must never be redistributed. Synthetic parity generators may be shared as code, not data.

🧭 Best Practices
- Always include provenance metadata in synthetic outputs.
- Document the original source dataset and its license locally.
- Validate parity with statistical tests before using synthetic data in production.
- **User Responsibility**: The user is solely responsible for ensuring the source data used for profiling is accessed legally.

📖 Example Provenance Metadata
```json
{
  "dataset_nature": "Statistical Parity Sample",
  "license_label": "Restricted (User-Responsible)",
  "generation_method": "synthetic_sampling",
  "provenance_statement": "This dataset consists of statistical samples generated from user-supplied parameters. It contains no raw records.",
  "timestamp": "2026-03-23T19:30:00Z"
}
```

📜 License
This project is licensed under Apache 2.0.
Note: Synthetic datasets generated from restricted sources must respect the original dataset’s license terms.
