from typing import Dict, Any
from . import MetricRegistry

@MetricRegistry.register("planning_quality")
@MetricRegistry.register("strategic_planning")
async def calculate_planning_quality(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity planning evaluation using Luna-Judge.
    Maps to the 'strategic_planning' rubric.
    """
    # Luna Judge handles the rubric selection based on the 'judge_rubric' key
    # or we can force it here by modifying the criterion
    updated_criterion = criterion.copy()
    updated_criterion["judge_config"] = updated_criterion.get("judge_config", {})
    updated_criterion["judge_config"]["judge_rubric"] = "strategic_planning"
    
    # Import here to avoid circular dependencies
    from ..metrics import calculate_luna_judge_score
    return await calculate_luna_judge_score(updated_criterion, agent_summary)

@MetricRegistry.register("root_cause_analysis_correctness")
@MetricRegistry.register("causal_inference")
async def calculate_root_cause_analysis(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity root cause evaluation using Luna-Judge.
    Maps to the 'causal_inference' rubric.
    """
    updated_criterion = criterion.copy()
    updated_criterion["judge_config"] = updated_criterion.get("judge_config", {})
    updated_criterion["judge_config"]["judge_rubric"] = "causal_inference"
    
    from ..metrics import calculate_luna_judge_score
    return await calculate_luna_judge_score(updated_criterion, agent_summary)
