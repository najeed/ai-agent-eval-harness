"""
verify_features.py

Manually/Automated verification of core harness features.
Generates a capability matrix for publication.
"""

import subprocess
import json
from pathlib import Path

FEATURES = [
    {
        "id": "metric_calc",
        "name": "Metric Calculation",
        "cmd": [
            "python",
            "-m",
            "eval_runner.cli",
            "evaluate",
            "--path",
            "scenarios/starter_scenario.json",
            "--limit",
            "1",
        ],
    },
    {
        "id": "triage_tagging",
        "name": "Triage Heuristics",
        "cmd": [
            "python",
            "-m",
            "eval_runner.cli",
            "explain",
            "reports/latest_results.jsonl",
        ],
    },
    {
        "id": "sandbox_isolation",
        "name": "Tool Sandbox Isolation",
        "cmd": ["python", "-m", "pytest", "tests/test_tool_sandbox.py"],
    },
    {
        "id": "publication_plugin",
        "name": "Publication Export",
        "cmd": [
            "python",
            "-m",
            "eval_runner.cli",
            "evaluate",
            "--path",
            "scenarios/starter_scenario.json",
            "--pilot",
        ],
    },
]


def verify():
    print("=" * 60)
    print(" MultiAgentEval - FEATURE VERIFICATION SUITE")
    print("=" * 60)

    matrix = []

    for feature in FEATURES:
        print(f"\n[Verifying] {feature['name']}...")
        try:
            res = subprocess.run(
                feature["cmd"], capture_output=True, text=True, timeout=30
            )
            status = "PASS" if res.returncode == 0 else "FAIL"
            print(f"   -> Result: {status}")
            if status == "FAIL":
                print(f"   [Error] {res.stderr[:200]}")
        except Exception as e:
            status = "ERROR"
            print(f"   -> Error: {e}")

        matrix.append(
            {"feature": feature["name"], "status": status, "id": feature["id"]}
        )

    output_path = Path("reports/capability_matrix.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(matrix, f, indent=2)

    print("\n" + "=" * 60)
    print(f" Verification Complete. Capability matrix saved to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    verify()
