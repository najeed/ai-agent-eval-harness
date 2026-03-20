# eval_runner/exporter.py
import json
from pathlib import Path
from typing import List, Dict, Any
from .trace_utils import load_events


class HFExporter:
    """Logic for mapping internal run.jsonl traces to HuggingFace Dataset schemas."""

    @staticmethod
    def export(trace_path: str, output_path: str):
        """Converts a run.jsonl file into a HF-compatible JSON dataset with canonical metadata."""
        import subprocess

        print(f"      [Exporter] Converting {trace_path} to HuggingFace format...")

        # Capture environment metadata
        try:
            commit = (
                subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
                .decode()
                .strip()
            )
        except:
            commit = "unknown"

        canonical_meta = {
            "harness_version": "1.2.0-opencore",
            "commit": commit,
            "export_timestamp": (
                Path(trace_path).stat().st_mtime if Path(trace_path).exists() else None
            ),
            "schema_version": "1.0",
        }

        hf_dataset = []
        path = Path(trace_path)
        if not path.exists():
            print(f"      [Exporter] Error: Trace file {trace_path} not found.")
            return

        try:
            events = load_events(path)
            for event in events:
                hf_dataset.append(
                    {
                        "event_type": event.get("event"),
                        "timestamp": event.get("timestamp"),
                        "payload": event.get("payload", {}),
                        "meta": canonical_meta,
                    }
                )
        except Exception as e:
            print(f"      [Exporter] Error: Failed to load events: {e}")
            return

        with open(output_path, "w") as f:
            json.dump(hf_dataset, f, indent=2)
            print(f"      [Exporter] Success! Dataset saved to {output_path}")

    @staticmethod
    def push_to_hf(dataset_path: str, repo_id: str):
        """Pushes a dataset to HuggingFace Hub using huggingface_hub SDK."""
        print(
            f"      [Exporter] Preparing to push {dataset_path} to HF Hub: {repo_id}..."
        )

        try:
            from huggingface_hub import HfApi

            api = HfApi()

            # Check if dataset exists
            path = Path(dataset_path)
            if not path.exists():
                print(f"      [Exporter] Error: {dataset_path} not found.")
                return

            print(f"      [Exporter] Uploading {path.name} to {repo_id}...")
            api.upload_file(
                path_or_fileobj=str(path),
                path_in_repo=path.name,
                repo_id=repo_id,
                repo_type="dataset",
            )
            print(
                f"      [Exporter] Success! Dataset pushed to https://huggingface.co/datasets/{repo_id}"
            )

        except ImportError:
            print("      [Exporter] Error: 'huggingface_hub' SDK not found.")
            print(
                "      [HINT] Run 'pip install huggingface_hub' and 'huggingface-cli login' to enable this feature."
            )
        except Exception as e:
            print(f"      [Exporter] Failed to push to HF Hub: {e}")
            if "not logged in" in str(e).lower() or "unauthorized" in str(e).lower():
                print(
                    "      [HINT] Please run 'huggingface-cli login' to authenticate."
                )
