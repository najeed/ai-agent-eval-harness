import pytest
import json
import pandas as pd
import os
import numpy as np
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from industries.agriculture.generators.faostat_generator import generate_faostat_parity
from industries.media_entertainment.generators.imdb_generator import generate_imdb_parity
from industries.telecom.generators.ookla_generator import generate_ookla_parity
from industries.retail.generators.olist_generator import generate_olist_parity

@pytest.fixture
def synthesizer():
    return ParitySynthesizer()

def test_model_ids_exist(synthesizer):
    """Verify all defined models can generate some data."""
    for model_id in synthesizer.MODELS.keys():
        records = synthesizer.generate_statistical_twin(model_id, count=5)
        assert len(records) == 5
        assert "_synthesis_audit" in records[0]

def test_statistical_moment_parity(synthesizer):
    """Assert generated distribution matches model parameters within tolerance."""
    # Test with a high count for statistical significance
    count = 1000
    model_id = "sec_fundamentals"
    records = synthesizer.generate_statistical_twin(model_id, count=count)
    
    revenues = [r["revenue_mil"] for r in records]
    target_mean = synthesizer.MODELS[model_id]["distributions"]["revenue_mil"]["mean"]
    target_std = synthesizer.MODELS[model_id]["distributions"]["revenue_mil"]["std"]
    
    # 5% tolerance for mean/std with 1000 samples
    assert abs(np.mean(revenues) - target_mean) < (target_mean * 0.05)
    assert abs(np.std(revenues) - target_std) < (target_std * 0.05)

def test_nc_sa_provenance_audit(synthesizer):
    """Assert NC-SA models carry the inheritance warning."""
    nc_sa_models = ["agri_stats_parity", "network_performance_parity", "ecommerce_transaction_parity"]
    for model_id in nc_sa_models:
        records = synthesizer.generate_statistical_twin(model_id, count=1)
        audit = records[0]["_synthesis_audit"]
        assert "CC BY-NC-SA" in audit["source_license"]

def test_dedicated_generator_execution(tmp_path):
    """Verify that dedicated generators produce valid JSONL files with correct provenance."""
    # 1. FAOStat
    fao_output = tmp_path / "faostat_test.jsonl"
    generate_faostat_parity(count=10, output_path=str(fao_output))
    assert fao_output.exists()
    
    with open(fao_output, 'r') as f:
        line = json.loads(f.readline())
        assert "_provenance_audit" in line
        assert "FAOStat" in line["_provenance_audit"]["license_info"]
        assert "inherit non-commercial restrictions" in line["_provenance_audit"]["note"]

    # 2. IMDb
    imdb_output = tmp_path / "imdb_test.jsonl"
    generate_imdb_parity(count=10, output_path=str(imdb_output))
    assert imdb_output.exists()
    
    with open(imdb_output, 'r') as f:
        line = json.loads(f.readline())
        assert "IMDb" in line["_provenance_audit"]["license_info"]
        assert "inherit restrictions" in line["_provenance_audit"]["note"]

def test_source_agnosticism_clinical(synthesizer):
    """Verify generic clinical records do not leak restricted identifiers."""
    records = synthesizer.generate_statistical_twin("clinical", count=10)
    json_str = json.dumps(records)
    restricted_keywords = ["MIMIC", "IEA", "UNIDO", "PhysioNet"]
    for kw in restricted_keywords:
        assert kw not in json_str

def test_boundary_constraints(synthesizer):
    """Assert that generated values respect min/max constraints."""
    model_id = "media_metadata_parity"
    # averageRating min=1, max=10
    records = synthesizer.generate_statistical_twin(model_id, count=500)
    ratings = [r["averageRating"] for r in records]
    assert all(1.0 <= r <= 10.0 for r in ratings)

def test_unknown_model_id(synthesizer):
    """Verify that unknown model IDs raise ValueError."""
    with pytest.raises(ValueError, match="Unknown synthesis model"):
        synthesizer.generate_statistical_twin("invalid_model")

