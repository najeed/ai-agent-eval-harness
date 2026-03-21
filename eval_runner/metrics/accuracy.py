from typing import Dict, Any
from . import MetricRegistry
from .utils import extract_numbers, compare_numerics
from .. import config
from ..rubrics import RubricRegistry


@MetricRegistry.register("luna_judge_score")
async def calculate_luna_judge_score(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    LLM-based evaluation using a configurable provider.
    Defaults to Jaccard similarity if provider fails or no expected outcome is provided.
    """
    expected_outcome = criterion.get("expected_outcome", "")
    if not expected_outcome:
        return 1.0

    # Short-circuit for exact matches to avoid LLM variance/cost
    if agent_summary.strip() == expected_outcome.strip():
        return 1.0

    try:
        from ..llm_providers import LLMProviderFactory

        # Check for judge_config overrides in the criterion
        judge_config = criterion.get("judge_config", {})

        provider_name = judge_config.get("judge_provider") or config.JUDGE_PROVIDER
        model_name = judge_config.get("judge_model") or config.JUDGE_MODEL
        temperature = float(judge_config.get("judge_temperature", config.LUNA_JUDGE_TEMPERATURE))
        rubric_name = judge_config.get("judge_rubric", "generic")

        # Essential Fix: Required Judge Guard
        is_required = criterion.get("required", False)

        try:
            provider = LLMProviderFactory.create(provider_name)
        except Exception as e:
            if is_required:
                raise RuntimeError(
                    f"Judge Configuration Error: Required provider '{provider_name}' failed to initialize. {e}"
                )
            else:
                print(
                    f"      [Metrics] [Luna-Judge] Warning: Provider '{provider_name}' unavailable. Falling back to Jaccard."
                )
                raise e  # Trigger the fallback catch below

        # Select rubric
        rubric_template = RubricRegistry.get(rubric_name)
        prompt = rubric_template.format(expected_outcome=expected_outcome, agent_summary=agent_summary)

        # Handle model override if provided
        if hasattr(provider, "model") and model_name:
            provider.model = model_name

        response_text = await provider.generate(prompt, temperature=temperature)
        try:
            # Try to parse float only
            import re

            match = re.search(r"([0-1]\.[0-9]+|1\.0|0)", response_text)
            if match:
                score = float(match.group(1))
            else:
                score = float(response_text)

            print(f"      [Metrics] [Luna-Judge] Provider score: {score:.2f}")
            return max(0.0, min(1.0, score))
        except ValueError:
            print(f"      [Metrics] [Luna-Judge] Provider returned non-float: '{response_text}'")
    except Exception as e:
        if isinstance(e, RuntimeError) and "Judge Configuration Error" in str(e):
            raise e
        print(f"      [Metrics] [Luna-Judge] Evaluation failed: {e}")

    # Fallback to Jaccard Similarity (Only if not required)
    print("      [Metrics] [Luna-Judge] Executing Jaccard Fallback...")
    from .utils import calculate_jaccard

    score = calculate_jaccard(expected_outcome, agent_summary)
    print(f"      [Metrics] [Luna-Judge] Fallback similarity score: {score:.2f}")
    return score


@MetricRegistry.register("calculation_accuracy")
def calculate_calculation_accuracy(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity numerical accuracy check.
    Extracts numbers from both 'expected_outcome' and 'agent_summary' and compares them.
    Returns 1.0 if all numbers in expected are found in actual within tolerance.
    """
    expected_outcome = criterion.get("expected_outcome", "")
    if not expected_outcome or not agent_summary:
        return 0.0

    expected_nums = extract_numbers(expected_outcome)
    actual_nums = extract_numbers(agent_summary)

    if not expected_nums:
        return 1.0  # No numbers to verify

    # Check if each expected number has a match in actual numbers
    matches = 0
    for en in expected_nums:
        if any(compare_numerics(en, an) for an in actual_nums):
            matches += 1

    score = matches / len(expected_nums)
    print(f"      [Metrics] Calculation accuracy: {score:.2f} ({matches}/{len(expected_nums)} numbers matched)")
    return score


@MetricRegistry.register("verification_accuracy")
def calculate_verification_accuracy(criterion: Dict[str, Any], agent_summary: str) -> float:
    """
    High-fidelity verification check.
    Checks for verification keywords and semantic overlap.
    """
    verification_keywords = [
        "verified",
        "confirmed",
        "validated",
        "checked",
        "reconciled",
        "approved",
    ]
    summary_lower = agent_summary.lower()

    has_keyword = any(kw in summary_lower for kw in verification_keywords)

    # Also use Luna Judge for semantic grounding if available,
    # but here we'll use a local fallback to keep it fast
    from .utils import calculate_jaccard

    expected_outcome = criterion.get("expected_outcome", "")
    sim = calculate_jaccard(expected_outcome, agent_summary)

    score = 0.5 * (1.0 if has_keyword else 0.0) + 0.5 * sim
    print(f"      [Metrics] Verification accuracy: {score:.2f} (Keyword: {has_keyword}, Similarity: {sim:.2f})")
    return score
