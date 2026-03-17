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
        """Scans the industries directory and builds a metadata index."""
        self.scenarios = []
        root_path = Path(root_dir)
        
        if not root_path.exists():
            return

        for p in root_path.glob("**/*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                # Extract metadata
                meta = data.get("metadata", {})
                scenario_id = data.get("scenario_id", p.stem)
                
                # Industry Inference Logic (Decoupled)
                industry = data.get("industry")
                tags = meta.get("tags", [])
                
                if not industry:
                    # Fallback to folder structure if possible
                    if p.parent.name == "scenarios" and "ai-agent-eval-harness" in str(p.absolute()).lower():
                        industry = p.parent.parent.name
                    else:
                        industry = "unclassified"
                        if "local" not in tags:
                            tags.append("local")
                
                if "local" not in tags and "ai-agent-eval-harness" not in str(p.absolute()).lower():
                    tags.append("local")

                self.scenarios.append({
                    "id": scenario_id,
                    "title": data.get("title", scenario_id),
                    "industry": industry,
                    "difficulty": meta.get("difficulty", 1),
                    "tags": list(set(tags)), # Deduplicate
                    "path": str(p),
                    "description": data.get("description", meta.get("description", ""))
                })
            except Exception:
                continue
        
        # Save index
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.scenarios, f, indent=2)

    def load_index(self):
        """Loads the index from disk."""
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.scenarios = json.load(f)
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
                s for s in results 
                if (query in s["id"].lower() or 
                    query in s["title"].lower() or 
                    query in s["industry"].lower() or 
                    query in s["description"].lower() or
                    any(query in t.lower() for t in s["tags"]))
            ]
            
        # 2. Faceted Filters
        for key, value in filters.items():
            if value:
                results = [s for s in results if str(s.get(key)).lower() == str(value).lower()]
                
        return results

def list_scenarios(query: str = None):
    """CLI handler for listing/searching scenarios."""
    catalog = ScenarioCatalog()
    catalog.load_index()
    
    if query:
        results = catalog.search(query)
        print(f"\n🔍 Search Results for '{query}': ({len(results)} found)\n")
    else:
        results = catalog.scenarios
        print(f"\n📂 Scenario Catalog: ({len(results)} total)\n")

    if not results:
        print("No scenarios found.")
        return

    # Print table-like output
    print(f"{'ID':<30} | {'Industry':<15} | {'Diff':<4} | {'Title'}")
    print("-" * 80)
    for s in results[:50]: # Cap at 50 for CLI readability
        print(f"{s['id']:<30} | {s['industry']:<15} | {s['difficulty']:<4} | {s['title']}")
        
    if len(results) > 50:
        print(f"\n... and {len(results) - 50} more. Use a more specific search term.")
