from __future__ import annotations

"""
spec_parser.py

Utility for parsing Markdown PRDs into validated JSON scenario stubs for the MultiAgentEval.
"""

import re
import json
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from . import config
from .llm_providers import GeminiProvider


def parse_markdown_to_scenario(markdown_text: str) -> Dict[str, Any]:
    """
    Parses a structured Markdown PRD into a scenario JSON object using section splitting.
    """

    scenario: Dict[str, Any] = {
        "aes_version": 1.2,
        "metadata": {
            "id": f"scenario-{uuid.uuid4().hex[:8]}",
            "compliance_level": "Standard",
        },
        "description": "",
        "industry": "general",
        "workflow": {
            "nodes": [],
            "edges": [],
        },
    }

    # 1. Extract Title (H1)
    title_match = re.search(r"^#\s+(?:PRD:\s*)?(.*)", markdown_text, re.MULTILINE | re.IGNORECASE)
    if title_match:
        scenario["metadata"]["name"] = title_match.group(1).strip()

    # 2. Extract Metadata (Industry, Use Case, Core Function)
    industry_match = re.search(r"\*\*Industry:\*\*\s*(.*)", markdown_text, re.IGNORECASE)
    if industry_match:
        scenario["industry"] = industry_match.group(1).strip()

    use_case_match = re.search(r"\*\*Use Case:\*\*\s*(.*)", markdown_text, re.IGNORECASE)
    if use_case_match:
        scenario["use_case"] = use_case_match.group(1).strip()

    core_func_match = re.search(r"\*\*Core Function:\*\*\s*(.*)", markdown_text, re.IGNORECASE)
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
        elif "tasks" in header or "test cases" in header:
            # First, check if there are actual ### headers defined
            if "###" in body:
                # Find all H3 headers in the tasks section
                task_headers = list(re.finditer(r"^###\s+(?:\d+\.\s*)?(.*)", body, re.MULTILINE))
                for i, match in enumerate(task_headers):
                    task_title = match.group(1).strip()
                    start_pos = match.end()
                    end_pos = task_headers[i + 1].start() if i + 1 < len(task_headers) else len(body)

                    task_body = body[start_pos:end_pos].strip()
                    
                    # Metadata Stripping: Extract (Expect: ...) or (Goal: ...)
                    expect_match = re.search(r"\((?:Expect|Goal):\s*(.*?)\)", task_body, re.IGNORECASE)
                    expected_outcome = expect_match.group(1).strip() if expect_match else None
                    if expect_match:
                        task_body = task_body.replace(expect_match.group(0), "").strip()

                    node = {
                        "id": f"task-{len(scenario['workflow']['nodes']) + 1}",
                        "title": task_title,
                        "task_description": task_body or task_title,
                    }
                    if expected_outcome:
                        node["expected_outcome"] = {
                            "type": "typed_value",
                            "data_type": "string",
                            "value": expected_outcome
                        }
                    scenario["workflow"]["nodes"].append(node)
                    # Simple linear edges by default from parser
                    if len(scenario["workflow"]["nodes"]) > 1:
                        scenario["workflow"]["edges"].append({
                            "from": scenario["workflow"]["nodes"][-2]["id"],
                            "to": node["id"]
                        })
            else:
                # Fallback: Try to parse as bullet points if no H3 found
                bullet_tasks = re.findall(r"^\s*-\s*(.*)", body, re.MULTILINE)
                if bullet_tasks:
                    for i, task_text in enumerate(bullet_tasks):
                        # Strip (Expect: ...) from bullet points too
                        expect_match = re.search(r"\((?:Expect|Goal):\s*(.*?)\)", task_text, re.IGNORECASE)
                        expected_outcome = expect_match.group(1).strip() if expect_match else None
                        if expect_match:
                             task_text = task_text.replace(expect_match.group(0), "").strip()

                        node = {
                            "id": f"task-{len(scenario['workflow']['nodes']) + 1}",
                            "task_description": task_text,
                        }
                        if expected_outcome:
                            node["expected_outcome"] = {
                                "type": "typed_value",
                                "data_type": "string",
                                "value": expected_outcome
                            }
                        scenario["workflow"]["nodes"].append(node)
                        if i > 0:
                            scenario["workflow"]["edges"].append({
                                "from": scenario["workflow"]["nodes"][-2]["id"],
                                "to": node["id"]
                            })
                else:
                    # No structured tasks found - trigger LLM synthesis for real implementation
                    import asyncio
                    try:
                        synthesized = asyncio.run(synthesize_tasks_from_prd(markdown_text))
                        for i, task in enumerate(synthesized):
                            node = {
                                "id": task.get("task_id") or f"task-{len(scenario['workflow']['nodes']) + 1}",
                                "title": task.get("title") or "Synthesized Task",
                                "task_description": task.get("description") or task.get("title") or "No description",
                                "required_tools": task.get("required_tools", []),
                                "success_criteria": task.get("success_criteria", [])
                            }
                            if task.get("expected_outcome"):
                                node["expected_outcome"] = {
                                    "type": "typed_value",
                                    "data_type": "string",
                                    "value": str(task.get("expected_outcome"))
                                }
                            scenario["workflow"]["nodes"].append(node)
                            if len(scenario["workflow"]["nodes"]) > 1:
                                scenario["workflow"]["edges"].append({
                                    "from": scenario["workflow"]["nodes"][-2]["id"],
                                    "to": node["id"]
                                })
                    except Exception as e:
                        print(f"   [SpecParser] Critical: LLM Synthesis failed and no manual tasks found: {e}")
                        # Fallback to a single empty node to keep the scenario valid
                        scenario["workflow"]["nodes"].append({
                            "id": "task-1",
                            "task_description": "Initial task (Generated as fallback)",
                        })
        elif "topology" in header:
            topology = {}
            for t_line in lines[1:]:
                cl = t_line.strip()
                name_match = re.search(r"\*\*(.*?):\*\*", cl)
                if not name_match:
                    continue
                agent = name_match.group(1).strip()

                writes = []
                w_match = re.search(r"writes to\s*[:\s]*[\[\"']*(.*?)(?=[\]\"']*\.|\s*\]|$)", cl)
                if w_match:
                    writes = [w.strip(" `\"[]") for w in w_match.group(1).split(",")]

                reads = []
                r_match = re.search(r"reads from\s*[:\s]*[\[\"']*(.*?)(?=[\]\"']*\.|\s*\]|$)", cl)
                if r_match:
                    reads = [r.strip(" `\"[]") for r in r_match.group(1).split(",")]

                topology[agent] = {
                    "writes": [w for w in writes if w],
                    "reads": [r for r in reads if r],
                }
            if topology:
                scenario["metadata"]["agent_topology"] = topology
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
                scenario["metadata"]["policies"] = policies

    return scenario


