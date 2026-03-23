import pandas as pd
from typing import Dict, Any

def profile_data(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Step 1: Extract Statistical Profiles.
    Compute descriptive statistics, variance, and correlations.
    """
    stats = {
        "mean": df.mean(numeric_only=True).to_dict(),
        "variance": df.var(numeric_only=True).to_dict(),
        "correlations": df.corr(numeric_only=True).to_dict(),
        "categorical_freqs": {
            col: df[col].value_counts(normalize=True).to_dict()
            for col in df.select_dtypes(include="object")
        },
        "shape": df.shape,
        "columns": df.columns.tolist()
    }
    return stats
