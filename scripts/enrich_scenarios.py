import json
import logging
from pathlib import Path
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("scenario_enricher")

INDUSTRIES_TO_ENRICH = ["telecom", "finance", "healthcare", "manufacturing", "energy", "defense", "public-sector"]


def enrich_scenario(file_path: Path) -> bool:
    """Injects state, governance, and state verification metrics into the scenario."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if already enriched
        if "initial_state" in data and "policies" in data:
            return False

        # Add initial state
        data["initial_state"] = {
            "session_active": True,
            "user_authenticated": True,
            "system_status": "nominal",
        }

        # Add generic policies
        data["policies"] = {
            "max_spend_limit": 500,
            "requires_approval_for_destructive_actions": True,
        }

        # Modify nodes to include expected_state_changes if tool_call_correctness is present
        modified = False
        workflow = data.get("workflow", {})
        nodes = workflow.get("nodes", [])

        if nodes:
            for node in nodes:
                has_state_metric = any(
                    c.get("metric") == "state_verification"
                    for c in node.get("success_criteria", [])
                )
                if not has_state_metric:
                    # Add dummy state change to test state_verification
                    if "expected_state_changes" not in node:
                        node["expected_state_changes"] = [
                            {"path": "task_completed", "value": True}
                        ]

                    if "success_criteria" not in node:
                        node["success_criteria"] = []

                    node["success_criteria"].append(
                        {"metric": "state_verification", "threshold": 1.0}
                    )
                    modified = True

        if (
            modified or "initial_state" not in data
        ):  # Save if we modified nodes or added state
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        return False

    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}")
        return False


def main():
    base_dir = Path(__file__).parent.parent / "industries"

    total_enriched = 0
    for industry in INDUSTRIES_TO_ENRICH:
        industry_path = base_dir / industry
        if not industry_path.exists():
            continue

        logger.info(f"Enriching {industry}...")
        for scenario_file in industry_path.rglob("*.json"):
            if enrich_scenario(scenario_file):
                total_enriched += 1

    logger.info(
        f"Successfully enriched {total_enriched} scenarios across Gold Tier industries."
    )


if __name__ == "__main__":
    main()
