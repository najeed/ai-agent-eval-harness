"""
handlers/scenarios.py

Logic for scenario-related commands (AES, lint, inspect, etc.)
"""

import json
import os
from pathlib import Path

import yaml
from jsonschema import RefResolver, validate

from .. import catalog, drift_importer, linter, loader, mutator, spec_parser


def classify_scenario(scenario: dict) -> dict:
    """
    Industrially classifies a scenario based on its title and description.
    Uses semantic similarity mapping to industries for metadata enrichment.
    """
    try:
        # Lazy loading of ML components for industrial performance
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Industry labels and their embeddings (Industrial Taxonomy)
        industries = ["finance", "healthcare", "legal", "retail", "technology"]
        industry_embeddings = model.encode(industries)

        text = f"{scenario.get('title', '')} {scenario.get('description', '')}"
        text_embedding = model.encode(text)

        # Calculate cosine similarity (Industrial standard for semantic mapping)
        cos_sim = util.cos_sim(text_embedding, industry_embeddings)[0]
        top_idx = cos_sim.argmax()

        return {
            "industry": industries[top_idx],
            "confidence": float(cos_sim[top_idx]),
        }
    except Exception:
        # Fallback to generic if ML components are missing or fail
        return {"industry": "generic", "confidence": 0.0}


async def handle_aes_validate(args):
    """Handler for 'aes validate' command."""
    try:
        schema_path = Path(__file__).parent.parent.parent / "spec" / "aes" / "aes.schema.json"
        with open(schema_path) as f:
            schema = json.load(f)

        resolver = RefResolver(f"file:///{schema_path.parent.as_posix()}/", schema)

        path = Path(args.path)
        if path.is_file():
            files = [path]
        else:
            files = list(path.glob("*.aes.yaml")) + list(path.glob("*.json"))

        if not files:
            print(f"❌ Error: No AES scenarios found at path: {args.path}")
            return 1

        success_count = 0
        for f_path in files:
            try:
                with open(f_path) as f:
                    if f_path.suffix == ".yaml" or f_path.suffix == ".aes.yaml":
                        data = yaml.safe_load(f)
                    else:
                        data = json.load(f)

                validate(instance=data, schema=schema, resolver=resolver)
                ver = data.get("aes_version", "unknown")
                print(f"✔ {f_path.name}: Valid (AES v{ver})")
                success_count += 1

                # Industrial Export Logic (v1.2.3)
                if getattr(args, "export", None):
                    export_path = Path(args.export)
                    export_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(export_path, "w", encoding="utf-8") as yf:
                        yaml.safe_dump(data, yf, sort_keys=False, indent=2)
                    print(f"⚙ Exported stabilized AES.YAML to: {export_path}")
            except Exception as e:
                print(f"✘ {f_path.name}: Invalid - {str(e)}")

        return 0 if success_count == len(files) else 1
    except Exception as e:
        print(f"❌ [ERROR] AES Validation FAILED: {e}")
        return 1


async def handle_inspect(args):
    """Handler for 'inspect' command."""
    try:
        path = Path(getattr(args, "scenario_path", None) or getattr(args, "path", ""))
        if not path.exists():
            print(f"❌ Error: Scenario file not found: {path}")
            return 1

        scenario = loader.load_scenario(str(path))
        print("\n" + "=" * 60)
        print(f"{'SCENARIO INSPECTOR':^60}")
        print("=" * 60)
        metadata = scenario.get("metadata", {})
        print(f"ID:          {metadata.get('id', 'unknown')}")
        print(f"Name:        {metadata.get('name', 'Untitled')}")
        print(f"Industry:    {scenario.get('industry')}")
        print(f"Workflow:    {len(scenario.get('workflow', {}).get('nodes', []))} nodes")
        print("-" * 60)
        print(f"Description: {scenario.get('description')}")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Failed to inspect scenario: {e}")
        return 1


async def handle_lint(args):
    """Handler for 'lint' command."""
    try:
        linter.run_lint(args.target)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Linting FAILED: {e}")
        return 1


async def handle_list(args):
    """Handler for 'list' command."""
    try:
        cat = catalog.ScenarioCatalog()
        if getattr(args, "refresh", False):
            cat.build_index()
        else:
            cat.load_index()
        catalog.list_scenarios(query=getattr(args, "search", None))
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Failed to list scenarios: {e}")
        return 1


async def handle_catalog_search(args):
    """Handler for 'catalog-search' command."""
    try:
        cat = catalog.ScenarioCatalog()
        results = cat.search(args.query)
        for r in results:
            print(f" - {r.get('id', 'unknown')}: {r.get('title', 'Untitled')}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Catalog search FAILED: {e}")
        return 1


async def handle_mutate(args):
    """Handler for 'mutate' command."""
    try:
        if not os.path.exists(args.input):
            print(f"❌ Error: Mutation input file not found: {args.input}")
            return 1
        with open(args.input, encoding="utf-8") as f:
            scenario = json.load(f)
        mutated = mutator.mutate_scenario(scenario, args.type)
        output_path = Path(args.output or "mutated.json")
        mutator.save_mutated_scenario(mutated, output_path)
        print(f"✅ Mutation complete! Variant saved to: {output_path}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Mutation FAILED: {e}")
        return 1


async def handle_spec_to_eval(args):
    """Handler for 'spec-to-eval' command."""
    try:
        if not os.path.exists(args.input):
            print(f"❌ Error: Spec input file not found: {args.input}")
            return 1
        with open(args.input, encoding="utf-8") as f:
            markdown_text = f.read()
        scenario = await spec_parser.parse_markdown_to_scenario(markdown_text)
        output_path = Path(args.output or "scenario.json")
        spec_parser.save_scenario_json(scenario, output_path)
        print(f"✅ Conversion complete! Scenario saved to: {output_path}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Conversion FAILED: {e}")
        return 1


async def handle_import_drift(args):
    """Handler for 'import-drift' command."""
    try:
        out_dir = Path(getattr(args, "output_dir", "scenarios"))
        drift_importer.import_trace_as_scenario(Path(args.input), args.industry, out_dir)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Drift import FAILED: {e}")
        return 1


async def handle_scenario_generate(args):
    """Handler for 'scenario generate' command."""
    try:
        from .. import scaffold

        scaffold.generate_interactive()
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Scenario generation FAILED: {e}")
        return 1


async def handle_catalog_refresh(args):
    """Handler for 'catalog-refresh' command."""
    try:
        cat = catalog.ScenarioCatalog()
        cat.build_index()
        print("✅ Catalog index refreshed.")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Catalog refresh FAILED: {e}")
        return 1
