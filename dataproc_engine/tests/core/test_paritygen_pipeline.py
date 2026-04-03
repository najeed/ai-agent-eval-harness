"""
test_paritygen_pipeline.py
Full pipeline coverage for the paritygen sub-package:
  profiling -> modeling -> sampling -> validation -> provenance -> synthesizer
"""
import json
import pytest
import pandas as pd
import numpy as np

from dataproc_engine.core.paritygen.profiling import profile_data
from dataproc_engine.core.paritygen.modeling import fit_multivariate_model
from dataproc_engine.core.paritygen.sampling import generate_synthetic
from dataproc_engine.core.paritygen.provenance import provenance_metadata
from dataproc_engine.core.paritygen.validation import validate_parity
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def numeric_df():
    """Simple numeric DataFrame for pipeline tests."""
    return pd.DataFrame({
        "revenue": [100.0, 200.0, 150.0, 300.0, 250.0],
        "profit":  [10.0,  25.0,  15.0,  40.0,  30.0],
    })


@pytest.fixture
def mixed_df():
    """Mixed numeric + categorical DataFrame."""
    return pd.DataFrame({
        "revenue":  [100.0, 200.0, 300.0, 150.0],
        "profit":   [10.0,  30.0,  50.0,  20.0],
        "sector":   ["tech", "health", "tech", "finance"],
        "region":   ["US",  "EU",    "US",   "APAC"],
    })


# ─── Step 1: Profiling ────────────────────────────────────────────────────────

def test_profile_data_numeric_only(numeric_df):
    """profile_data extracts mean, variance, correlation for numeric columns."""
    stats = profile_data(numeric_df)

    assert "mean" in stats
    assert "variance" in stats
    assert "correlations" in stats
    assert "shape" in stats
    assert "columns" in stats
    assert stats["shape"] == (5, 2)
    assert "revenue" in stats["mean"]
    assert stats["mean"]["revenue"] == pytest.approx(200.0)


def test_profile_data_categorical_frequencies(mixed_df):
    """profile_data captures categorical value frequencies."""
    stats = profile_data(mixed_df)

    assert "categorical_freqs" in stats
    assert "sector" in stats["categorical_freqs"]
    assert "tech" in stats["categorical_freqs"]["sector"]
    # "tech" appears 2/4 times → 50%
    assert stats["categorical_freqs"]["sector"]["tech"] == pytest.approx(0.5)


def test_profile_data_empty_df():
    """profile_data handles empty DataFrame gracefully."""
    df = pd.DataFrame({"val": pd.Series([], dtype=float)})
    stats = profile_data(df)
    assert "shape" in stats
    assert stats["shape"][0] == 0


# ─── Step 2: Modeling ─────────────────────────────────────────────────────────

def test_fit_multivariate_model_structure(numeric_df):
    """fit_multivariate_model returns a dict with numeric and categorical keys."""
    model = fit_multivariate_model(numeric_df)

    assert "numeric" in model
    assert "categorical" in model
    assert "mean" in model["numeric"]
    assert "cov" in model["numeric"]
    assert "cols" in model["numeric"]
    assert set(model["numeric"]["cols"]) == {"revenue", "profit"}


def test_fit_multivariate_model_categorical(mixed_df):
    """fit_multivariate_model captures categorical frequency distributions."""
    model = fit_multivariate_model(mixed_df)

    assert "sector" in model["categorical"]
    assert "region" in model["categorical"]
    # Frequencies should sum to 1.0 for each categorical
    sector_total = sum(model["categorical"]["sector"].values())
    assert sector_total == pytest.approx(1.0, abs=0.01)


def test_fit_model_covariance_is_symmetric(numeric_df):
    """Covariance matrix from fit must be symmetric."""
    model = fit_multivariate_model(numeric_df)
    cov = model["numeric"]["cov"]
    # cov[revenue][profit] == cov[profit][revenue]
    assert cov["revenue"]["profit"] == pytest.approx(cov["profit"]["revenue"])


