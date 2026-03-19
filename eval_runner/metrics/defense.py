from typing import Dict, Any
from . import MetricRegistry

@MetricRegistry.register("information_fusion_accuracy")
@MetricRegistry.register("threat_identification_accuracy")
@MetricRegistry.register("decision_making_correctness")
@MetricRegistry.register("roe_compliance_score")
@MetricRegistry.register("supply_chain_resilience_index")
async def calculate_defense_high_fidelity_metric(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity defense evaluation.
    Maps to 'policy_adherence' or a custom defense rubric if complexity demands.
    """
    updated_criterion = criterion.copy()
    updated_criterion["judge_config"] = updated_criterion.get("judge_config", {})
    
    # Map to specialized rubrics if they exist
    rubric_map = {
        "roe_compliance_score": "policy_adherence",
        "threat_identification_accuracy": "factual_grounding",
        "decision_making_correctness": "strategic_planning"
    }
    
    metric_name = criterion.get("metric", "")
    updated_criterion["judge_config"]["judge_rubric"] = rubric_map.get(metric_name, "generic")
    
    from ..metrics import calculate_luna_judge_score
    return await calculate_luna_judge_score(updated_criterion, agent_summary)
