import os
import json
from pathlib import Path
from .linter import ScenarioLinter
from . import loader
from . import mutator

class ContributeWizard:
    """Guided wizard for creating and contributing new agent scenarios."""

    @staticmethod
    def run():
        print("\n" + "=" * 60)
        print(f"{'🚀 AI AGENT HARNESS: CONTRIBUTION WIZARD':^60}")
        print("=" * 60)
        print("This wizard will help you build a high-quality evaluation scenario.\n")

        # 1. Scaffolding
        title = input("1. Enter Scenario Title (e.g., 'Return Policy Inquiries'): ").strip()
        industry = input("2. Enter Industry (e.g., 'retail', 'finance', 'telecom'): ").strip() or "generic"
        
        scenario_id = title.lower().replace(" ", "-")
        filename = f"{scenario_id}.json"
        target_dir = Path("industries") / industry / "scenarios"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename

        print(f"\n[Scaffold] Creating {filename}...")
        stub = {
            "scenario_id": scenario_id,
            "title": title,
            "description": f"Evaluation for {title} in the {industry} industry.",
            "industry": industry,
            "use_case": "Customer Support",
            "core_function": "Inquiry Handling",
            "complexity_level": "medium",
            "tasks": [
                {
                    "task_id": "test-1",
                    "description": "User asks a basic question about...",
                    "expected_outcome": "Agent provides a clear, accurate answer...",
                    "success_criteria": ["Accuracy", "Clarity"],
                    "tools": []
                }
            ]
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(stub, f, indent=2)

        # 2. Linting & Quality Check
        print("\n" + "-" * 60)
        print(f"{'🔍 QUALITY TICKETING':^60}")
        print("-" * 60)
        linter = ScenarioLinter()
        report = linter.lint(str(target_path))
        
        print(f"File:  {target_path}")
        print(f"Score: {report['score']}/100")
        print(f"Tier:  {report['tier']}")
        
        if report['tier'] != "GOLD":
            print("\n[TIP] To reach GOLD tier, ensure all tasks have success_criteria and complexity_level is set.")
            for warn in report.get('warnings', []):
                print(f"  ⚠ {warn}")

        # 3. Mutation Pack (Optional)
        do_mutate = input("\nWould you like to generate adversarial variants (typos, injections)? (y/N): ").strip().lower()
        if do_mutate == 'y':
            print("[Mutator] Generating typo variant...")
            mutated = mutator.mutate_scenario(stub, "typo")
            mutated_path = target_path.parent / f"{target_path.stem}_typo.json"
            mutator.save_mutated_scenario(mutated, mutated_path)
            print(f"   -> Saved to {mutated_path.name}")

        # 4. PR Instructions
        print("\n" + "=" * 60)
        print(f"{'🏁 NEXT STEPS':^60}")
        print("=" * 60)
        print(f"1. Open {target_path} and fill in the 'tasks' section.")
        print("2. Run 'eval-harness lint scenarios/' to verify again.")
        print(f"3. Run 'git checkout -b contrib/{scenario_id}'")
        print("4. Commit and push your changes to GitHub.")
        print("5. Open a Pull Request! We appreciate your contribution.")
        print("=" * 60 + "\n")
