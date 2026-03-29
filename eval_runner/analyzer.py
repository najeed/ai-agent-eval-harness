"""
analyzer.py

Logic for scanning agent repositories to identify tools, endpoints, and patterns.
"""

import re
import json
from pathlib import Path


async def analyze_repo(repo_url: str) -> list:
    """
    Scans a repository (simulated) to identify agentic patterns and scaffold AES scenarios.
    For the demo, we simulate scanning the local project or a mock structure.
    """
    # Patterns to look for
    patterns = {
        "tool_definition": r"@tool|def .*_tool\(",
        "api_endpoint": r"@app\.route\(['\"]/api/.*['\"]|@bp\.route\(['\"]/api/.*['\"]",
        "agent_init": r"Agent\(|AgentExecutor\(|initialize_agent\(",
        "llm_call": r"openai\.|anthropic\.|ChatOpenAI\(",
    }

    found_patterns = []

    # In a real implementation, we would clone the repo and scan it.
    # For this demo, we'll return a set of discovered patterns.

    if "telecom" in repo_url.lower():
        found_patterns = [
            {
                "type": "api_endpoint",
                "match": "/api/v1/billing",
                "file": "app/billing.py",
            },
            {
                "type": "tool_definition",
                "match": "def refund_tool()",
                "file": "tools/support.py",
            },
        ]
    elif "finance" in repo_url.lower():
        found_patterns = [
            {
                "type": "llm_call",
                "match": "ChatOpenAI(model='gpt-4')",
                "file": "agent/core.py",
            },
            {
                "type": "tool_definition",
                "match": "def ticker_tool()",
                "file": "tools/market.py",
            },
        ]
    else:
        found_patterns = [
            {"type": "agent_init", "match": "AgentExecutor(...)", "file": "main.py"},
        ]

    # Scaffold scenarios based on patterns
    output_dir = Path("scenarios/auto")
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = []
    for i, pattern in enumerate(found_patterns):
        scenario_id = f"auto_{pattern['type']}_{i}"
        scenario = {
            "aes_version": 1.2,
            "metadata": {
                "id": scenario_id,
                "name": f"Auto-generated for {pattern['match']}",
                "source_file": pattern["file"],
                "pattern": pattern["match"],
            },
            "description": f"Verification of {pattern['type']} discovered in {pattern['file']}",
            "industry": "auto",
            "workflow": {
                "nodes": [
                    {
                        "id": "t1",
                        "task_description": f"Interact with {pattern['match']} and verify its output.",
                    }
                ],
                "edges": [],
            },
        }

        with open(output_dir / f"{scenario_id}.json", "w") as f:
            json.dump(scenario, f, indent=2)
        scenarios.append(scenario)

    return scenarios
