import pandas as pd
from typing import Any

def fit_multivariate_model(df: pd.DataFrame) -> Any:
    """
    Step 2: Fit Generative Models.
    Currently fits a multivariate normal approximation for numeric and frequency models for categorical.
    V2.1 Note: Will integrate 'copulas' library once environment dependencies are resolved.
    """
    # 1. Numeric Model: Mean and Covariance Matrix
    numeric_df = df.select_dtypes(include="number")
    model = {
        "numeric": {
            "mean": numeric_df.mean().to_dict(),
            "cov": numeric_df.cov().to_dict(),
            "cols": numeric_df.columns.tolist()
        },
        "categorical": {
            col: df[col].value_counts(normalize=True).to_dict()
            for col in df.select_dtypes(include="object")
        }
    }
    return model
