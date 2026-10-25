import json
import unittest
from unittest.mock import patch

from eval_runner import config
from eval_runner.compliance import ComplianceService


class TestCompliancePQC(unittest.TestCase):
    def setUp(self):
        self.run_id = "test_run_compliance_pqc"
        self.run_dir = config.RUN_LOG_DIR / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "run_manifest.json"

        self.compliance_service = ComplianceService()

    def tearDown(self):
        if self.manifest_path.exists():
            self.manifest_path.unlink()
        if self.run_dir.exists():
            self.run_dir.rmdir()

    def test_check_pqc_status_quantum_safe_with_client(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [
                {"algorithm": "ED25519", "identity": "system_id"},
                {
                    "algorithm": "ML-DSA-65",
                    "identity": "system_id@pqc",
                    "signature": "abcdef123456",
                },
            ],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        from unittest.mock import MagicMock

        from eval_runner.identity import IdentityService

        mock_pqc = MagicMock()
        mock_pqc.verify_digest.return_value = True
        with patch.object(IdentityService, "get_pqc_client", return_value=mock_pqc):
            status = self.compliance_service.check_pqc_status(self.run_id)
            self.assertTrue(status["quantum_safe"])
            self.assertEqual(status["algorithm"], "ML-DSA-65")

    def test_check_pqc_status_unverifiable_without_client(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [
                {"algorithm": "ED25519", "identity": "system_id"},
                {
                    "algorithm": "ML-DSA-65",
                    "identity": "system_id@pqc",
                    "signature": "abcdef123456",
                },
            ],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        from eval_runner.identity import IdentityService

        with patch.object(IdentityService, "get_pqc_client", return_value=None):
            status = self.compliance_service.check_pqc_status(self.run_id)
            self.assertFalse(status["quantum_safe"])
            self.assertEqual(status["status"], "unverifiable")
            self.assertIn("PQC client not available", status["reason"])

    def test_check_pqc_status_not_quantum_safe(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [{"algorithm": "ED25519", "identity": "system_id"}],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        status = self.compliance_service.check_pqc_status(self.run_id)
        self.assertFalse(status["quantum_safe"])
        self.assertEqual(status["algorithm"], "ED25519")

    def test_check_pqc_status_missing_manifest(self):
        status = self.compliance_service.check_pqc_status("non_existent_run")
        self.assertFalse(status["quantum_safe"])
        self.assertEqual(status["reason"], "Manifest missing")

    def test_evaluate_compliance_with_pqc_strict_mode(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [{"algorithm": "ED25519"}],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        from eval_runner.compliance import evaluate_compliance

        with patch("eval_runner.config.PQC_STRICT_MODE", False):
            result = evaluate_compliance(self.run_id, {"some_metric": 1.0})
            self.assertFalse(result["compliant"])
            self.assertFalse(result["pqc_status"]["quantum_safe"])
            self.assertEqual(result["behavioral_metrics"], "not_evaluated_in_oss")
            self.assertFalse(result["metrics_eval"]["pass"])

        with patch("eval_runner.config.PQC_STRICT_MODE", True):
            result = evaluate_compliance(self.run_id, {"some_metric": 1.0})
            self.assertFalse(result["compliant"])
            self.assertIn("PQC_STRICT_MODE", result["message"])
            self.assertEqual(result["metrics_eval"]["status"], "NOT_EVALUATED")

    def test_evaluate_compliance_quantum_safe_is_compliant(self):
        """Quantum-safe proof alone yields NOT_EVALUATED until behavioral metrics pass."""
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [
                {
                    "algorithm": "ML-DSA-65",
                    "provider": "cyclecore",
                    "timestamp": "2026-05-14T12:00:01",
                    "signature": "sig_hex_12345",
                }
            ],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        from unittest.mock import MagicMock

        from eval_runner.compliance import evaluate_compliance
        from eval_runner.identity import IdentityService

        mock_pqc = MagicMock()
        mock_pqc.verify_digest.return_value = True

        with patch.object(IdentityService, "get_pqc_client", return_value=mock_pqc):
            for strict in (False, True):
                with (
                    patch("eval_runner.config.PQC_STRICT_MODE", strict),
                    self.subTest(strict=strict),
                ):
                    result = evaluate_compliance(self.run_id, {})
                    self.assertEqual(result["status"], "NOT_EVALUATED")
                    self.assertFalse(result["compliant"])
                    self.assertTrue(result["pqc_status"]["quantum_safe"])

            mock_eval = {"status": "EVALUATED", "pass": True}
            with patch(
                "eval_runner.compliance.ComplianceService._evaluate_metrics_pack",
                return_value=mock_eval,
            ):
                result = evaluate_compliance(self.run_id, {"latency": 100})
                self.assertEqual(result["status"], "COMPLIANT")
                self.assertTrue(result["compliant"])
                self.assertTrue(result["pqc_status"]["quantum_safe"])

            # Test branch: status != NOT_EVALUATED and pass == False -> NON_COMPLIANT
            mock_failed_eval = {"status": "EVALUATED", "pass": False}
            with patch(
                "eval_runner.compliance.ComplianceService._evaluate_metrics_pack",
                return_value=mock_failed_eval,
            ):
                result = evaluate_compliance(self.run_id, {"latency": 100})
                self.assertEqual(result["status"], "NON_COMPLIANT")
                self.assertFalse(result["compliant"])
                self.assertIn("One or more compliance requirements failed", result["message"])

    def test_check_pqc_status_run_store_missing_get_manifest(self):
        class InvalidRunStore:
            pass

        with self.assertRaises(ValueError) as ctx:
            self.compliance_service.check_pqc_status(self.run_id, run_store=InvalidRunStore())
        self.assertIn("RunStorageProvider is required", str(ctx.exception))

    def test_check_pqc_status_invalid_signature(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [
                {
                    "algorithm": "ML-DSA-65",
                    "identity": "system_id@pqc",
                    "signature": "invalid_sig_hex",
                },
            ],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        from unittest.mock import MagicMock

        from eval_runner.identity import IdentityService

        mock_pqc = MagicMock()
        mock_pqc.verify_digest.return_value = False
        with patch.object(IdentityService, "get_pqc_client", return_value=mock_pqc):
            status = self.compliance_service.check_pqc_status(self.run_id)
            self.assertFalse(status["quantum_safe"])
            self.assertEqual(status["algorithm"], "ML-DSA-65")
            self.assertIn("PQC signature verification failed", status["reason"])

    def test_check_pqc_status_exception_handling(self):
        class CorruptedManifestStore:
            def get_manifest(self, *a, **k):
                return {"provenance_chain": None}  # raises TypeError when iterating

        status = self.compliance_service.check_pqc_status(
            self.run_id, run_store=CorruptedManifestStore()
        )
        self.assertFalse(status["quantum_safe"])
        self.assertIn("reason", status)

    def test_evaluate_compliance_with_explicit_run_store(self):
        class DummyStore:
            def get_manifest(self, *a, **k):
                return {"provenance_chain": []}

        from eval_runner.compliance import evaluate_compliance

        result = evaluate_compliance("run-explicit", run_store=DummyStore())
        self.assertFalse(result["compliant"])
        self.assertEqual(result["status"], "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()
