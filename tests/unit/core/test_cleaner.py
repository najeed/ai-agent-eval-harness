from datetime import UTC, datetime, timedelta

from eval_runner.cleaner import cleanup_traces


class FakeRunStore:
    def __init__(self, runs):
        self.runs = runs
        self.deleted = []

    def list_runs(self, *, limit, context=None):
        return self.runs

    def delete_run(self, run_id, *, context=None):
        self.deleted.append(run_id)
        return True


def test_cleanup_traces_non_existent():
    """An empty provider has no expired runs."""
    assert cleanup_traces(run_store=FakeRunStore([]), days=1) == []


def test_cleanup_traces_execution(capsys):
    """Dry runs report expired provider records; force deletes those records."""
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    store = FakeRunStore([{"run_id": "old-run", "created_at": old}])
    assert cleanup_traces(run_store=store, days=7, force=False) == ["old-run"]
    assert "Would remove expired provider run: old-run" in capsys.readouterr().out
    assert store.deleted == []
    assert cleanup_traces(run_store=store, days=7, force=True) == ["old-run"]
    assert store.deleted == ["old-run"]


def test_cleanup_traces_ignores_new(capsys):
    store = FakeRunStore([{"run_id": "new-run", "created_at": datetime.now(UTC).isoformat()}])
    assert cleanup_traces(run_store=store, days=7, force=True) == []
    assert store.deleted == []
    assert capsys.readouterr().out == ""
