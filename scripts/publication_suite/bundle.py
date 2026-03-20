"""
bundle.py

Regulatory Export Utility.
Creates a signed ZIP artifact bundle with SHA-256 manifest.
"""

import argparse
import sys
import os
from pathlib import Path

# Add project root to sys.path to access eval_runner
project_root = Path(__file__).parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from eval_runner.plugins import manager
from eval_runner.artifact_plugin import ArtifactPlugin


class Bundler:
    def __init__(self, batch_dir: str):
        self.batch_dir = Path(batch_dir)
        # Ensure plugins are loaded so we can find the service
        manager.load_plugins()

    def create_bundle(self):
        print(f"📦 [Bundler CLI] Targeting batch: {self.batch_dir.name}")

        # Locate the ArtifactPlugin instance
        artifact_svc = next(
            (p for p in manager.plugins if isinstance(p, ArtifactPlugin)), None
        )

        if not artifact_svc:
            print("❌ [Bundler CLI] Error: ArtifactPlugin not found in core.")
            return

        targets = [
            "aggregated_results.json",
            "leaderboard.html",
            "pilot_preview.html",
            "manifest.json",
        ]

        # Leverage the CORE capability instead of local logic
        result = artifact_svc.bundle_artifacts(
            target_dir=str(self.batch_dir), files_to_include=targets
        )

        if result["status"] == "success":
            print(
                f"✅ [Bundler CLI] Core-powered bundle created: {result['bundle_path']}"
            )
        else:
            print(f"❌ [Bundler CLI] Failure: {result.get('message')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_dir", help="Directory of the result batch")
    args = parser.parse_args()

    bundler = Bundler(args.batch_dir)
    bundler.create_bundle()
