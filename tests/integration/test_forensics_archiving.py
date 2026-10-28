from eval_runner.forensics import ForensicCollector
from eval_runner.reference.local_artifact import LocalFileArtifactStore


def test_forensic_plugin_archiving(tmp_path):
    store = LocalFileArtifactStore(base_dir=tmp_path / "artifact-store")
    collector = ForensicCollector("test-run", artifact_store=store)

    # Create a dummy plugin
    plugin_path = tmp_path / "my_plugin.py"
    plugin_content = "class MyPlugin: pass"
    plugin_path.write_text(plugin_content)

    # Archive it
    file_hash = collector.archive_plugin(plugin_path)

    # Verify file exists in forensics/plugins
    archived_name = f"plugins/{plugin_path.stem}.{file_hash[:12]}.py"
    assert store.get_artifact("test-run", f"forensics/{archived_name}") == plugin_content.encode()

    # Verify it was registered as an artifact
    ledger = collector.collect()
    # Path in ledger should be relative to forensics target_dir?
    # Current collect() returns ledger with alias as key
    assert archived_name in ledger
    assert ledger[archived_name] == file_hash
