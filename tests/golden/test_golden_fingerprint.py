"""
tests/golden/test_golden_fingerprint.py
Golden Verification Corpus: Deterministic Provenance Fingerprint Validation
"""

from eval_runner.context import EvaluationContext
from eval_runner.publication_plugin import PublicationPlugin


def test_golden_deterministic_fingerprint_across_time():
    plugin = PublicationPlugin()

    ctx1 = EvaluationContext(
        identifier="scenario_telecom_01",
        scenario_data={"id": "scenario_telecom_01"},
        run_id="run-001",
        seed=42,
        metadata={"version": "1.0.0"},
    )

    ctx2 = EvaluationContext(
        identifier="scenario_telecom_01",
        scenario_data={"id": "scenario_telecom_01"},
        run_id="run-002",  # Different run ID, same scenario/seed/version
        seed=42,
        metadata={"version": "1.0.0"},
    )

    fp1 = plugin._generate_fingerprint(ctx1)
    fp2 = plugin._generate_fingerprint(ctx2)

    # Identical immutable inputs must yield identical fingerprint (independent of wall-clock time)
    assert fp1 == fp2
    assert isinstance(fp1, str)
    assert len(fp1) > 0


def test_golden_fingerprint_sensitivity_to_seed_and_version():
    plugin = PublicationPlugin()

    ctx_base = EvaluationContext(
        identifier="scenario_telecom_01",
        scenario_data={"id": "scenario_telecom_01"},
        seed=42,
        metadata={"version": "1.0.0"},
    )

    ctx_diff_seed = EvaluationContext(
        identifier="scenario_telecom_01",
        scenario_data={"id": "scenario_telecom_01"},
        seed=43,
        metadata={"version": "1.0.0"},
    )

    ctx_diff_ver = EvaluationContext(
        identifier="scenario_telecom_01",
        scenario_data={"id": "scenario_telecom_01"},
        seed=42,
        metadata={"version": "2.0.0"},
    )

    fp_base = plugin._generate_fingerprint(ctx_base)
    fp_diff_seed = plugin._generate_fingerprint(ctx_diff_seed)
    fp_diff_ver = plugin._generate_fingerprint(ctx_diff_ver)

    assert fp_base != fp_diff_seed
    assert fp_base != fp_diff_ver
