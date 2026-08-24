"""
A5: Verdict-authoritative attempt success (pass@k).

An attempt succeeds if and only if:
  1. workflow_verdict.status == workflow_completed, AND
  2. every evaluation is valid (no evaluation_valid=False, no
     EVALUATION_INVALID triage), AND
  3. no metric row is EVALUATION_INVALID / failed (informational exempt), AND
  4. no policy decision was denied.
"""

import pytest

from eval_runner.runner import DefaultRunner


def _completed_attempt():
    return [
        {
            "task_id": "node_1",
            "status": "success",
            "metrics": [{"metric": "m", "success": True}],
        },
        {
            "task_id": "workflow",
            "status": "success",
            "metrics": [],
            "workflow_verdict": {"status": "workflow_completed", "reason": "terminal reached"},
        },
    ]


@pytest.fixture
def runner():
    return DefaultRunner()


class TestVerdictAuthoritativeSuccess:
    def test_completed_valid_attempt_succeeds(self, runner):
        assert runner._is_attempt_successful(_completed_attempt()) is True

    def test_missing_workflow_verdict_vetoes(self, runner):
        rows = [{"task_id": "n1", "status": "success", "metrics": [{"success": True}]}]
        assert runner._is_attempt_successful(rows) is False

    def test_failed_verdict_vetoes(self, runner):
        rows = _completed_attempt()
        rows[-1]["workflow_verdict"]["status"] = "workflow_failed"
        assert runner._is_attempt_successful(rows) is False

    def test_aborted_verdict_vetoes(self, runner):
        rows = _completed_attempt()
        rows[-1]["workflow_verdict"]["status"] = "workflow_aborted"
        assert runner._is_attempt_successful(rows) is False

    def test_evaluation_invalid_triage_vetoes(self, runner):
        rows = _completed_attempt()
        rows[0]["triage_tag"] = "EVALUATION_INVALID"
        assert runner._is_attempt_successful(rows) is False

    def test_evaluation_valid_false_vetoes(self, runner):
        rows = _completed_attempt()
        rows[0]["evaluation_valid"] = False
        assert runner._is_attempt_successful(rows) is False

    def test_invalid_metric_row_vetoes(self, runner):
        rows = _completed_attempt()
        rows[0]["metrics"].append({"metric": "x", "status": "EVALUATION_INVALID", "success": False})
        assert runner._is_attempt_successful(rows) is False

    def test_failed_metric_row_vetoes(self, runner):
        rows = _completed_attempt()
        rows[0]["metrics"][0]["success"] = False
        assert runner._is_attempt_successful(rows) is False

    def test_informational_failure_does_not_veto(self, runner):
        rows = _completed_attempt()
        rows[0]["metrics"].append(
            {"metric": "info_row", "success": False, "severity": "informational"}
        )
        assert runner._is_attempt_successful(rows) is True

    def test_denied_policy_check_vetoes(self, runner):
        rows = _completed_attempt()
        rows[0]["policy_checks"] = [{"id": "p1", "decision": "denied", "reason": "limit exceeded"}]
        assert runner._is_attempt_successful(rows) is False

    def test_allowed_policy_checks_do_not_veto(self, runner):
        rows = _completed_attempt()
        rows[0]["policy_checks"] = [{"id": "p1", "decision": "allowed"}]
        assert runner._is_attempt_successful(rows) is True

    def test_empty_attempt_fails(self, runner):
        assert runner._is_attempt_successful([]) is False

    def test_legacy_passed_key_no_longer_grants_success(self, runner):
        # The legacy bug: rows keyed 'passed' instead of 'success' silently passed.
        rows = [
            {
                "task_id": "n1",
                "status": "success",
                "workflow_verdict": {"status": "workflow_completed"},
                "metrics": [{"metric": "m", "passed": True, "success": False}],
            }
        ]
        assert runner._is_attempt_successful(rows) is False
