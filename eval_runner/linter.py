"""
linter.py

Automated quality scoring and linting for AES scenarios.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
import hashlib

class ScenarioLinter:
    """Analyzes scenarios for quality, validity, and duplicates."""
    
    def lint(self, file_path: str) -> Dict[str, Any]:
        """Runs a suite of checks on a scenario file."""
        p = Path(file_path)
        results = {
            "file": p.name,
            "status": "pass",
            "warnings": [],
            "errors": [],
            "score": 100
        }
        
        if not p.exists():
            results["status"] = "fail"
            results["errors"].append("File not found")
            return results

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            results["status"] = "fail"
            results["errors"].append(f"Invalid JSON: {str(e)}")
            results["score"] = 0
            return results

        # 1. Metadata Checks (Phase 13 Compliance)
        meta = data.get("metadata", {})
        required_meta = ["difficulty", "industry"]
        for field in required_meta:
            if field not in meta:
                results["warnings"].append(f"Missing recommended metadata: '{field}'")
                results["score"] -= 10
        
        # 2. Structure Checks
        if "tasks" not in data or not isinstance(data["tasks"], list):
            results["errors"].append("Scenario has no 'tasks' list")
            results["status"] = "fail"
            results["score"] -= 50
        elif len(data["tasks"]) == 0:
            results["warnings"].append("Scenario has 0 tasks")
            results["score"] -= 20
            
        # 3. Complexity Calculation
        tool_use_count = 0
        for task in data.get("tasks", []):
            if "tools" in task:
                tool_use_count += len(task["tools"])
        
        results["complexity"] = {
            "task_count": len(data.get("tasks", [])),
            "suggested_tools": tool_use_count
        }

        if results["errors"]:
            results["status"] = "fail"
        elif results["warnings"]:
            results["status"] = "warning"
            
        return results

    def find_duplicates(self, root_dir: str) -> List[Dict[str, Any]]:
        """Identifies scenarios with identical task signatures."""
        hashes = {}
        duplicates = []
        root = Path(root_dir)
        
        for p in root.glob("**/*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Create a signature based on tasks
                tasks_str = json.dumps(data.get("tasks", []), sort_keys=True)
                signature = hashlib.md5(tasks_str.encode()).hexdigest()
                
                if signature in hashes:
                    duplicates.append({
                        "original": hashes[signature],
                        "duplicate": str(p)
                    })
                else:
                    hashes[signature] = str(p)
            except Exception:
                continue
        return duplicates


def run_lint(path: str):
    """CLI handler for linting."""
    linter = ScenarioLinter()
    if Path(path).is_file():
        res = linter.lint(path)
        print(json.dumps(res, indent=2))
    else:
        # Directory linting
        total = 0
        fails = 0
        for p in Path(path).glob("**/*.json"):
            res = linter.lint(str(p))
            total += 1
            if res["status"] == "fail":
                fails += 1
                print(f"❌ {p.name}: {res['errors']}")
        print(f"\nLinting complete. {total} scanned, {fails} failed.")
