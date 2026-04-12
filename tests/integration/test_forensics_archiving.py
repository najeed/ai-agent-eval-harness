from eval_runner.forensics import ForensicCollector


def test_forensic_plugin_archiving(tmp_path):
    run_log_dir = tmp_path / "runs" / "test-run"
    run_log_dir.mkdir(parents=True)

    collector = ForensicCollector("test-run", run_log_dir)

    # Create a dummy plugin
    plugin_path = tmp_path / "my_plugin.py"
    plugin_content = "class MyPlugin: pass"
    plugin_path.write_text(plugin_content)

    # Archive it
    file_hash = collector.archive_plugin(plugin_path)

    # Verify file exists in forensics/plugins
    archived_dir = run_log_dir / "forensics" / "plugins"
    assert archived_dir.exists()

    # Find the file (it has the hash in the name)
    archived_files = list(archived_dir.glob("*.py"))
    assert len(archived_files) == 1
    assert file_hash[:12] in archived_files[0].name

    # Verify content
    assert archived_files[0].read_text() == plugin_content

    # Verify it was registered as an artifact
    ledger = collector.collect()
    # Path in ledger should be relative to forensics target_dir?
    # Current collect() returns ledger with alias as key
    alias = f"plugins/{archived_files[0].name}"
    assert alias in ledger
    assert ledger[alias] == file_hash