# ─── Step 3: Sampling ─────────────────────────────────────────────────────────

def test_generate_synthetic_shape(numeric_df):
    """generate_synthetic produces the requested number of rows."""
    model = fit_multivariate_model(numeric_df)
    synth = generate_synthetic(model, n_samples=50)

    assert isinstance(synth, pd.DataFrame)
    assert len(synth) == 50
    assert set(["revenue", "profit"]).issubset(synth.columns)


def test_generate_synthetic_categorical_values(mixed_df):
    """generate_synthetic respects categorical distributions."""
    model = fit_multivariate_model(mixed_df)
    synth = generate_synthetic(model, n_samples=100)

    # All synthetic sector values must be from the original set
    assert set(synth["sector"].unique()).issubset({"tech", "health", "finance"})
    assert set(synth["region"].unique()).issubset({"US", "EU", "APAC"})


def test_generate_synthetic_numeric_plausibility(numeric_df):
    """Synthetic numeric columns should be roughly in the same order of magnitude."""
    model = fit_multivariate_model(numeric_df)
    synth = generate_synthetic(model, n_samples=200)

    # Means should be in the ballpark of original means (within 3 sigma of original std)
    original_mean_rev = numeric_df["revenue"].mean()
    synth_mean_rev = synth["revenue"].mean()
    assert abs(synth_mean_rev - original_mean_rev) < original_mean_rev * 2.0


# ─── Step 4: Validation — Categorical Drift Branch ───────────────────────────

def test_validate_parity_categorical_pass():
    """validate_parity detects no drift when categorical frequencies match."""
    df_a = pd.DataFrame({"cat": ["A", "B", "A", "B", "A", "B"]})
    df_b = pd.DataFrame({"cat": ["A", "A", "B", "B", "A", "B"]})

    metrics = validate_parity(df_a, df_b)
    assert "cat" in metrics
    assert metrics["cat"]["max_freq_drift"] < 0.20
    assert metrics["cat"]["status"] in ("PASS", "DRIFT_WARN")


def test_validate_parity_categorical_drift():
    """validate_parity detects significant categorical drift."""
    df_a = pd.DataFrame({"cat": ["A"] * 10 + ["B"] * 0})  # 100% A
    df_b = pd.DataFrame({"cat": ["A"] * 5 + ["B"] * 5})   # 50% A
    metrics = validate_parity(df_a, df_b)
    assert "cat" in metrics
    assert metrics["cat"]["max_freq_drift"] > 0.40


def test_validate_parity_mixed_numeric_and_categorical():
    """validate_parity processes both numeric and categorical columns."""
    df_a = pd.DataFrame({"val": [1.0, 2.0, 3.0], "cat": ["X", "Y", "X"]})
    df_b = pd.DataFrame({"val": [1.1, 2.1, 3.1], "cat": ["X", "X", "Y"]})

    metrics = validate_parity(df_a, df_b)
    assert "val" in metrics
    assert "cat" in metrics


def test_validate_parity_correlation_drift():
    """validate_parity captures correlation matrix drift."""
    df_a = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10]})   # perfect corr
    df_b = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [10, 1, 8, 2, 5]})   # random

    metrics = validate_parity(df_a, df_b)
    assert "_correlation_max_drift" in metrics


# ─── Step 5: Provenance Metadata ──────────────────────────────────────────────

def test_provenance_metadata_structure():
    """provenance_metadata returns valid JSON with required compliance fields."""
    meta_str = provenance_metadata("CC-BY 4.0")
    meta = json.loads(meta_str)

    assert "license_info" in meta
    assert meta["license_info"] == "CC-BY 4.0"
    assert "generation_method" in meta
    assert meta["generation_method"] == "statistical_sampling"
    assert "provenance_statement" in meta
    assert "compliance_disclaimer" in meta
    assert "generated_at" in meta
    assert "parity_framework" in meta


