import json
import shutil
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock cyclecore_pq to prevent import errors during CLI loading
mock_cyclecore = MagicMock()
sys.modules["cyclecore_pq"] = mock_cyclecore
sys.modules["cyclecore_pq.client"] = mock_cyclecore.client

from eval_runner import cli, config, verifier  # noqa: E402


class TestPQCCLI(unittest.TestCase):
    def setUp(self):
        # Reset PQC config before each test
        config.PQC_ENABLED = False
        config.PQC_STRICT_MODE = False
        # Ensure runs directory exists for tests
        config.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

    @patch("eval_runner.cli.safe_run_async")
    @patch("sys.exit")
    def test_run_pqc_flag_enables(self, mock_exit, mock_safe_run):
        # Industrial Hardening: Ensure coroutines are closed to prevent RuntimeWarnings
        # in Python 3.14+
        # This prevents resource leaks and non-deterministic failures in forensic test suites.
        mock_safe_run.side_effect = lambda coro: coro.close() or 0
        # Simulate 'agentv run --path scenarios/test.json --pqc'
        test_args = ["agentv", "run", "--path", "scenarios/test.json", "--pqc"]
        with patch("sys.argv", test_args):
            cli.main()
            self.assertTrue(config.PQC_ENABLED)

    @patch("eval_runner.cli.safe_run_async")
    @patch("sys.exit")
    def test_run_no_pqc_flag_disables(self, mock_exit, mock_safe_run):
        mock_safe_run.side_effect = lambda coro: coro.close() or 0
        # Start with PQC enabled
        config.PQC_ENABLED = True
        # Simulate 'agentv run --path scenarios/test.json --no-pqc'
        test_args = ["agentv", "run", "--path", "scenarios/test.json", "--no-pqc"]
        with patch("sys.argv", test_args):
            cli.main()
            self.assertFalse(config.PQC_ENABLED)

    @patch("eval_runner.cli.safe_run_async")
    @patch("sys.exit")
    def test_evaluate_pqc_flag_enables(self, mock_exit, mock_safe_run):
        mock_safe_run.side_effect = lambda coro: coro.close() or 0
        # Simulate 'agentv evaluate --path scenarios/ --pqc'
        test_args = ["agentv", "evaluate", "--path", "scenarios/", "--pqc"]
        with patch("sys.argv", test_args):
            cli.main()
            self.assertTrue(config.PQC_ENABLED)

    def test_strict_mode_fail_closed_signing(self):
        # Test TraceVerifier.sign_trace behavior across all strict mode combinations.
        # NOTE: sign_trace now includes a post-signature self-verification step.
        # Classical (ED25519) signing must use a real provisioned identity — mock keys
        # cannot produce a valid signature that the self-verify gate accepts.
        # Only the PQC client is mocked.
        from eval_runner.identity import IdentityService

        base_run_id = "test_strict_matrix"
        created_dirs = []
        identity_id = "strict_mode_test_id"
        IdentityService._provision_local_identity(identity_id)

        def _get_case_trace(suffix: str):
            rid = f"{base_run_id}_{suffix}"
            rdir = config.RUN_LOG_DIR / rid
            rdir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(rdir)
            tpath = rdir / "run.jsonl"
            tpath.write_text(json.dumps({"event": "start"}) + "\n")
            return rid, tpath

        try:
            # --- CASE 1: PQC ENABLED + STRICT ON + SIGNING FAILURE = FAIL CLOSED ---
            # sign_trace raises RuntimeError before reaching self-verify
            rid1, tpath1 = _get_case_trace("case1")
            mock_client_failing = MagicMock()
            mock_client_failing.sign_digest.side_effect = Exception("API Timeout")
            mock_client_failing.verify_digest.return_value = True

            with (
                patch("eval_runner.config.PQC_ENABLED", True),
                patch("eval_runner.config.PQC_STRICT_MODE", True),
                patch("eval_runner.config.PQC_IDENTITY_ID", identity_id),
                patch(
                    "eval_runner.identity.IdentityService.get_pqc_client",
                    return_value=mock_client_failing,
                ),
            ):
                with self.assertRaises(RuntimeError) as cm:
                    verifier.TraceVerifier.sign_trace(
                        str(tpath1), run_id=rid1, identity_id=identity_id
                    )
                self.assertIn("PQC_STRICT_MODE Violation", str(cm.exception))

            # --- CASE 2: PQC ENABLED + STRICT OFF + SIGNING FAILURE = FAIL OPEN ---
            rid2, tpath2 = _get_case_trace("case2")
            mock_client_failing2 = MagicMock()
            mock_client_failing2.sign_digest.side_effect = Exception("API Timeout")
            mock_client_failing2.verify_digest.return_value = True

            with (
                patch("eval_runner.config.PQC_ENABLED", True),
                patch("eval_runner.config.PQC_STRICT_MODE", False),
                patch("eval_runner.config.PQC_IDENTITY_ID", identity_id),
                patch(
                    "eval_runner.identity.IdentityService.get_pqc_client",
                    return_value=mock_client_failing2,
                ),
            ):
                # Should NOT raise, should just log warning and continue with classical
                manifest = verifier.TraceVerifier.sign_trace(
                    str(tpath2), run_id=rid2, identity_id=identity_id
                )
                self.assertEqual(len(manifest["provenance_chain"]), 1)
                self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")

            # --- CASE 3: PQC ENABLED + STRICT ON + SIGNING SUCCESS = SUCCESS ---
            rid3, tpath3 = _get_case_trace("case3")
            mock_client_success = MagicMock()
            mock_client_success.sign_digest.return_value = "pqc_sig"
            mock_client_success.verify_digest.return_value = True

            with (
                patch("eval_runner.config.PQC_ENABLED", True),
                patch("eval_runner.config.PQC_STRICT_MODE", True),
                patch("eval_runner.config.PQC_IDENTITY_ID", identity_id),
                patch(
                    "eval_runner.identity.IdentityService.get_pqc_client",
                    return_value=mock_client_success,
                ),
            ):
                manifest = verifier.TraceVerifier.sign_trace(
                    str(tpath3), run_id=rid3, identity_id=identity_id
                )
                self.assertEqual(len(manifest["provenance_chain"]), 2)
                self.assertEqual(manifest["provenance_chain"][1]["algorithm"], "ML-DSA-65")

            # --- CASE 4: PQC DISABLED + STRICT ON = SUCCESS (Classical Only) ---
            rid4, tpath4 = _get_case_trace("case4")
            with (
                patch("eval_runner.config.PQC_ENABLED", False),
                patch("eval_runner.config.PQC_STRICT_MODE", True),
            ):
                manifest = verifier.TraceVerifier.sign_trace(
                    str(tpath4), run_id=rid4, identity_id=identity_id
                )
                self.assertEqual(len(manifest["provenance_chain"]), 1)
                self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")

        finally:
            for d in created_dirs:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
