import os
import json
from pathlib import Path
from eval_runner.artifact_plugin import ArtifactPlugin

def test_signing():
    plugin = ArtifactPlugin()
    tmp_dir = Path(".tmp/test_signing")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    test_file = tmp_dir / "test.txt"
    test_file.write_text("Hello compliance world!")
    
    print("Testing bundle creation with signing...")
    result = plugin.bundle_artifacts(
        target_dir=str(tmp_dir),
        files_to_include=["test.txt"],
        output_filename="test_bundle.zip"
    )
    
    manifest_path = Path(result["manifest_path"])
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
        
    print(f"Manifest keys: {list(manifest.keys())}")
    if "signature_ed25519" in manifest:
        print("✅ Signature found in manifest.")
        print(f"Signature: {manifest['signature_ed25519'][:20]}...")
    else:
        print("❌ Signature missing from manifest.")

if __name__ == "__main__":
    test_signing()
