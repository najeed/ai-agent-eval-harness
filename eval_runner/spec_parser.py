from __future__ import annotations

"""
spec_parser.py

Utility for parsing Markdown PRDs into validated JSON scenario stubs for the AI Agent Evaluation Harness.
"""

import re
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List


def parse_markdown_to_scenario(markdown_text: str) -> Dict[str, Any]:
    """
    Parses a structured Markdown PRD into a scenario JSON object using section splitting.
    """

    scenario: Dict[str, Any] = {
        "scenario_id": f"scenario-{uuid.uuid4().hex[:8]}",
        "version": "2.0.0",
        "tasks": [],
    }

    # 1. Extract Title (H1)
    title_match = re.search(
        r"^#\s+(?:PRD:\s*)?(.*)", markdown_text, re.MULTILINE | re.IGNORECASE
    )
    if title_match:
        scenario["title"] = title_match.group(1).strip()

    # 2. Extract Metadata (Industry, Use Case, Core Function)
    industry_match = re.search(
        r"\*\*Industry:\*\*\s*(.*)", markdown_text, re.IGNORECASE
    )
    if industry_match:
        scenario["industry"] = industry_match.group(1).strip()

    use_case_match = re.search(
        r"\*\*Use Case:\*\*\s*(.*)", markdown_text, re.IGNORECASE
    )
    if use_case_match:
        scenario["use_case"] = use_case_match.group(1).strip()

    core_func_match = re.search(
        r"\*\*Core Function:\*\*\s*(.*)", markdown_text, re.IGNORECASE
    )
    if core_func_match:
        scenario["core_function"] = core_func_match.group(1).strip()

    # 3. Split into sections by H2
    sections = re.split(r"^##\s+", markdown_text, flags=re.MULTILINE)

    for section in sections:
        lines = section.strip().split("\n")
        if not lines:
            continue
        header = lines[0].lower().strip()
        body = "\n".join(lines[1:]).strip()

        if "overview" in header:
            scenario["description"] = body
        elif "tasks" in header:
            # Find all H3 headers in the tasks section (numbered or unnumbered)
            task_headers = list(
                re.finditer(r"^###\s+(?:\d+\.\s*)?(.*)", body, re.MULTILINE)
            )
            for i, match in enumerate(task_headers):
                task_title = match.group(1).strip()
                start_pos = match.end()
                end_pos = (
                    task_headers[i + 1].start()
                    if i + 1 < len(task_headers)
                    else len(body)
                )

                task_body = body[start_pos:end_pos].strip()
                t_lines = task_body.split("\n")

                expected_outcome = ""
                tools = []
                criteria = []
                final_desc = []

                for t_line in t_lines:
                    cl = t_line.strip()
                    if not cl:
                        continue
                    if "**Expected Outcome:**" in cl:
                        expected_outcome = cl.split("**Expected Outcome:**")[-1].strip()
                    elif "**Tools:**" in cl:
                        t_str = cl.split("**Tools:**")[-1].strip()
                        tools = [
                            t.strip().strip("`").strip("[]").strip('"')
                            for t in t_str.split(",")
                        ]
                    elif "**Criteria:**" in cl:
                        c_str = cl.split("**Criteria:**")[-1].strip()
                        c_match = re.search(r"([a-zA-Z_]+)(?:\s*\((.*)\))?", c_str)
                        if c_match:
                            m_name = c_match.group(1).strip()
                            thr = 0.5
                            if c_match.group(2):
                                f_match = re.search(r"(\d+\.?\d*)", c_match.group(2))
                                if f_match:
                                    thr = float(f_match.group(1))
                            criteria.append({"metric": m_name, "threshold": thr})
                    else:
                        final_desc.append(cl)

                scenario["tasks"].append(
                    {
                        "task_id": f"task-{len(scenario['tasks']) + 1}",
                        "title": task_title,
                        "description": "\n".join(final_desc).strip(),
                        "expected_outcome": expected_outcome,
                        "required_tools": tools,
                        "success_criteria": criteria
                        or [{"metric": "generic_accuracy", "threshold": 0.5}],
                    }
                )
        elif "topology" in header:
            topology = {}
            for t_line in lines[1:]:
                cl = t_line.strip()
                name_match = re.search(r"\*\*(.*?):\*\*", cl)
                if not name_match:
                    continue
                agent = name_match.group(1).strip()

                writes = []
                w_match = re.search(
                    r"writes to\s*[`\[\]\"']*(.*?)[`\[\]\"']*(?:,|$|\.|\s)", cl
                )
                if w_match:
                    writes = [
                        w.strip().strip("`").strip('"')
                        for w in w_match.group(1).split(",")
                    ]

                reads = []
                r_match = re.search(
                    r"reads from\s*[`\[\]\"']*(.*?)[`\[\]\"']*(?:,|$|\.|\s)", cl
                )
                if r_match:
                    reads = [
                        r.strip().strip("`").strip('"')
                        for r in r_match.group(1).split(",")
                    ]

                topology[agent] = {
                    "writes": [w for w in writes if w],
                    "reads": [r for r in reads if r],
                }
            if topology:
                scenario["agent_topology"] = topology
        elif "policies" in header:
            policies = {}
            for p_line in lines[1:]:
                cl = p_line.strip()
                match = re.search(r"-\s*\*\*(.*?):\*\*\s*(.*)", cl)
                if match:
                    p_name = match.group(1).strip()
                    p_val_str = match.group(2).strip()
                    # Try to parse as JSON if it looks like a dict
                    try:
                        p_val = json.loads(p_val_str.replace("'", '"'))
                    except:
                        p_val = {"max_limit": 100}  # Default
                    policies[p_name] = p_val
            if policies:
                scenario["policies"] = policies

    return scenario


def save_scenario_stub(scenario: Dict[str, Any], output_path: Path):
    """Saves the scenario object to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=2)
    print(f"   [SpecParser] Scenario stub saved to: {output_path}")
