import os

import pytest

from eval_runner import config, loader
from eval_runner.linter import ScenarioLinter

FINTECH_DIR = (config.PROJECT_ROOT / "scenarios" / "fintech").absolute()


@pytest.mark.parametrize(
    "scenario_path",
    [
        FINTECH_DIR / f
        for f in (os.listdir(FINTECH_DIR) if FINTECH_DIR.exists() else [])
        if f.startswith("fintech_") and f.endswith(".json")
    ],
)
def test_fintech_scenario_quality(scenario_path):
    """Ensure all new Fintech scenarios are valid and GOLD tier."""
    # 1. Load test
    scenario = loader.load_scenario(str(scenario_path))
    assert scenario is not None
    assert scenario["industry"] == "fintech"

    # 2. Lint test
    results = ScenarioLinter().lint(str(scenario_path))
    assert results["status"] == "pass"
    assert results["score"] == 100
    assert results["tier"] == "GOLD"
    assert len(results["errors"]) == 0
