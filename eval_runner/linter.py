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

    def get_quality_tier(self, score: int) -> str:
        """Determines the quality tier based on the lint score."""
        if score >= 90:
            return "GOLD"
        elif score >= 70:
            return "SILVER"
        elif score >= 50:
            return "BRONZE"
        return "UNRANKED"

    def lint(self, file_path: str) -> Dict[str, Any]:
        """Runs a suite of checks on a scenario file."""
        p = Path(file_path)
        results = {
            "file": p.name,
            "status": "pass",
            "warnings": [],
            "errors": [],
            "score": 100,
            "tier": "GOLD",
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
            results["tier"] = "UNRANKED"
            return results

        # 1. Registry/List Check
        if isinstance(data, list):
            if p.name == "index.json":
                results["status"] = "pass"
                results["tier"] = "REGISTRY"
                results["score"] = 100
                results["warnings"].append("Registry file ignored by standard scenario linting.")
                return results
            else:
                results["status"] = "fail"
                results["errors"].append(f"Scenario file must be a JSON object, found list")
                results["score"] = 0
                results["tier"] = "UNRANKED"
                return results

        if not isinstance(data, dict):
            results["status"] = "fail"
            results["errors"].append(f"Scenario file must be a JSON object, found {type(data).__name__}")
            results["score"] = 0
            results["tier"] = "UNRANKED"
            return results

        aes_version = data.get("aes_version")
        results["aes_version"] = aes_version
        
        if aes_version != 1.2:
            results["errors"].append(f"Invalid aes_version: {aes_version} (Requires 1.2-STABLE)")
            results["status"] = "fail"
            results["score"] -= 50

        # Mandatory Top-Level Fields (v1.2-STABLE)
        mandatory_fields = ["aes_version", "metadata", "workflow", "industry"]
        for field in mandatory_fields:
            if field not in data or not data[field]:
                results["errors"].append(f"Missing mandatory field: '{field}'")
                results["status"] = "fail"
                results["score"] -= 20

        # Metadata Compliance (v1.2 requirement)
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
             results["errors"].append("Metadata must be a JSON object")
             results["status"] = "fail"
        else:
            if "attribution" not in metadata:
                results["warnings"].append("Missing recommended field: 'metadata.attribution' (v2.0-STABLE requirement)")
                results["score"] -= 10
            if "version" not in metadata:
                results["warnings"].append("Missing recommended field: 'metadata.version'")
                results["score"] -= 5

        # Recommend complexity_level instead of difficulty
        if "complexity_level" not in data:
            results["warnings"].append("Missing recommended field: 'complexity_level' (low/medium/high)")
            results["score"] -= 5

        # 2. Workflow Validation (Nodes & Edges)
        if "workflow" not in data or not isinstance(data["workflow"], dict):
            results["errors"].append("Missing or invalid 'workflow' block (Standard requires nodes/edges)")
            results["status"] = "fail"
        else:
            wf = data["workflow"]
            if "nodes" not in wf or not isinstance(wf["nodes"], list):
                results["errors"].append("Workflow missing 'nodes' array")
                results["status"] = "fail"
            elif len(wf["nodes"]) == 0:
                results["warnings"].append("Workflow has 0 nodes")
                results["score"] -= 20
            else:
                node_ids = set()
                for i, node in enumerate(wf["nodes"]):
                    n_id = node.get("id")
                    if not n_id or "task_description" not in node:
                        results["errors"].append(f"Node {i} missing 'id' or 'task_description'")
                        results["status"] = "fail"
                    if n_id:
                        node_ids.add(n_id)

                # Edge Integrity
                edges = wf.get("edges", [])
                if not isinstance(edges, list):
                    results["errors"].append("Workflow 'edges' must be a list")
                else:
                    for i, edge in enumerate(edges):
                        if "from" not in edge or "to" not in edge:
                            results["errors"].append(f"Edge {i} missing 'from' or 'to'")
                        elif edge["from"] not in node_ids or edge["to"] not in node_ids:
                            results["errors"].append(f"Edge {i} references invalid node: {edge['from']} -> {edge['to']}")
                            results["status"] = "fail"

        # 3. Complexity Calculation
        node_count = len(data.get("workflow", {}).get("nodes", []))
        results["complexity"] = {
            "node_count": node_count,
        }

        if results["errors"]:
            results["status"] = "fail"
        elif results["warnings"]:
            results["status"] = "warning"
            
        # 4. Final Scoring & Tier
        results["score"] = max(0, results["score"])
        results["tier"] = self.get_quality_tier(results["score"])

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

                # Create a signature based on workflow nodes
                workflow = data.get("workflow", {})
                sig_payload = workflow.get("nodes", [])
                
                tasks_str = json.dumps(sig_payload, sort_keys=True)
                signature = hashlib.md5(tasks_str.encode()).hexdigest()

                if signature in hashes:
                    duplicates.append({"original": hashes[signature], "duplicate": str(p)})
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
            else:
                status_icon = "✅" if res["status"] == "pass" else "⚠"
                print(f"{status_icon} {p.name}: Score {res['score']} [{res['tier']}]")
        print(f"\nLinting complete. {total} scanned, {fails} failed.")
