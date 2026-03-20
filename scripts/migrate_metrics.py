# scripts/migrate_metrics.py
import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("metric_migrator")

# Mapping defined based on v3.0 metrics.py and the implementation_plan
METRIC_MAPPING = {
    # Theoretical names commonly found in legacy JSONs -> Real metrics.py functions
    "information_retrieval_accuracy": "tool_call_correctness",
    "data_entry_accuracy": "tool_call_correctness",
    "data_analysis_accuracy": "factual_accuracy",
    "communication_accuracy": "communication_clarity",
    "process_adherence": "policy_compliance",
    "system_navigation_efficiency": "performance_efficiency",
    "problem_resolution_rate": "factual_accuracy",
    "technical_troubleshooting_accuracy": "tool_call_correctness",
    "customer_satisfaction_score": "communication_clarity",
}


def migrate_scenario(file_path: Path) -> int:
    """Reads a scenario, updates deprecated metrics, and returns the number of changes made."""
    changes = 0
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "tasks" not in data:
            return 0

        for task in data["tasks"]:
            if "success_criteria" not in task:
                continue

            for criterion in task["success_criteria"]:
                old_metric = criterion.get("metric")
                # Also normalize to lower case just in case
                if old_metric and old_metric.lower() in METRIC_MAPPING:
                    new_metric = METRIC_MAPPING[old_metric.lower()]
                    criterion["metric"] = new_metric
                    changes += 1

        if changes > 0:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}")

    return changes


def run_migration(root_dir: str):
    logger.info(f"Starting metric migration across {root_dir}")
    base_path = Path(root_dir)

    total_files = 0
    total_modifications = 0
    modified_files = 0

    # Iterate through all JSON files in industries folder recursively
    for json_file in base_path.rglob("*.json"):
        total_files += 1
        changes = migrate_scenario(json_file)
        if changes > 0:
            modified_files += 1
            total_modifications += changes

    logger.info(f"Migration Complete!")
    logger.info(f"Scanned Files: {total_files}")
    logger.info(f"Modified Files: {modified_files}")
    logger.info(f"Total Metric Replacements: {total_modifications}")


if __name__ == "__main__":
    import os

    # Default to assuming script is run from project root
    target_dir = os.path.join(os.path.dirname(__file__), "..", "industries")
    run_migration(target_dir)
