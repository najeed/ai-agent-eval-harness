import json
import os
from pathlib import Path

def generate_interactive():
    """Interactive prompt to generate scenarios."""
    print("\n✨ AI Agent Eval Harness - Scenario Generator\n")
    
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
            "expected_tpl": "Successfully handled {capability}."
        },
        {
            "desc_tpl": "Edge-case validation for {capability} workflows within the {industry} sector.",
            "task_tpl": "Simulate a complex {capability} interaction. Ensure the agent follows standard {industry} protocols.",
            "expected_tpl": "{capability.title()} processed with full audit trails."
        },
        {
            "desc_tpl": "Adversarial robustness check: {capability} under high-load/ambiguous conditions.",
            "task_tpl": "The user provides minimal info for {capability}. The agent must clarify and then execute.",
            "expected_tpl": "Agent clarifies request and completes {capability} correctly."
        }
    ]

    generated_files = []
    for i in range(1, count + 1):
        tpl = templates[(i-1) % len(templates)]
        scenario_id = f"gen_{industry}_{capability.replace(' ', '_')}_{i}"
        scenario = {
            "scenario_id": scenario_id,
            "title": f"Generated {capability.replace('_', ' ').title()} Scenario {i}",
            "description": tpl["desc_tpl"].format(capability=capability, industry=industry),
            "industry": industry,
            "tasks": [
                {
                    "task_id": f"task_{i}",
                    "description": tpl["task_tpl"].format(capability=capability, industry=industry),
                    "expected_output": tpl["expected_tpl"].format(capability=capability, industry=industry),
                    "requirements": [
                        {"type": "mandatory", "description": f"Call the appropriate {capability} tool."}
                    ],
                    "metrics": [
                        {"metric": "success_rate", "threshold": 1.0}
                    ]
                }
            ]
        }
        
        filename = f"{scenario_id}.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(scenario, f, indent=2)
        generated_files.append(filepath)

    print(f"\n✅ Successfully generated {len(generated_files)} scenarios in {output_dir}/")
    for f in generated_files:
        print(f"  - {f.name}")
    print("\nTip: Run these with 'eval-harness run <path>'")

if __name__ == "__main__":
    generate_interactive()
