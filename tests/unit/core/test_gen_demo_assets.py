"""
test_gen_demo_assets.py

Unit tests for the generate_assets utility.
Verifies file generation and timestamp shifting for demo traces.
"""

from eval_runner.console import gen_demo_assets


def test_generate_assets_success(tmp_path):
    """Verifies that demo assets are created through the run store provider."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_store = LocalFileRunStore(runs_dir)

    gen_demo_assets.generate_assets(run_store=run_store)

    runs = run_store.list_runs()
    assert len(runs) > 0

    first_run = runs[0]
    events = run_store.get_events(first_run["run_id"])
    assert len(events) > 0
    assert "timestamp" in events[0]
    assert "event" in events[0]
