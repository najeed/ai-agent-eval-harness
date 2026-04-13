from __future__ import annotations

"""
drift_importer.py

Utility to import production traces (JSON) as evaluation scenarios.
"""

import json  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

from .trace_utils import load_events  # noqa: E402


def import_trace_as_scenario(trace_path: Path, industry: str, output_dir: Path) -> Path:
    """
    Reads a production trace and converts it into a v2 scenario JSON.
    """
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    try:
        trace_data = load_events(trace_path)
    except Exception as e:
        raise ValueError(f"Failed to parse trace: {e}")  # noqa: B904

    if isinstance(trace_data, dict):
        history = trace_data.get("history", [])
    else:
        history = trace_data

    if not history:
        raise ValueError("No conversation history found in trace.")

    identifier = f"drift-{uuid.uuid4().hex[:8]}"

    # Create scenario structure (Transition to AES v1.4.0 Identity)
    scenario = {
        "aes_version": 1.4,
        "id": identifier,
        "industry": industry,
        "use_case": "production_replay",
        "metadata": {
            "id": identifier,
            "name": f"Imported Drift: {trace_path.name}",
            "compliance_level": "Standard",
        },
        "description": f"Automatically imported from production trace: {trace_path.name}",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "Replay production trace and verify outcome.",
                    "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.8}],
                }
            ],
            "edges": [],
        },
        "ground_truth_history": history,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{identifier}.json"

    with open(output_file, "w") as f:
        json.dump(scenario, f, indent=2)

    return output_file
