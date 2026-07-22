import json
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Mock cyclecore_pq before importing eval_runner
mock_cyclecore = MagicMock()
sys.modules["cyclecore_pq"] = mock_cyclecore
sys.modules["cyclecore_pq.client"] = mock_cyclecore.client

from eval_runner import config, identity, verifier  # noqa: E402


class TestPQCSigning(unittest.TestCase):
    def setUp(self):
        # Industrial Requirement: Trace MUST be in the vault folder
        self.run_id = "test_run_123"
        self.vault_dir = config.RUN_LOG_DIR / self.run_id
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.test_trace = self.vault_dir / "run.jsonl"

        with open(self.test_trace, "w") as f:
            f.write(json.dumps({"event": "test_start"}) + "\n")

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

        if self.test_trace.exists():
            self.test_trace.unlink()
        if self.vault_dir.exists():
            # Clean up sidecars
            sidecar = self.vault_dir / "run_manifest.json"
            if sidecar.exists():
                sidecar.unlink()
            try:
                # Remove artifacts folder if created by sign_trace
                forensics_dir = self.vault_dir / "forensics"
                if forensics_dir.exists():
                    import shutil

                    shutil.rmtree(forensics_dir)
                self.vault_dir.rmdir()
            except OSError:
                pass

    @patch("eval_runner.identity.IdentityService.get_private_key")
    def test_hybrid_signing_flow(self, mock_get_priv):
        # Mock ED25519
        mock_priv = MagicMock()
        mock_priv.sign.return_value = b"classical_sig"
        mock_get_priv.return_value = mock_priv

        # Mock CycleCore
        mock_client = MagicMock()
        mock_client.sign_digest.return_value = "pqc_sig_hex"

        # Force the client into the service
        identity.IdentityService._pqc_client = mock_client

        # Execute signing
        manifest = verifier.TraceVerifier.sign_trace(
            trace_path=str(self.test_trace), run_id=self.run_id, identity_id="system_id"
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

    @patch("eval_runner.identity.IdentityService.get_private_key")
    def test_verify_hybrid_signatures(self, mock_get_priv):
        # Mock clients
        mock_priv = MagicMock()
        mock_get_priv.return_value = mock_priv

        mock_client = MagicMock()
        mock_client.verify_digest.return_value = True
        identity.IdentityService._pqc_client = mock_client

        # Create a mock manifest with valid hex and timestamp
        timestamp = datetime.now().astimezone().isoformat()
        manifest = {
            "vc_version": "3.0.0",
            "sha256": "abcdef0123456789",
            "timestamp": timestamp,
            "provenance_chain": [
                {
                    "identity": "system_id",
                    "signature": "deadbeef" * 8,  # 32 bytes hex
                    "algorithm": "ED25519",
                },
                {
                    "identity": "system_id@pqc",
                    "signature": "cafebabe" * 60,  # Large hex for PQC
                    "algorithm": "ML-DSA-65",
                },
            ],
        }
        manifest_path = self.vault_dir / "run_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        # Mock file hash to match manifest
        with patch("eval_runner.verifier.TraceVerifier.compute_signature") as mock_hash:
            mock_hash.return_value = "abcdef0123456789"

            # Mock public key verification
            with patch("eval_runner.identity.IdentityService.get_public_key") as mock_get_pub:
                mock_pub = MagicMock()
                mock_get_pub.return_value = mock_pub

                # Execute verification
                success = verifier.TraceVerifier.verify_trace(
                    trace_path=str(self.test_trace), manifest_path=str(manifest_path)
                )

                self.assertTrue(success)
                mock_pub.verify.assert_called_once()
                mock_client.verify_digest.assert_called_once()

    def test_pqc_disabled_fallback(self):
        config.PQC_ENABLED = False

        with patch("eval_runner.identity.IdentityService.get_private_key") as mock_get_priv:
            mock_priv = MagicMock()
            mock_priv.sign.return_value = b"classical_sig"
            mock_get_priv.return_value = mock_priv

            manifest = verifier.TraceVerifier.sign_trace(
                trace_path=str(self.test_trace), run_id=self.run_id, identity_id="system_id"
            )

            # Should only have 1 signature
            self.assertEqual(len(manifest["provenance_chain"]), 1)
            self.assertEqual(manifest["provenance_chain"][0]["algorithm"], "ED25519")


if __name__ == "__main__":
    unittest.main()
