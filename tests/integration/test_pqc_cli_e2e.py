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
        # Test TraceVerifier.sign_trace behavior across all strict mode combinations
        run_id = "test_strict_matrix"
        run_dir = config.RUN_LOG_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        trace_path = run_dir / "run.jsonl"
        trace_path.write_text(json.dumps({"event": "start"}) + "\n")

        try:
            # Common mocks
            with (
                patch("eval_runner.identity.IdentityService.get_private_key") as mock_get_priv,
                patch("eval_runner.identity.IdentityService.get_pqc_client") as mock_get_client,
                patch("eval_runner.config.PQC_IDENTITY_ID", "test_id"),
            ):
                mock_priv = MagicMock()
                mock_priv.sign.return_value.hex.return_value = "classical_sig"
                mock_get_priv.return_value = mock_priv
                mock_client = MagicMock()

                # --- CASE 1: PQC ENABLED + STRICT ON + SIGNING FAILURE = FAIL CLOSED ---
                with (
                    patch("eval_runner.config.PQC_ENABLED", True),
                    patch("eval_runner.config.PQC_STRICT_MODE", True),
                ):
                    mock_client.sign_digest.side_effect = Exception("API Timeout")
                    mock_get_client.return_value = mock_client

                    with self.assertRaises(RuntimeError) as cm:
                        verifier.TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
                    self.assertIn("PQC_STRICT_MODE Violation", str(cm.exception))

                # --- CASE 2: PQC ENABLED + STRICT OFF + SIGNING FAILURE = FAIL OPEN ---
                with (
                    patch("eval_runner.config.PQC_ENABLED", True),
                    patch("eval_runner.config.PQC_STRICT_MODE", False),
                ):
                    mock_client.sign_digest.side_effect = Exception("API Timeout")
                    mock_get_client.return_value = mock_client

                    # Should NOT raise, should just log warning and continue with classical
                    manifest = verifier.TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
                    self.assertEqual(len(manifest["provenance_chain"]), 1)
                    self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")

                # --- CASE 3: PQC ENABLED + STRICT ON + SIGNING SUCCESS = SUCCESS ---
                with (
                    patch("eval_runner.config.PQC_ENABLED", True),
                    patch("eval_runner.config.PQC_STRICT_MODE", True),
                ):
                    mock_client.sign_digest.side_effect = None
                    mock_client.sign_digest.return_value = "pqc_sig"
                    mock_get_client.return_value = mock_client

                    manifest = verifier.TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
                    self.assertEqual(len(manifest["provenance_chain"]), 2)
                    self.assertEqual(manifest["provenance_chain"][1]["algorithm"], "ML-DSA-65")

                # --- CASE 4: PQC DISABLED + STRICT ON = SUCCESS (Classical Only) ---
                with (
                    patch("eval_runner.config.PQC_ENABLED", False),
                    patch("eval_runner.config.PQC_STRICT_MODE", True),
                ):
                    manifest = verifier.TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
                    self.assertEqual(len(manifest["provenance_chain"]), 1)
                    self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")

        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
