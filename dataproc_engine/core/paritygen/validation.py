import pandas as pd
from scipy.stats import ks_2samp
from typing import Dict, Any

def validate_parity(original_df: pd.DataFrame, synthetic_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Step 4: Validate Parity using KS-Test, Wasserstein Distance, and Correlation Drift.
    """
    results = {}
    
    # 1. Distribution Tests (Continuous)
    from scipy.stats import wasserstein_distance
    for col in original_df.select_dtypes(include="number").columns:
        if col in synthetic_df.columns:
            # KS Test
            stat, pval = ks_2samp(original_df[col], synthetic_df[col])
            # True Wasserstein Distance
            w_dist = wasserstein_distance(original_df[col], synthetic_df[col])
            
            results[col] = {
                "ks_stat": round(stat, 4),
                "p_value": round(pval, 4),
                "wasserstein_dist": round(w_dist, 4),
                "status": "PASS" if pval > 0.05 else "DRIFT_WARN"
            }
            
    # 2. Correlation Matrix Drift
    orig_corr = original_df.select_dtypes(include="number").corr()
    syn_corr = synthetic_df.select_dtypes(include="number").corr()
    if not orig_corr.empty and not syn_corr.empty:
        corr_drift = (orig_corr - syn_corr).abs().max().max()
        results["_correlation_max_drift"] = round(corr_drift, 4)

    # 3. Categorical Frequencies
    for col in original_df.select_dtypes(include="object").columns:
        if col in synthetic_df.columns:
            orig_freq = original_df[col].value_counts(normalize=True).to_dict()
            syn_freq = synthetic_df[col].value_counts(normalize=True).to_dict()
            
            # Max frequency drift
            drift = 0.0
            for val in orig_freq:
                drift = max(drift, abs(orig_freq[val] - syn_freq.get(val, 0)))
            
            results[col] = {
                "max_freq_drift": round(drift, 4),
                "status": "PASS" if drift < 0.10 else "DRIFT_WARN"
            }
            
    return results
