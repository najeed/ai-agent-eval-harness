"""
tests/contracts/test_verification_contract.py
Contract Test: Trace Verification & Certificate Chain

Validates the public TraceVerifier API, VC v3.0.0 certificate schema,
VerificationResult WSM scoring model, and SHA3-256 fingerprint stability.
Any structural change to these guarantees requires a MAJOR semver bump.
"""

from __future__ import annotations

import eval_runner.config as config
from eval_runner.verifier import VC_V3_SCHEMA_VERSION, TraceVerifier, VerificationResult


class TestVerificationContract:
    """
    Trace Verification & Certificate Chain Contract Tests.
    """

    # ─── VC Schema Version ────────────────────────────────────────────────────

    def test_vc_schema_version_is_v3(self):
        """
        Contract: The Verification Certificate schema version must be '3.0.0'.
        Changing this constant is a MAJOR breaking contract change.
        """
        assert VC_V3_SCHEMA_VERSION == "3.0.0", (
            f"VC schema version changed to '{VC_V3_SCHEMA_VERSION}'. "
            "This is a MAJOR contract violation."
        )

    # ─── VerificationResult WSM Model ─────────────────────────────────────────

    def test_verification_result_aggregate_score_in_bounds(self):
        """
        Contract: VerificationResult.aggregate_score must always lie in [0.0, 1.0]
        for any valid metric vector.
        """
        metrics = {
            "safety": 0.9,
            "security": 0.85,
            "reliability": 0.7,
            "fairness": 0.8,
            "explainability": 0.6,
            "privacy": 0.75,
            "resilience": 0.65,
        }
        result = VerificationResult(success=True, message="Contract check", metrics=metrics)
        assert 0.0 <= result.aggregate_score <= 1.0, (
            f"aggregate_score {result.aggregate_score} is out of [0.0, 1.0] bounds."
        )

    def test_verification_result_safety_floor_enforced(self):
        """
        Contract: WSM Safety Floor — if safety < 0.5 or security < 0.5,
        aggregate_score must be capped at <= 0.49. This is a SOC2 CC6.6 control guarantee.
        """
        low_safety = {
            "safety": 0.2,
            "security": 0.9,
            "reliability": 1.0,
            "fairness": 1.0,
            "explainability": 1.0,
            "privacy": 1.0,
            "resilience": 1.0,
        }
        result = VerificationResult(success=True, message="Safety floor test", metrics=low_safety)
        assert result.aggregate_score <= 0.49, (
            f"Safety floor not enforced: score {result.aggregate_score} with safety=0.2."
        )

    def test_verification_result_wsm_weights_sum_to_one(self):
        """
        Contract: The WSM weight vector must sum to 1.0.
        Changing the weight distribution is a MAJOR contract violation.
        """
        total = sum(VerificationResult.WSM_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, (
            f"WSM weights do not sum to 1.0 (sum={total}). "
            "This is a MAJOR scoring model contract violation."
        )

    def test_verification_result_wsm_required_dimensions(self):
        """
        Contract: The WSM must contain exactly the 7 NIST AI-100-1 dimensions.
        """
        required = {
            "safety",
            "security",
            "reliability",
            "fairness",
            "explainability",
            "privacy",
            "resilience",
        }
        actual = set(VerificationResult.WSM_WEIGHTS.keys())
        assert required == actual, f"WSM dimensions changed. Expected: {required}, Got: {actual}"

    # ─── sign_trace Certificate Structure ─────────────────────────────────────

    def test_sign_trace_produces_valid_certificate_schema(self, tmp_path, monkeypatch):
        """
        Contract: sign_trace() must return a dict with the required VC v3.0.0 fields:
        'run_id', 'vc_version', 'trace_hash', 'timestamp', and 'provenance_chain'.
        """
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

        run_id = "contract_verify_001"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        trace = run_dir / "run.jsonl"
        trace.write_text('{"event": "tool_call"}\n{"event": "agent_response"}\n', encoding="utf-8")

        manifest = TraceVerifier.sign_trace(
            trace_path=str(trace),
            identity_id="contract_test_signer",
            run_id=run_id,
        )

        assert manifest is not None, "sign_trace() returned None — certification failed."
        required_fields = {"run_id", "vc_version", "trace_hash", "timestamp", "provenance_chain"}
        for field in required_fields:
            assert field in manifest, (
                f"VC certificate missing required field '{field}'. "
                f"This is a MAJOR contract violation. Got keys: {list(manifest.keys())}"
            )

    def test_sign_trace_schema_version_matches_constant(self, tmp_path, monkeypatch):
        """
        Contract: The vc_version in the generated VC must equal VC_V3_SCHEMA_VERSION.
        """
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

        run_id = "contract_schema_001"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        trace = run_dir / "run.jsonl"
        trace.write_text('{"event": "start"}\n', encoding="utf-8")

        manifest = TraceVerifier.sign_trace(
            trace_path=str(trace),
            identity_id="schema_contract_signer",
            run_id=run_id,
        )

        assert manifest.get("vc_version") == VC_V3_SCHEMA_VERSION, (
            f"VC vc_version '{manifest.get('vc_version')}' "
            f"does not match constant '{VC_V3_SCHEMA_VERSION}'."
        )

    def test_sign_trace_hash_is_sha3_256(self, tmp_path, monkeypatch):
        """
        Contract: trace_hash must be a 64-character lowercase hex string (SHA3-256).
        """
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

        run_id = "contract_fp_001"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        trace = run_dir / "run.jsonl"
        trace.write_text('{"event": "validation"}\n', encoding="utf-8")

        manifest = TraceVerifier.sign_trace(
            trace_path=str(trace),
            identity_id="fp_contract_signer",
            run_id=run_id,
        )

        th = manifest.get("trace_hash", "")
        assert len(th) == 64, f"trace_hash is not 64 chars (SHA3-256): '{th}'"
        assert all(c in "0123456789abcdef" for c in th), f"trace_hash is not lowercase hex: '{th}'"
        assert manifest.get("hash_algorithm") == "sha3_256"

    def test_sign_trace_fingerprint_stability(self, tmp_path, monkeypatch):
        """
        Contract: Two independent traces with identical contents produce identical trace_hash.
        """
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

        # Run A
        run_id_a = "contract_stable_001"
        run_dir_a = runs_dir / run_id_a
        run_dir_a.mkdir(parents=True)
        trace_a = run_dir_a / "run.jsonl"
        trace_a.write_text('{"event": "stable_event"}\n', encoding="utf-8")

        # Run B
        run_id_b = "contract_stable_002"
        run_dir_b = runs_dir / run_id_b
        run_dir_b.mkdir(parents=True)
        trace_b = run_dir_b / "run.jsonl"
        trace_b.write_text('{"event": "stable_event"}\n', encoding="utf-8")

        # Seal hash check on initial file
        hash_a = TraceVerifier.compute_signature(trace_a)
        hash_b = TraceVerifier.compute_signature(trace_b)
        assert hash_a == hash_b, "compute_signature is non-deterministic on identical files."
