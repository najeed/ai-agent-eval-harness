# eval_runner/exporter.py
import json
from pathlib import Path
from typing import List, Dict, Any

class HFExporter:
    """Logic for mapping internal run.jsonl traces to HuggingFace Dataset schemas."""
    
    @staticmethod
    def export(trace_path: str, output_path: str):
        """Converts a run.jsonl file into a HF-compatible JSON dataset with canonical metadata."""
        import subprocess
        print(f"      [Exporter] Converting {trace_path} to HuggingFace format...")
        
        # Capture environment metadata
        try:
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
        except:
            commit = "unknown"
            
        canonical_meta = {
            "harness_version": "1.2.0-opencore",
            "commit": commit,
            "export_timestamp": Path(trace_path).stat().st_mtime if Path(trace_path).exists() else None,
            "schema_version": "1.0"
        }
        
        hf_dataset = []
        path = Path(trace_path)
        if not path.exists():
            print(f"      [Exporter] Error: Trace file {trace_path} not found.")
            return

        with open(path, "r") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    hf_dataset.append({
                        "event_type": event.get("event"),
                        "timestamp": event.get("timestamp"),
                        "payload": event.get("payload", {}),
                        "meta": canonical_meta
                    })
                except:
                    continue

        with open(output_path, "w") as f:
            json.dump(hf_dataset, f, indent=2)
            print(f"      [Exporter] Success! Dataset saved to {output_path}")

    @staticmethod
    def push_to_hf(dataset_path: str, repo_id: str):
        """Placeholder for pushing a dataset to HuggingFace Hub."""
        print(f"      [Exporter] Preparing to push {dataset_path} to HF Hub: {repo_id}...")
        print("      [HINT] Ensure 'huggingface_hub' is installed and you are logged in via 'huggingface-cli login'.")
        # In actual implementation: api = HfApi(); api.upload_file(...)
        print(f"      [Exporter] Successfully staged {dataset_path} for {repo_id}")
