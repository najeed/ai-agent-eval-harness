import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Mock cyclecore_pq before importing eval_runner
mock_cyclecore = MagicMock()
sys.modules["cyclecore_pq"] = mock_cyclecore
sys.modules["cyclecore_pq.client"] = mock_cyclecore.client

from eval_runner import config, identity, verifier  # noqa: E402
from eval_runner.reference.local_run_store import LocalFileRunStore  # noqa: E402


class TestPQCSigning(unittest.TestCase):
    def setUp(self):
        # The local reference provider owns its files internally; tests seed
        # evidence through its public contract rather than a trace path.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.run_id = "test_run_123"
        self.run_store = LocalFileRunStore(self.temp_dir.name)
        self.run_store.create_run(self.run_id, "pqc-signing")
        self.run_store.append_events(self.run_id, [{"event": "test_start", "_seq": 1}])

        # Reset PQC config
        config.PQC_ENABLED = True
        config.PQC_PROVIDER = "cyclecore"
        config.CYCLECORE_API_KEY = "test_key"
        config.CYCLECORE_IDENTITY_ID = "test_id"
        identity.IdentityService._pqc_client = None

    def tearDown(self):
        # Reset PQC global config to prevent cross-test contamination (xdist)
        config.PQC_ENABLED = False
        config.CYCLECORE_API_KEY = ""
        identity.IdentityService._pqc_client = None

        try:
            self.temp_dir.cleanup()
        except OSError as cleanup_err:
            import logging

            logging.getLogger(__name__).debug(f"Tempdir cleanup notice: {cleanup_err}")

    def test_hybrid_signing_flow(self):
        """Hybrid signing (ED25519 + PQC) produces a 2-entry provenance chain."""
        # Provision a real local identity so the self-verification step succeeds.
        from eval_runner.identity import IdentityService

        identity_id = "pqc_test_signing_id"
        IdentityService._provision_local_identity(identity_id)

        # Mock CycleCore PQC client only
        mock_client = MagicMock()
        mock_client.sign_digest.return_value = "pqc_sig_hex"
        mock_client.verify_digest.return_value = True
        identity.IdentityService._pqc_client = mock_client

        # Execute signing with a real identity
        manifest = verifier.TraceVerifier.sign_trace_bytes(
            self.run_store.get_trace_bytes(self.run_id),
            run_id=self.run_id,
            identity_id=identity_id,
            run_store=self.run_store,
        )

        # Verify manifest structure
        self.assertEqual(len(manifest["provenance_chain"]), 2)
        self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")
        self.assertEqual(manifest["provenance_chain"][1]["algorithm"], "ML-DSA-65")
        self.assertEqual(manifest["provenance_chain"][1]["signature"], "pqc_sig_hex")

        # Verify ZES: sign_digest should have been called with a 32-byte digest
        mock_client.sign_digest.assert_called_once()
        args, kwargs = mock_client.sign_digest.call_args
        self.assertEqual(len(kwargs["digest"]), 32)

    def test_verify_hybrid_signatures(self):
        config.PQC_ENABLED = True
        config.PQC_IDENTITY_ID = "system_id@pqc"
        config.PQC_PROVIDER = "cyclecore"

        mock_client = MagicMock()
        mock_client.sign_digest.return_value = "cafebabe" * 60
        mock_client.verify_digest.return_value = True
        identity.IdentityService._pqc_client = mock_client

        identity_id = "pqc_hybrid_test_id"
        identity.IdentityService._provision_local_identity(identity_id)

        trace_bytes = self.run_store.get_trace_bytes(self.run_id)
        manifest = verifier.TraceVerifier.sign_trace_bytes(
            trace_bytes,
            run_id=self.run_id,
            identity_id=identity_id,
            run_store=self.run_store,
        )

        self.assertEqual(len(manifest["provenance_chain"]), 2)
        self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")
        self.assertEqual(manifest["provenance_chain"][1]["algorithm"], "ML-DSA-65")

        success = verifier.TraceVerifier.verify_trace_bytes(
            trace_bytes,
            manifest,
            run_store=self.run_store,
            trace_only=True,
        )
        self.assertTrue(success)
        mock_client.verify_digest.assert_called_once()

    def test_pqc_disabled_fallback(self):
        """When PQC is disabled, only a classical ED25519 signature is produced."""
        config.PQC_ENABLED = False

        # Provision a real local identity so the self-verification step succeeds.
        from eval_runner.identity import IdentityService

        identity_id = "pqc_disabled_fallback_id"
        IdentityService._provision_local_identity(identity_id)

        manifest = verifier.TraceVerifier.sign_trace_bytes(
            self.run_store.get_trace_bytes(self.run_id),
            run_id=self.run_id,
            identity_id=identity_id,
            run_store=self.run_store,
        )

        # Should only have 1 signature
        self.assertEqual(len(manifest["provenance_chain"]), 1)
        self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")


if __name__ == "__main__":
    unittest.main()
