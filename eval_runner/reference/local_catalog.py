"""
eval_runner.reference.local_catalog
OSS Reference Implementation: LocalFileCatalogStore
"""

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from eval_runner import config, utils
from eval_runner.interfaces.catalog import CatalogStore

logger = logging.getLogger(__name__)


class LocalFileCatalogStore(CatalogStore):
    """
    Local filesystem-backed reference CatalogStore.
    Reads scenario definitions from SCENARIOS_DIR and industries/ directories.
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or config.PROJECT_ROOT)

    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        scenarios = []
        search_dirs = [
            self.base_dir / "scenarios",
            self.base_dir / "industries",
        ]

        for s_dir in search_dirs:
            if not s_dir.exists():
                continue
            for ext in ("*.json", "*.yaml", "*.yml"):
                for p in s_dir.rglob(ext):
                    if not p.is_file() or p.name.startswith("."):
                        continue
                    if category and category.lower() not in str(p).lower():
                        continue
                    try:
                        scenarios.append(
                            {
                                "id": p.stem,
                                "path": str(p),
                                "relative_path": str(p.relative_to(self.base_dir)),
                            }
                        )
                    except Exception as e:
                        logger.debug("Failed to index scenario path %s: %s", p, e)
                        continue
        return scenarios

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        all_s = self.list_scenarios()
        target_path = None
        for item in all_s:
            if item["id"] == scenario_id or item["relative_path"] == scenario_id:
                target_path = Path(item["path"])
                break

        if not target_path or not target_path.exists():
            return None

        try:
            with open(target_path, encoding="utf-8") as f:
                if target_path.suffix in (".yaml", ".yml"):
                    return yaml.safe_load(f)
                return json.load(f)
        except Exception as e:
            logger.debug("Failed to read scenario %s at %s: %s", scenario_id, target_path, e)
            return None

    def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str:
        target_path = self.base_dir / "scenarios" / f"{scenario_id}.json"
        if not utils.is_path_safe(target_path, self.base_dir):
            raise PermissionError(f"Target path {target_path} is outside allowed boundary")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(scenario_data, f, indent=2)
        return str(target_path)

    def delete_scenario(self, scenario_id: str) -> bool:
        target_path = self.base_dir / "scenarios" / f"{scenario_id}.json"
        if target_path.exists() and utils.is_path_safe(target_path, self.base_dir):
            target_path.unlink()
            return True
        return False
