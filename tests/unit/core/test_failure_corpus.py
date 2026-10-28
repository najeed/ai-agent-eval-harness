"""Failure-corpus searches operate on the caller's run provider."""

from eval_runner import failure_corpus


class FakeRunStore:
    def __init__(self, events_by_run):
        self.events_by_run = events_by_run

    def list_runs(self, *, limit, context=None):
        return [{"run_id": run_id} for run_id in self.events_by_run]

    def get_events(self, run_id, *, offset, limit, context=None):
        return self.events_by_run[run_id]


def test_search_no_matching_events(capsys):
    failure_corpus.search("anything", run_store=FakeRunStore({}))
    assert "No matching failures" in capsys.readouterr().out


def test_search_regex_match(capsys):
    store = FakeRunStore(
        {
            "run-001": [
                {
                    "run_id": "run-001",
                    "event": "TURN_FAIL",
                    "status": "failure",
                    "triage_tag": "TOOL_ERROR",
                }
            ],
            "run-002": [{"run_id": "run-002", "event": "TURN_PASS", "status": "success"}],
        }
    )
    failure_corpus.search("TOOL.+", run_store=store)
    output = capsys.readouterr().out
    assert "Found 1 matching" in output
    assert "run-001" in output


def test_search_multiterm_overflow_and_invalid_regex_fallback(capsys):
    store = FakeRunStore(
        {
            "run": [
                {"event": "TURN_FAIL", "status": "failure", "triage_tag": "[invalid"}
                for _ in range(15)
            ]
        }
    )
    failure_corpus.search("failure", run_store=store)
    assert "... and 5 more" in capsys.readouterr().out
    failure_corpus.search("[invalid", run_store=store)
    assert "Found 15 matching" in capsys.readouterr().out


def test_search_multiterm_requires_every_term(capsys):
    store = FakeRunStore(
        {"run": [{"event": "TURN_END", "status": "success", "content": "all good"}]}
    )
    failure_corpus.search("failure injection", run_store=store)
    assert "No matching failures" in capsys.readouterr().out


def test_search_provider_error_is_reported(capsys):
    class BrokenStore:
        def list_runs(self, **kwargs):
            raise PermissionError("Access denied")

    failure_corpus.search("anything", run_store=BrokenStore())
    assert "Error searching corpus: Access denied" in capsys.readouterr().out
