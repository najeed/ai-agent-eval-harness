import json
import os
import jsonschema
from pathlib import Path


def generate_interactive():
    """Interactive prompt to generate scenarios."""
    print("\n[Generator] MultiAgentEval - Scenario Generator\n")

    industry = input("What industry? (e.g., customer_support, telecom): ").strip() or "general"
    capability = input("What capability? (e.g., refund handling, troubleshooting): ").strip() or "default"
    count_str = input("How many scenarios? (default: 1): ").strip()
    try:
        count = int(count_str) if count_str else 1
    except ValueError:
        count = 1

    output_dir = Path("scenarios") / industry
    output_dir.mkdir(parents=True, exist_ok=True)

    templates = [
        {
            "desc_tpl": "Automatically generated test case for {capability} in {industry} industry.",
            "task_tpl": "User wants to perform {capability}. Handle the request correctly.",
            "expected_tpl": "Successfully handled {capability}.",
        },
        {
            "desc_tpl": "Edge-case validation for {capability} workflows within the {industry} sector.",
            "task_tpl": "Simulate a complex {capability} interaction. Ensure the agent follows standard {industry} protocols.",
            "expected_tpl": "{capability_title} processed with full audit trails.",
        },
        {
            "desc_tpl": "Adversarial robustness check: {capability} under high-load/ambiguous conditions.",
            "task_tpl": "The user provides minimal info for {capability}. The agent must clarify and then execute.",
            "expected_tpl": "Agent clarifies request and completes {capability} correctly.",
        },
    ]

    generated_files = []
    for i in range(1, count + 1):
        tpl = templates[(i - 1) % len(templates)]
        scenario_id = f"gen_{industry}_{capability.replace(' ', '_')}_{i}"
        scenario = {
            "aes_version": 1.2,
            "metadata": {
                "name": f"Generated {capability.replace('_', ' ').title()} Scenario {i}",
                "compliance_level": "Standard"
            },
            "description": tpl["desc_tpl"].format(capability=capability, industry=industry),
            "industry": industry,
            "workflow": {
                "nodes": [
                    {
                        "id": "start_node",
                        "task_description": tpl["task_tpl"].format(capability=capability, industry=industry),
                        "expected_outcome": {
                            "type": "typed_value",
                            "data_type": "string",
                            "value": tpl["expected_tpl"].format(
                                capability=capability,
                                industry=industry,
                                capability_title=capability.title(),
                            )
                        }
                    }
                ],
                "edges": []
            },
            "evaluation": {
                "consensus": {
                    "strategy": "Majority_Vote",
                    "min_judges": 1,
                    "judge_panel": ["Luna-1"]
                }
            }
        }

        # Internal Schema Validation (Fail-Fast)
        try:
            schema_path = Path(__file__).parent.parent / "schemas" / "scenario.schema.json"
            if schema_path.exists():
                with open(schema_path, "r", encoding="utf-8") as sf:
                    schema = json.load(sf)
                jsonschema.validate(instance=scenario, schema=schema)
        except jsonschema.exceptions.ValidationError as ve:
            print(f"❌ Internal Validation Error for {scenario_id}: {ve.message}")
            continue
        except Exception as e:
            print(f"⚠ Warning: Could not perform internal validation: {e}")

        filename = f"{scenario_id}.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(scenario, f, indent=2)
        generated_files.append(filepath)

    print(f"\n✅ Successfully generated {len(generated_files)} scenarios in {output_dir}/")
    for f in generated_files:
        print(f"  - {f.name}")
    print("\nTip: Run these with 'multiagent-eval evaluate --path <path_or_dir>'")


def init_standard(standard_id: str):
    """Initialize a new evaluation environment based on an industrial standard."""
    from . import registry_sync
    registry = registry_sync.load_registry()
    
    # Simple lookup
    standard = None
    for category in registry["industries"].values():
        if standard_id in category["standards"]:
            standard = category["standards"][standard_id]
            break
            
    if not standard:
        raise ValueError(f"Standard '{standard_id}' not found in registry.")

    print(f"🏗️  Initializing environment for standard: {standard['name']} ({standard_id})")
    
    # Create directory structure
    base_dir = Path(f"eval_{standard_id.lower()}")
    base_dir.mkdir(exist_ok=True)
    (base_dir / "scenarios").mkdir(exist_ok=True)
    (base_dir / "docs").mkdir(exist_ok=True)
    
    # Create a readme with the standard description
    with open(base_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(f"# Evaluation Environment: {standard['name']}\n\n")
        f.write(f"**ID:** {standard_id}\n")
        f.write(f"**Industry:** {standard['industry']}\n\n")
        f.write(f"## Description\n{standard['description']}\n\n")
        f.write(f"--- \n*Generated by multiagent-eval init --standard {standard_id}*")
    
    print(f"✅ Created environment at {base_dir}/")


def scaffold_benchmark(dir_path: str, industry: str, protocol: str):
    """Scaffold a new agent evaluation environment."""
    base_dir = Path(dir_path) if dir_path else Path("eval_env")
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate scenarios dir
    scenarios_dir = base_dir / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)
    
    # Save config
    config_data = {
        "industry": industry or "general",
        "agent_api_url": protocol or "http://localhost:5001/execute_task",
    }
    with open(base_dir / "eval_config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)
        
    # Generate starter scenario using v1.2 schema
    starter = {
        "aes_version": 1.2,
        "metadata": {
            "name": "Starter Scenario",
            "compliance_level": "Standard"
        },
        "description": "A basic starter scenario focusing on interaction.",
        "industry": industry or "general",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "Initial interaction test.",
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "string",
                        "value": "Successful execution."
                    }
                }
            ],
            "edges": []
        },
        "evaluation": {
            "consensus": {
                "strategy": "Majority_Vote",
                "min_judges": 1,
                "judge_panel": ["Luna-1"]
            }
        }
    }
    
    with open(scenarios_dir / "starter_scenario.json", "w", encoding="utf-8") as f:
        json.dump(starter, f, indent=4)
        
    print(f"✅ Scaffolded benchmark environment at {base_dir}")


def generate_github_action():
    """Generates a GitHub Actions workflow for the target environment."""
    workflow_path = Path(".github/workflows/eval_harness_ci.yml")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    
    workflow_content = """name: AES Evaluation Harness CI

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install .

      - name: Run Evaluation
        run: |
          multiagent-eval evaluate --path scenarios/
"""
    with open(workflow_path, "w", encoding="utf-8") as f:
        f.write(workflow_content)
    
    print(f"🚀 Created GitHub Actions workflow at {workflow_path}")
    print("✅ CI manifest generated.")


if __name__ == "__main__":
    generate_interactive()
