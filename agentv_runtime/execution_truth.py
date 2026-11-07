"""Single authority for execution-mode eligibility for certification.

This predicate establishes eligibility only; signatures, evidence completeness,
identity, and claim-specific authority still have to be verified independently.
"""


def execution_truth_eligible(execution_mode: object, provisional: object = False) -> bool:
    """Only explicitly live, non-provisional execution can be authoritative."""
    return (
        isinstance(execution_mode, str)
        and execution_mode.strip().lower() == "live"
        and provisional is False
    )
