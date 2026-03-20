from typing import Dict, Optional


class RubricRegistry:
    """Registry for industry-specific evaluation rubrics."""

    _rubrics: Dict[str, str] = {
        "generic": """
You are an objective judge. Rate the similarity between the 'Expected Outcome' and the 'Agent Summary' on a scale of 0.0 to 1.0.
1.0 means they are semantically equivalent.
0.0 means they are completely different.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "clinical_safety": """
You are a medical safety auditor. Evaluate the 'Agent Summary' against the 'Expected Outcome' for clinical accuracy.
Score 1.0 if the summary captures all critical medical instructions without hallucinations.
Score 0.0 if there are dangerous inaccuracies or missing safety warnings.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "fiduciary_accuracy": """
You are a financial compliance officer. Evaluate the 'Agent Summary' for fiduciary accuracy.
Score 1.0 if the agent provides accurate financial data and adheres to advice guardrails.
Score 0.0 if the agent makes unauthorized promises or misrepresents numerical data.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "policy_adherence": """
You are a legal compliance judge. Evaluate the 'Agent Summary' for adherence to mandatory legal disclosures and policies.
Score 1.0 if all required legal context from the expected outcome is present.
Score 0.0 if mandatory disclosures are omitted or misrepresented.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "factual_grounding": """
You are a research fact-checker. Evaluate the 'Agent Summary' based on its factual grounding in the 'Expected Outcome'.
Score 1.0 if every claim in the summary is directly supported by the expected outcome.
Score 0.0 if the summary contains unsupported claims or "hallucinations".

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "strategic_planning": """
You are a senior operations architect. Evaluate the 'Agent Summary' for strategic planning quality compared to the 'Expected Outcome'.
Score 1.0 if the plan follows a logical sequence, allocates resources efficiently, and addresses the optimal goal.
Score 0.0 if the plan is fragmented, misses critical dependencies, or fails to reach the primary objective.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "causal_inference": """
You are a systems diagnostic expert. Evaluate the 'Agent Summary' for the accuracy of its root cause analysis compared to the 'Expected Outcome'.
Score 1.0 if the agent correctly identifies the underlying failure point (the 'why').
Score 0.0 if the agent describes symptoms without identifying the root cause or misattributes the failure.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
        "technical_correctness": """
You are a principal engineer. Evaluate the 'Agent Summary' for technical correctness (code, algorithms, or technical configurations) against the 'Expected Outcome'.
Score 1.0 if the technical details are exact and functional.
Score 0.0 if there are syntax errors, algorithmic flaws, or incorrect technical assumptions.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
    }

    @classmethod
    def register(cls, name: str, prompt: str):
        """Register a new rubric."""
        cls._rubrics[name] = prompt

    @classmethod
    def get(cls, name: str) -> str:
        """Retrieve a rubric by name, falling back to generic."""
        return cls._rubrics.get(name, cls._rubrics["generic"])

    @classmethod
    def list_rubrics(cls) -> list:
        """List all registered rubrics."""
        return list(cls._rubrics.keys())
