# 🧪 Local Synthesis Instructions

The following industrial datasets may be **Restricted**. You cannot download them directly from this repository. Instead, you can use our **Statistical Simulators** to generate your own compliant local copy.

### 🚀 Quick Start (One Command)
Run the following to generate 50 records for your local clinical, energy, or industrial research:
```powershell
python industries/healthcare/generators/clinical_generator.py
python industries/energy/generators/energy_generator.py
python industries/manufacturing/generators/industrial_generator.py
```

### 🧠 Why are we doing this?
1.  **Privacy Protection**: Raw clinical data often contains sensitive PII that cannot be redistributed.
2.  **License Compliance**: Many industrial datasets have restrictive terms that prohibit embedding them in Public repos.
3.  **User Accountability**: By using these **Generators**, you assume the legal responsibility for your local environment. You are responsible for ensuring you have the rights to the source data used to calibrate these simulators.

### 📊 Verification
Each generator produces a `_provenance` block in the JSON output, proving the data was synthetically generated.

**Example Production Record**:
```json
{
  "subject_id": 123456,
  "primary_metric": 118.5,
  "secondary_metric": 78.2,
  "status": "Stable",
  "_provenance": {
    "synthetic": true,
    "source": "[your-input-source]",
    "generated_at": "2026-03-23T09:15:00Z",
    "compliance_disclaimer": "User assumes all liability for license compliance."
  }
}
```

### 🛠️ Customization
To increase the record count, edit the `__main__` block in the generator scripts or call them via the API:
```python
from industries.healthcare.generators.clinical_generator import ClinicalParityGenerator
data = ClinicalParityGenerator().generate(n_samples=5000)
```
