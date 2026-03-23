import pandas as pd
import numpy as np
from typing import Dict, Any

def generate_synthetic(model: Dict[str, Any], n_samples: int = 1000) -> pd.DataFrame:
    """
    Step 3: Generate Synthetic Samples from the fitted models.
    Preserves joint distributions (correlations) via Multivariate Normal sampling.
    """
    # 1. Sample Numeric Fields (Preserving Correlation)
    num_meta = model["numeric"]
    means = [num_meta["mean"][col] for col in num_meta["cols"]]
    cov = [[num_meta["cov"][c1][c2] for c2 in num_meta["cols"]] for c1 in num_meta["cols"]]
    
    # Generate Multivariate Normal Samples
    synthetic_numeric = np.random.multivariate_normal(means, cov, size=n_samples)
    synthetic_df = pd.DataFrame(synthetic_numeric, columns=num_meta["cols"])
    
    # 2. Sample Categorical Fields (Preserving Frequencies)
    for col, freqs in model["categorical"].items():
        categories = list(freqs.keys())
        probabilities = list(freqs.values())
        synthetic_df[col] = np.random.choice(categories, size=n_samples, p=probabilities)
        
    return synthetic_df
