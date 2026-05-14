import json
import unittest
from unittest.mock import patch

from enterprise.services.compliance_service import ComplianceService

from eval_runner import config


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

    def test_check_pqc_status_quantum_safe(self):
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [
                {"algorithm": "ED25519", "identity": "system_id"},
                {"algorithm": "ML-DSA-65", "identity": "system_id@pqc"},
            ],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        status = self.compliance_service.check_pqc_status(self.run_id)
        self.assertTrue(status["quantum_safe"])
        self.assertEqual(status["algorithm"], "ML-DSA-65")

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

    @patch("enterprise.services.compliance_service.ComplianceService._evaluate_metrics_pack")
    def test_evaluate_compliance_with_pqc_strict_mode(self, mock_eval):
        # Setup mock compliance pack result
        mock_eval.return_value = {"pass": True, "details": []}

        # Setup run manifest (Not Quantum Safe)
        manifest = {
            "timestamp": "2026-05-14T12:00:00",
            "provenance_chain": [{"algorithm": "ED25519"}],
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f)

        # 1. PQC_STRICT_MODE = False (Should Pass)
        with patch("eval_runner.config.PQC_STRICT_MODE", False):
            from enterprise.services.compliance_service import evaluate_compliance

            result = evaluate_compliance(self.run_id, {"some_metric": 1.0})
            self.assertTrue(result["compliant"])
            self.assertFalse(result["pqc_status"]["quantum_safe"])

        # 2. PQC_STRICT_MODE = True (Should Fail)
        with patch("eval_runner.config.PQC_STRICT_MODE", True):
            result = evaluate_compliance(self.run_id, {"some_metric": 1.0})
            self.assertFalse(result["compliant"])
            self.assertFalse(result["pqc_status"]["quantum_safe"])


if __name__ == "__main__":
    unittest.main()
