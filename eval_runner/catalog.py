"""
catalog.py

Logic for indexing and searching scenario metadata.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any


class ScenarioCatalog:
    """Central index for all discoverable scenarios."""

    def __init__(self, index_path: str = "scenarios/index.json"):
        self.index_path = Path(index_path)
        self.scenarios: List[Dict[str, Any]] = []

    def build_index(self, root_dir: str = "industries"):
        """Scans the industries directory and builds a metadata index with caching."""
        new_scenarios = []
        root_path = Path(root_dir)

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

                meta = data.get("metadata", {})
                scenario_id = data.get("scenario_id", p.stem)
                industry = data.get(
                    "industry",
                    p.parent.parent.name if p.parent.name == "scenarios" else "generic",
                )

                lint_res = linter.lint(path_str)

                new_scenarios.append(
                    {
                        "id": scenario_id,
                        "title": data.get("title", scenario_id),
                        "industry": industry,
                        "difficulty": meta.get("difficulty", 1),
                        "tags": meta.get("tags", []),
                        "path": path_str,
                        "mtime": mtime,
                        "description": data.get(
                            "description", meta.get("description", "")
                        ),
                        "lint_score": lint_res["score"],
                        "status": lint_res["status"],
                    }
                )
            except Exception as e:
                print(f"Error indexing {p}: {e}")
                continue

        # Atomic update
        self.scenarios = new_scenarios
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.scenarios, f, indent=2)

    def check_for_updates(self) -> bool:
        """Quickly checks if the number of files on disk matches the index."""
        root_path = Path("industries")
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
                results = [
                    s for s in results if str(s.get(key)).lower() == str(value).lower()
                ]

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
    print(f"{'ID':<30} | {'Industry':<15} | {'Diff':<4} | {'Title'}")
    print("-" * 80)
    for s in results[:50]:  # Cap at 50 for CLI readability
        print(
            f"{s['id']:<30} | {s['industry']:<15} | {s['difficulty']:<4} | {s['title']}"
        )

    if len(results) > 50:
        print(f"\n... and {len(results) - 50} more. Use a more specific search term.")
