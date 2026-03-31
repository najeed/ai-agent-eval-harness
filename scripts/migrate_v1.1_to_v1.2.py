import json
import logging
from pathlib import Path
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migration_v1_2")

def migrate_scenario(file_path: Path) -> bool:
    """Physically migrates a v1.1 scenario to v1.2 DAG structure."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return False
        # Check if version upgrade is needed
        version = data.get("aes_version", 1.1)
        has_workflow = "workflow" in data
        has_tasks = "tasks" in data

        if version == 1.2 and has_workflow:
            return False
            
        if not has_tasks and not has_workflow:
            return False

        logger.info(f"Migrating {file_path.name} to AES v1.2...")

        nodes = []
        edges = []
        for i, task in enumerate(data["tasks"]):
            node_id = task.get("task_id") or f"node_{i}"
            nodes.append({
                "id": node_id,
                "task_description": task.get("description"),
                "expected_outcome": {
                    "type": "typed_value",
                    "data_type": "object",
                    "value": task.get("expected_outcome")
                }
            })
            if i > 0:
                edges.append({"from": nodes[i-1]["id"], "to": node_id})

        # Preserve main metadata
        new_data = {
            "aes_version": 1.2,
            "metadata": {
                "name": data.get("title", file_path.stem),
                "compliance_level": "Standard"
            },
            "description": data.get("description", ""),
            "industry": data.get("industry", "unknown"),
            "workflow": {
                "nodes": nodes,
                "edges": edges
            },
            "evaluation": {
                 "consensus": {
                     "strategy": "Majority_Vote",
                     "min_judges": 1,
                     "judge_panel": ["Luna-1"]
                 }
            }
        }

        # Keep initial_state and policies if they exist
        if "initial_state" in data:
            new_data["initial_state"] = data["initial_state"]
        if "policies" in data:
            new_data["policies"] = data["policies"]
        if "enabled_shims" in data:
            new_data["enabled_shims"] = data["enabled_shims"]

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2)
        
        return True

    except Exception as e:
        logger.error(f"Failed to migrate {file_path}: {e}")
        return False

def main():
    root_dir = Path(__file__).parent.parent
    targets = [root_dir / "industries", root_dir / "scenarios"]
    
    total_migrated = 0
    for target in targets:
        if not target.exists():
            continue
            
        for scenario_file in target.rglob("*.json"):
            if migrate_scenario(scenario_file):
                total_migrated += 1

    logger.info(f"Successfully migrated {total_migrated} scenarios to AES v1.2 standard.")

if __name__ == "__main__":
    main()
