# eval_runner/exporter.py
import json
from pathlib import Path
from typing import List, Dict, Any

class HFExporter:
    """Logic for mapping internal run.jsonl traces to HuggingFace Dataset schemas."""
    
    @staticmethod
    def export(trace_path: str, output_path: str):
        """Converts a run.jsonl file into a HF-compatible JSON dataset."""
        print(f"      [Exporter] Converting {trace_path} to HuggingFace format...")
        
        hf_dataset = []
        path = Path(trace_path)
        if not path.exists():
            print(f"      [Exporter] Error: Trace file {trace_path} not found.")
            return

        with open(path, "r") as f:
            for line in f:
                event = json.loads(line)
                # Map internal events to HF schema segments
                # For v1.0 RC, we just wrap the event in a standard 'data' field
                hf_dataset.append({
                    "event_type": event.get("event"),
                    "timestamp": event.get("timestamp"),
                    "payload": event.get("payload", {})
                })

        with open(output_path, "w") as f:
            json.dump(hf_dataset, f, indent=2)
            print(f"      [Exporter] Success! Dataset saved to {output_path}")
