import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("topology_upgrader")


def upgrade_scenario(file_path: Path) -> bool:
    """Upgrades a scenario to version 2.0.0 and injects agent topology."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("version") == "2.0.0":
            return False

        # Upgrade version
        data["version"] = "2.0.0"

        # Add default full-access agent topology
        data["agent_topology"] = {"primary_agent": {"reads": ["*"], "writes": ["*"]}}

        # Inject crew specific metrics into task
        modified = False
        if "tasks" in data:
            for task in data["tasks"]:
                if "crew_success_criteria" not in task:
                    task["crew_success_criteria"] = [
                        {"metric": "delegation_loop_risk", "threshold": 0.0}
                    ]
                    # Also add a dummy delegation count expected
                    task["expected_delegations"] = 1
                    modified = True

        if modified:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        return False

    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}")
        return False


def main():
    target_dir = (
        Path(__file__).parent.parent / "industries" / "logistics_and_warehousing"
    )
    if not target_dir.exists():
        logger.error(f"Target directory {target_dir} not found.")
        return

    total_upgraded = 0

    logger.info(f"Upgrading Logistics scenarios to v2.0...")
    for scenario_file in target_dir.rglob("*.json"):
        if upgrade_scenario(scenario_file):
            total_upgraded += 1

    logger.info(f"Successfully upgraded {total_upgraded} scenarios.")


if __name__ == "__main__":
    main()
