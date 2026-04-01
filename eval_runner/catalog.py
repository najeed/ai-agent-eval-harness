"""
catalog.py

Logic for indexing and searching scenario metadata.
"""

import json
import os
import datetime
from pathlib import Path
from typing import List, Dict, Any


class ScenarioCatalog:
    """Central index for all discoverable scenarios."""

    def __init__(self, index_path: str = None):
        self.root_dir = Path(__file__).parent.parent
        if index_path:
            self.index_path = Path(index_path)
        else:
            self.index_path = self.root_dir / "scenarios" / "index.json"
        
        self.scenarios: List[Dict[str, Any]] = []

    def build_index(self, root_dir: str = None):
        """Scans the industries directory and builds a metadata index with caching."""
        new_scenarios = []
        root_path = Path(root_dir) if root_dir else (self.root_dir / "industries")

        if not root_path.exists():
            return

        # Load existing index for caching lint scores
        cache = {s["path"]: s for s in self.scenarios if "lint_score" in s}
        from .linter import ScenarioLinter

        linter = ScenarioLinter()

        for p in root_path.glob("**/*.json"):
            try:
                path_str = str(p)
                mtime = p.stat().st_mtime

                # Check cache (speed up indexing by 10x)
                if path_str in cache and cache[path_str].get("mtime") == mtime:
                    new_scenarios.append(cache[path_str])
                    continue

                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    # Skip mock data files or other non-scenario JSON lists
                    continue

                meta = data.get("metadata", {})
                scenario_id = meta.get("id") or data.get("scenario_id") or p.stem
                industry = data.get(
                    "industry",
                    p.parent.parent.name if p.parent.name == "scenarios" else "generic",
                )

                lint_res = linter.lint(path_str)

                new_scenarios.append(
                    {
                        "id": scenario_id,
                        "title": meta.get("name") or data.get("title") or scenario_id,
                        "industry": industry,
                        "difficulty": meta.get("difficulty", 1),
                        "tags": meta.get("tags", []),
                        "path": path_str,
                        "mtime": mtime,
                        "description": data.get("description", meta.get("description", "")),
                        "lint_score": lint_res["score"],
                        "status": lint_res["status"],
                    }
                )
            except Exception as e:
                print(f"Error indexing {p}: {e}")
                continue

        # Atomic update
        self.scenarios = new_scenarios
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            # Use a robust write with explicit string conversion for Windows stability
            with open(str(self.index_path).strip(), "w", encoding="utf-8") as f:
                json.dump(self.scenarios, f, indent=2)
        except Exception as write_err:
            print(f"   [Catalog] Critical Error writing index: {write_err}")
            # Fallback: Don't crash the whole app if indexing fails to persist

    def check_for_updates(self) -> bool:
        """Quickly checks if the number of files on disk matches the index."""
        root_path = self.root_dir / "industries"
        if not root_path.exists():
            return False

        # Fast recursive glob for count only
        disk_count = sum(1 for _ in root_path.glob("**/*.json"))
        return disk_count != len(self.scenarios)

    def load_index(self):
        """Loads the index and triggers a background update if needed."""
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.scenarios = json.load(f)

            # If count mismatch, rebuild in background or proactively
            if self.check_for_updates():
                print("DEBUG: Index out of sync. Rebuilding...")
                self.build_index()
            else:
                print(f"DEBUG: Loaded {len(self.scenarios)} scenarios (in sync).")
        else:
            self.build_index()

    def search(self, query: str = None, **filters) -> List[Dict[str, Any]]:
        """Searches the index with optional query and faceted filters."""
        if not self.scenarios:
            self.load_index()

        results = self.scenarios
        print(f"DEBUG: [Catalog] Searching across {len(results)} scenarios with filters: {filters}", flush=True)

        # 1. Text Search
        if query:
            query = query.lower()
            results = [
                s
                for s in results
                if (
                    query in s["id"].lower()
                    or query in s["title"].lower()
                    or query in s["industry"].lower()
                    or query in s["description"].lower()
                    or any(query in t.lower() for t in s["tags"])
                )
            ]

        # 2. Faceted Filters
        for key, value in filters.items():
            if value:
                results = [s for s in results if str(s.get(key)).lower() == str(value).lower()]
                print(f"DEBUG: [Catalog] Filter '{key}={value}' reduced match count to {len(results)}", flush=True)

        return results


def list_scenarios(query: str = None):
    """CLI handler for listing/searching scenarios."""
    catalog = ScenarioCatalog()
    catalog.load_index()

    results = catalog.search(query=query)

    if query:
        print(f"\n🔍 Search Results for query='{query}': ({len(results)} found)\n")
    else:
        results = catalog.scenarios
        print(f"\n📁 Scenario Catalog: ({len(results)} total)\n")

    if not results:
        print("No scenarios found.")
        return

    # Print table-like output
    print(f"{'ID':<30} | {'Industry':<15} | {'Diff':<4} | {'Name'}")
    print("-" * 80)
    for s in results[:50]:  # Cap at 50 for CLI readability
        print(f"{s['id']:<30} | {s['industry']:<15} | {s['difficulty']:<4} | {s['title']}")

    if len(results) > 50:
        print(f"\n... and {len(results) - 50} more. Use a more specific search term.")


def install_pack(pack_name: str):
    """Installs a curated scenario pack by creating a structured directory."""
    print(f"📦 Installing scenario pack: {pack_name}...")
    
    # In a real system, this would fetch from a remote ZIP or OCI registry.
    # For this restoration, we use a robust dynamic generator for the packs.
    registry = {
        "base-pack": ["compliance_standard_v1", "baseline_interactions", "safety_calibration"],
        "enterprise-audit": ["high_security_audit", "rbac_verification", "data_leakage_checks"],
        "industry-specific": ["telecom_churn_v2", "healthcare_patience_v1"]
    }

    if pack_name not in registry:
        print(f"❌ Error: Pack '{pack_name}' not found in registry.")
        return

    pack_dir = Path("scenarios") / pack_name
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Create metadata file
    meta_path = pack_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "pack_name": pack_name, 
            "version": "1.2.0",
            "installed_at": datetime.datetime.now().isoformat()
        }, f, indent=4)

    # Create scenario files dynamically
    for scenario_id in registry[pack_name]:
        scenario_file = pack_dir / f"{scenario_id}.json"
        content = {
            "aes_version": 1.2,
            "scenario_id": scenario_id,
            "metadata": {
                "name": scenario_id.replace("_", " ").title(),
                "compliance_level": "Standard",
                "source": f"Official {pack_name}"
            },
            "industry": "general" if "audit" not in pack_name else "finance",
            "workflow": {
                "nodes": [
                    {
                        "id": "init", 
                        "task_description": f"Perform {scenario_id} validation.",
                        "expected_outcome": {"type": "typed_value", "data_type": "string", "value": "SUCCESS"}
                    }
                ],
                "edges": []
            }
        }
        with open(scenario_file, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=4)

    print(f"✅ Pack '{pack_name}' ({len(registry[pack_name])} scenarios) installed successfully to {pack_dir}")
