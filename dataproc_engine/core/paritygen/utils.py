import numpy as np
from typing import List

def dual_moment_correct(data: List[float], target_mean: float, target_std: float) -> List[float]:
    """
    Standardizes data and rescales to target mean/std to ensure zero-drift.
    """
    curr_mean = np.mean(data)
    curr_std = np.std(data)
    if curr_std == 0:
        return data
    # (x - mean) / std * target_std + target_mean
    return [((x - curr_mean) / curr_std) * target_std + target_mean for x in data]
