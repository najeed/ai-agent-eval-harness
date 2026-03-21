from eval_runner import cli
import json
from pathlib import Path
from unittest.mock import MagicMock

def test_inspect():
    print("Testing handle_inspect...")
    args = MagicMock()
    scen_path = Path("tmp_scen.json")
    scen_path.write_text(json.dumps({
        "scenario_id": "s1",
        "title": "Inspect Me",
        "description": "desc",
        "use_case": "uc",
        "core_function": "cf",
        "industry": "finance",
        "tasks": [{
            "task_id": "t1", 
            "description": "task", 
            "expected_outcome": "outcome", 
            "success_criteria": [{"metric": "planning_accuracy", "threshold": 0.5}]
        }]
    }))
    args.scenario_path = str(scen_path)
    try:
        cli.handle_inspect(args)
        print("✔ handle_inspect executed")
    except Exception as e:
        print(f"❌ handle_inspect failed: {e}")
    finally:
        if scen_path.exists():
            scen_path.unlink()

def test_lint():
    print("\nTesting handle_lint...")
    args = MagicMock()
    scen_path = Path("tmp_scen.json")
    scen_path.write_text(json.dumps({
        "scenario_id": "s1",
        "title": "Lint Me",
        "description": "desc",
        "use_case": "uc",
        "core_function": "cf",
        "industry": "finance",
        "tasks": [{
            "task_id": "t1", 
            "description": "task", 
            "expected_outcome": "outcome", 
            "success_criteria": [{"metric": "planning_accuracy", "threshold": 0.5}]
        }]
    }))
    args.target = str(scen_path)
    try:
        cli.handle_lint(args)
        print("✔ handle_lint executed")
    except Exception as e:
        print(f"❌ handle_lint failed: {e}")
    finally:
        if scen_path.exists():
            scen_path.unlink()

def test_taxonomy():
    print("\nTesting handle_taxonomy...")
    args = MagicMock()
    try:
        cli.handle_taxonomy(args)
        print("✔ handle_taxonomy executed")
    except Exception as e:
        print(f"❌ handle_taxonomy failed: {e}")

def test_catalog_search():
    print("\nTesting handle_catalog_search...")
    args = MagicMock()
    args.query = "api"
    try:
        cli.handle_catalog_search(args)
        print("✔ handle_catalog_search executed")
    except Exception as e:
        print(f"❌ handle_catalog_search failed: {e}")

if __name__ == "__main__":
    test_inspect()
    test_lint()
    test_taxonomy()
    test_catalog_search()