async def synthesize_tasks_from_prd(markdown_text: str) -> List[Dict[str, Any]]:
    """
    Uses an LLM to derive high-fidelity test tasks from PRD business rules.
    """
    print(f"   [SpecParser] Starting LLM synthesis...")
    try:
        # Use our internal provider for consistency and reliability
        api_key = config.GOOGLE_API_KEY
        # Fallback to env directly if config is not yet loaded or overridden
        if not api_key:
             import os
             api_key = os.environ.get("GOOGLE_API_KEY")

        if not api_key:
             print("   [SpecParser] Error: GOOGLE_API_KEY not found in config or environment.")
             return []

        model_name = config.GEMINI_MODEL or "gemini-2.5-flash"
        provider = GeminiProvider(api_key=api_key, model=model_name)
        
        print(f"   [SpecParser] Initializing Gemini ({model_name}) via Native Provider...")
        
        prompt = f"""
        Extract evaluation tasks from the following PRD. 
        If no tasks are explicitly listed, derive a balanced set of 3-5 tasks based on 'Business Rules' and 'Tools'.
        Include:
        1. At least one Positive case (successful flow).
        2. At least one Negative case (rejected or manual review flow).
        3. At least one Adversarial case (attempt to bypass security/policy).

        PRD:
        {markdown_text}

        Return ONLY a JSON list of tasks following this schema:
        [
          {{
            "task_id": "task-1",
            "title": "...",
            "description": "...",
            "expected_outcome": "...",
            "required_tools": ["tool_names", "..."],
            "success_criteria": [{{"metric": "...", "threshold": 0.8}}]
          }}
        ]
        """
        
        # Native provider uses async generate
        content = await provider.generate(prompt, temperature=0.1)
        
        print(f"   [SpecParser] LLM Response received. Parsing JSON...")
        
        # Extract JSON from potential markdown block
        content = content.strip()
        if "```json" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
        
        tasks = json.loads(content)
        return tasks
    except Exception as e:
        print(f"   [SpecParser] Warning: LLM Task Synthesis failed - {e}")
        return []


def save_scenario_json(scenario: Dict[str, Any], output_path: Path):
    """Saves the scenario object to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=4)
    print(f"   [SpecParser] Stub saved to: {output_path}")

# Backward compatibility alias
save_scenario_stub = save_scenario_json
