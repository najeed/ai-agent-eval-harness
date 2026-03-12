from __future__ import annotations
"""
drift_importer.py

Utility to import production traces (JSON) as evaluation scenarios.
"""

import json
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

def import_trace_as_scenario(trace_path: Path, industry: str, output_dir: Path) -> Path:
    """
    Reads a production trace and converts it into a v2 scenario JSON.
    """
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    try:
        with open(trace_path, "r") as f:
            content = f.read().strip()
            if not content:
                raise ValueError("Trace file is empty.")
            
            # Support both standard JSON and JSONL (one object per line)
            lines = content.splitlines()
            if len(lines) > 1:
                # Assume JSONL
                trace_data = [json.loads(line) for line in lines if line.strip()]
            else:
                # Assume standard JSON
                trace_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse trace as JSON/JSONL: {e}")

    if isinstance(trace_data, dict):
        history = trace_data.get("history", [])
    else:
        history = trace_data
    
    if not history:
        if isinstance(trace_data, list):
            history = trace_data
        else:
            raise ValueError("No conversation history found in trace.")

    scenario_id = f"drift-{uuid.uuid4().hex[:8]}"
    
    # Create scenario structure
    scenario = {
        "scenario_id": scenario_id,
        "version": "2.0.0",
        "title": f"Imported Drift: {trace_path.name}",
        "industry": industry,
        "use_case": "production_replay",
        "core_function": "drift_management",
        "description": f"Automatically imported from production trace: {trace_path.name}",
        "tasks": [
            {
                "task_id": "imported_task_1",
                "description": "Replay production trace and verify outcome.",
                "expected_outcome": "Outcome matches production ground truth (if provided).",
                "required_tools": [], # To be filled by user if needed
                "success_criteria": [
                    {"metric": "generic_accuracy", "threshold": 0.5}
                ]
            }
        ],
        "ground_truth_history": history # Store the original trace for comparison
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{scenario_id}.json"
    
    with open(output_file, "w") as f:
        json.dump(scenario, f, indent=2)

    return output_file
