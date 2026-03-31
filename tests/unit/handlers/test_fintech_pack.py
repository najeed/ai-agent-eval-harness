import pytest
import os
from pathlib import Path
from eval_runner import loader
from eval_runner.linter import ScenarioLinter

FINTECH_DIR = Path("scenarios/fintech")

@pytest.mark.parametrize("scenario_file", [
    f for f in os.listdir(FINTECH_DIR) if f.startswith("fintech_") and f.endswith(".json")
])
def test_fintech_scenario_quality(scenario_file):
    """Ensure all new Fintech scenarios are valid and GOLD tier."""
    path = FINTECH_DIR / scenario_file
    
    # 1. Load test
    scenario = loader.load_scenario(str(path))
    assert scenario is not None
    assert scenario["industry"] == "fintech"
    
    # 2. Lint test
    results = ScenarioLinter().lint(str(path))
    assert results["status"] == "pass"
    assert results["score"] == 100
    assert results["tier"] == "GOLD"
    assert len(results["errors"]) == 0