def test_compliance_manifest(synthesizer):
    """Verify the compliance manifest generation."""
    manifest = synthesizer.get_compliance_manifest()
    assert "agri_stats_parity" in manifest
    assert manifest["agri_stats_parity"] == "CC BY-NC-SA 3.0"

def test_deprecated_validation_logic(synthesizer):
    """Verify the deprecated validation passthrough."""
    from unittest.mock import patch
    import pandas as pd
    with patch("dataproc_engine.core.paritygen.validation.validate_parity") as mock_val:
        df1 = pd.DataFrame({"a": [1]})
        df2 = pd.DataFrame({"a": [1]})
        synthesizer.validate_parity(df1, df2)
        mock_val.assert_called_once()

def test_status_categorical_field(synthesizer):
    """Test the 'status' categorical field generation path."""
    records = synthesizer.generate_statistical_twin("clinical", count=10)
    statuses = [r["status"] for r in records]
    valid_statuses = ["Stable", "Critical", "Discharged"]
    assert all(s in valid_statuses for s in statuses)

def test_full_pipeline_coverage():
    """Verify profiling, modeling, sampling, and validation submodules."""
    from dataproc_engine.core.paritygen.profiling import profile_data
    from dataproc_engine.core.paritygen.modeling import fit_multivariate_model
    from dataproc_engine.core.paritygen.sampling import generate_synthetic
    from dataproc_engine.core.paritygen.validation import validate_parity
    from dataproc_engine.core.paritygen.utils import dual_moment_correct
    import pandas as pd
    
    # 1. Setup Sample Data
    data = {
        "val": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        "cat": ["A", "B", "A", "C", "B", "A", "C", "A", "B", "A"]
    }
    df = pd.DataFrame(data)
    
    # 2. Profiling
    stats = profile_data(df)
    assert stats["shape"] == (10, 2)
    assert "mean" in stats
    
    # 3. Modeling
    model = fit_multivariate_model(df)
    assert "numeric" in model
    assert "categorical" in model
    
    # 4. Sampling
    syn_df = generate_synthetic(model, n_samples=50)
    assert len(syn_df) == 50
    assert "val" in syn_df.columns
    assert "cat" in syn_df.columns
    
    # 5. Validation
    val_results = validate_parity(df, syn_df)
    assert "val" in val_results
    assert "cat" in val_results
    assert "ks_stat" in val_results["val"]
    
    # 6. Utils (Dual-Moment Correct)
    raw_vals = [1.0, 2.0, 3.0]
    corrected = dual_moment_correct(raw_vals, target_mean=10.0, target_std=1.0)
    assert abs(np.mean(corrected) - 10.0) < 0.001
    assert abs(np.std(corrected) - 1.0) < 0.001
    
    # Edge case: zero std
    assert dual_moment_correct([1, 1], 10, 1) == [1, 1]

def test_cli_integration(tmp_path):
    """Verify the CLI wrapper execution path."""
    from dataproc_engine.core.paritygen.cli import main
    import sys
    from unittest.mock import patch
    
    input_csv = tmp_path / "input.csv"
    output_csv = tmp_path / "output.csv"
    
    # Create dummy input
    df = pd.DataFrame({"val": [1, 2, 3], "cat": ["A", "B", "A"]})
    df.to_csv(input_csv, index=False)
    
    test_args = [
        "cli.py",
        "--input", str(input_csv),
        "--output", str(output_csv),
        "--n-samples", "10"
    ]
    
    with patch.object(sys, 'argv', test_args):
        main()
        
    assert output_csv.exists()
    assert os.path.exists(str(output_csv) + ".metadata.json")

def test_cli_missing_input(tmp_path):
    """Verify CLI error handling for missing input."""
    from dataproc_engine.core.paritygen.cli import main
    import sys
    from unittest.mock import patch
    
    test_args = [
        "cli.py",
        "--input", "non_existent.csv",
        "--output", "out.csv"
    ]
    
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code == 1