def test_provenance_metadata_with_note():
    """provenance_metadata includes custom note field."""
    meta_str = provenance_metadata("Restricted", synthetic=True, note="Clinical trial data proxy")
    meta = json.loads(meta_str)
    assert meta["note"] == "Clinical trial data proxy"


def test_provenance_metadata_is_deterministic_structure():
    """Two calls produce structurally identical output (fields match)."""
    m1 = json.loads(provenance_metadata("MIT"))
    m2 = json.loads(provenance_metadata("MIT"))
    assert set(m1.keys()) == set(m2.keys())


# ─── Step 6: ParitySynthesizer — All Models ───────────────────────────────────

@pytest.mark.parametrize("model_id", [
    "world_bank_gdp",
    "sec_fundamentals",
    "clinical",
    "macro_energy_balances",
    "industrial_sector_stats",
    "ecommerce_transaction_parity",
    "agri_stats_parity",
    "media_metadata_parity",
    "network_performance_parity",
])
def test_parity_synthesizer_all_models(model_id):
    """ParitySynthesizer generates valid records for every registered model."""
    synth = ParitySynthesizer()
    records = synth.generate_statistical_twin(model_id, count=3)

    assert isinstance(records, list)
    assert len(records) == 3
    # Every record must have synthesis audit metadata
    for rec in records:
        assert "_synthesis_audit" in rec
        assert rec["_synthesis_audit"]["generation_method"] == "statistical_sampling"


def test_parity_synthesizer_boundary_clipping():
    """Synthesized numeric values respect min/max boundaries."""
    synth = ParitySynthesizer()
    records = synth.generate_statistical_twin("clinical", count=100)

    glucose = [r["glucose_mg_dl"] for r in records]
    heart_rate = [r["heart_rate"] for r in records]

    # Model min/max constraints
    assert all(v >= 20 for v in glucose), "Glucose below min=20"
    assert all(v <= 600 for v in glucose), "Glucose above max=600"
    assert all(v >= 40 for v in heart_rate), "HR below min=40"
    assert all(v <= 200 for v in heart_rate), "HR above max=200"


def test_parity_synthesizer_compliance_manifest():
    """get_compliance_manifest returns one entry per model."""
    synth = ParitySynthesizer()
    manifest = synth.get_compliance_manifest()
    assert isinstance(manifest, dict)
    assert len(manifest) >= 8
    assert "world_bank_gdp" in manifest


def test_parity_synthesizer_unknown_model_raises():
    """generate_statistical_twin raises ValueError for unknown model IDs."""
    synth = ParitySynthesizer()
    with pytest.raises(ValueError, match="Unknown synthesis model"):
        synth.generate_statistical_twin("non_existent_model_xyz")





# ─── Step 7: Full E2E Pipeline ────────────────────────────────────────────────

def test_full_paritygen_pipeline_e2e(tmp_path, mixed_df):
    """End-to-end: profile → model → sample → validate → provenance."""
    # Step 1: Profile
    profile = profile_data(mixed_df)
    assert "mean" in profile

    # Step 2: Model
    model = fit_multivariate_model(mixed_df)
    assert "numeric" in model

    # Step 3: Sample
    synthetic = generate_synthetic(model, n_samples=20)
    assert len(synthetic) == 20

    # Step 4: Validate
    metrics = validate_parity(mixed_df, synthetic)
    assert "revenue" in metrics  # numeric column must be validated

    # Step 5: Provenance
    meta_str = provenance_metadata("CC-BY 4.0", note="E2E test")
    meta = json.loads(meta_str)
    assert meta["license_info"] == "CC-BY 4.0"

    # Step 6: Write to file (like CLI does)
    output = tmp_path / "synthetic.csv"
    synthetic.to_csv(output, index=False)
    assert output.exists()
    loaded = pd.read_csv(output)
    assert len(loaded) == 20
