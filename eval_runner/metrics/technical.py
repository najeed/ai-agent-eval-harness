from typing import Dict, Any
from . import MetricRegistry

@MetricRegistry.register("technical_correctness")
@MetricRegistry.register("algorithm_correctness")
@MetricRegistry.register("code_quality")
async def calculate_technical_correctness(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity technical evaluation using Luna-Judge.
    Maps to the 'technical_correctness' rubric.
    """
    updated_criterion = criterion.copy()
    updated_criterion["judge_config"] = updated_criterion.get("judge_config", {})
    updated_criterion["judge_config"]["judge_rubric"] = "technical_correctness"
    
    from ..metrics import calculate_luna_judge_score
    return await calculate_luna_judge_score(updated_criterion, agent_summary)
