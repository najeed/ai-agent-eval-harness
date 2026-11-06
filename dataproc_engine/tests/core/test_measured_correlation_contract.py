"""Correlation scores are measured, thresholded and independent of optional libraries."""

import builtins
import copy
from difflib import SequenceMatcher
from itertools import permutations

import pytest

from dataproc_engine.core.base_provider import StandardSchema
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.providers.decision_support import DecisionSupportProvider


def _sector_observations(sector, metric, values):
    return [
        StandardSchema.create(
            sector,
            {"region": "R1", "year": index, metric: value},
            {"source": f"test://{sector}"},
            record_id=f"{sector}-{index}",
        )
        for index, value in enumerate(values)
    ]


@pytest.mark.parametrize("datasets", [None, {"a": "bad"}, {1: []}, {"a": [None]}])
def test_decision_support_rejects_malformed_datasets(datasets):
    with pytest.raises(ValueError):
        DecisionSupportProvider({}).correlate_sectors(datasets)


def test_decision_support_simulation_permission_and_provenance():
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [1, 2, 3]),
    }
    datasets["a"][0].provenance["simulation"] = True
    with pytest.raises(PermissionError):
        DecisionSupportProvider({}).correlate_sectors(datasets)
    result = DecisionSupportProvider({"allow_simulation": True}).correlate_sectors(datasets)
    assert result[0]["provenance"]["execution_mode"] == "simulated"


def test_decision_support_explicit_alignment_and_unique_record_identity():
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [1, 2, 3]),
    }
    provider = DecisionSupportProvider({"correlation_keys": ["year", "region"]})
    assert provider.correlate_sectors(datasets)[0]["observation_count"] == 3
    datasets["a"][1].id = datasets["a"][0].id
    with pytest.raises(ValueError, match="identities"):
        provider.correlate_sectors(datasets)


def test_decision_support_never_pairs_unkeyed_rows_by_position():
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [3, 2, 1]),
    }
    for rows in datasets.values():
        for row in rows:
            row.data.pop("year")
    assert DecisionSupportProvider({}).correlate_sectors(datasets) == []


def test_decision_support_unrepresentable_numeric_values_are_not_measured():
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [10**400] * 3),
    }
    assert DecisionSupportProvider({}).correlate_sectors(datasets) == []


def test_decision_support_measures_aligned_pairs_and_binds_source_content():
    datasets = {
        "environment": _sector_observations("environment", "heat", [1, 2, 3, 4]),
        "agriculture": _sector_observations("agriculture", "yield", [8, 6, 4, 2]),
    }
    before = copy.deepcopy(datasets)
    provider = DecisionSupportProvider({})
    result = provider.correlate_sectors(datasets)
    assert len(result) == 1
    assert result[0]["sectors"] == ["agriculture", "environment"]
    assert result[0]["pearson"] == pytest.approx(-1)
    assert result[0]["spearman"] == pytest.approx(-1)
    assert result[0]["observation_count"] == 4
    assert datasets == before
    assert provider.correlate_sectors({k: list(reversed(v)) for k, v in datasets.items()}) == result
    from agentv_runtime.canonical import canonical_json_encode
    from eval_runner.utils import crypto

    evidence = result[0]["provenance"]["observations"][0]["left"]
    source = datasets["agriculture"][0]
    expected = {
        "id": source.id,
        "industry": source.industry,
        "data": source.data,
        "provenance": source.provenance,
    }
    assert evidence["content_digest"] == "sha3_256:" + crypto.checksum(
        canonical_json_encode(expected)
    )
    source.data["yield"] = 7
    updated = provider.correlate_sectors(datasets)
    assert updated[0]["correlation_id"] != result[0]["correlation_id"]


def test_decision_support_reports_tied_ranks_constants_and_composite_anomalies():
    provider = DecisionSupportProvider({})
    datasets = {
        "a": _sector_observations("a", "x", [0] * 9 + [10]),
        "b": _sector_observations("b", "y", [0] * 9 + [100]),
    }
    result = provider.correlate_sectors(datasets)[0]
    assert result["spearman"] == pytest.approx(1)
    assert result["risk"]["composite_anomaly_score"] == pytest.approx(3)
    assert result["risk"]["anomalies"] == [{"observation": ["R1", 9], "score": pytest.approx(3)}]
    datasets["a"] = _sector_observations("a", "x", [1] * 10)
    constant = provider.correlate_sectors(datasets)[0]
    assert constant["pearson"] is None
    assert constant["spearman"] is None
    assert constant["coefficient_status"] == "undefined_constant_series"


def test_decision_support_requires_overlap_and_complete_finite_metrics():
    provider = DecisionSupportProvider({})
    assert provider.correlate_sectors({}) == []
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [1, None, float("nan")]),
    }
    assert provider.correlate_sectors(datasets) == []
    datasets["b"] = _sector_observations("b", "y", [1, 2, 3])
    for row in datasets["b"]:
        row.data["year"] += 10
    assert provider.correlate_sectors(datasets) == []


@pytest.mark.parametrize(
    "config",
    [
        {"correlation_min_observations": 2},
        {"correlation_min_observations": True},
        {"correlation_anomaly_threshold": float("nan")},
        {"correlation_anomaly_threshold": 0},
        {"correlation_keys": []},
        {"correlation_keys": ["year", "year"]},
    ],
)
def test_decision_support_rejects_invalid_correlation_configuration(config):
    with pytest.raises(ValueError):
        DecisionSupportProvider(config).correlate_sectors({})


def test_decision_support_rejects_duplicate_or_missing_alignment_coordinates():
    datasets = {
        "a": _sector_observations("a", "x", [1, 2, 3]),
        "b": _sector_observations("b", "y", [1, 2, 3]),
    }
    datasets["a"][1].data["year"] = 0
    with pytest.raises(ValueError, match="Duplicate observation"):
        DecisionSupportProvider({}).correlate_sectors(datasets)
    with pytest.raises(ValueError, match="coordinates"):
        DecisionSupportProvider({"correlation_keys": ["date"]}).correlate_sectors(datasets)


def record(identity, industry, name, value=100):
    return StandardSchema(identity, industry, {"entity_name": name, "value": value}, {}, "hash")


@pytest.mark.parametrize("candidate", ["acme network", "acme networks", "acme networkz"])
def test_different_strengths_retain_actual_measured_scores(candidate):
    source = record("finance", "finance", "acme network")
    target = record("telecom", "telecom", candidate)
    result = DataCorrelator.correlate({"finance": [source], "telecom": [target]})
    provenance = result["finance"][0].provenance["telecom_correlation"]
    assert (
        provenance["similarity_score"]
        == 100 * SequenceMatcher(None, "acme network", candidate, autojunk=False).ratio()
    )
    assert provenance["minimum_similarity"] == 85.0
    assert provenance["algorithm"] == "difflib.SequenceMatcher.ratio/autojunk=false/v1"
    assert provenance["matched_record_id"] == "telecom"


@pytest.mark.parametrize("name", ["", None, 123, "unrelated oil company", "a", "!!!"])
def test_unrelated_empty_and_short_substrings_are_not_linked(name):
    source = record("finance", "finance", "acme networks")
    DataCorrelator.correlate({"finance": [source], "telecom": [record("tel", "telecom", name)]})
    assert "correlated_telecom_id" not in source.provenance
    assert "telecom_correlation" not in source.provenance
    assert "telecom_footprint_speed" not in source.data


def test_optional_library_availability_cannot_change_result_or_provenance(monkeypatch):
    data = {
        "finance": [record("fin", "finance", "ACME  Networks!")],
        "telecom": [record("tel", "telecom", "acme network")],
    }
    expected = DataCorrelator.correlate(copy.deepcopy(data))
    original_import = builtins.__import__

    def without_optional_library(name, *args, **kwargs):
        if name.startswith("rapidfuzz"):
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_optional_library)
    assert DataCorrelator.correlate(copy.deepcopy(data)) == expected


def test_candidate_order_and_duplicate_names_have_stable_tie_breaks():
    targets = [
        record("z", "telecom", "Acme Network", 30),
        record("a", "telecom", "acme network", 10),
        record("other", "telecom", "acme networkz", 20),
    ]
    results = []
    for ordered in permutations(targets):
        source = record("fin", "finance", "acme network")
        DataCorrelator.correlate({"finance": [source], "telecom": list(ordered)})
        results.append(source.to_dict())
    assert all(result == results[0] for result in results)
    assert results[0]["telecom_footprint_speed"] == 10
    assert results[0]["correlated_telecom_id"] == "a"


def test_explicit_threshold_boundary_and_stale_link_removal():
    source = record("fin", "finance", "acme network")
    data = {"finance": [source], "telecom": [record("tel", "telecom", "acme networks")]}
    threshold = 100 * SequenceMatcher(None, "acme network", "acme networks", autojunk=False).ratio()
    DataCorrelator.correlate(data, minimum_similarity=threshold)
    assert source.provenance["correlated_telecom_id"] == "tel"
    DataCorrelator.correlate(data, minimum_similarity=threshold + 0.001)
    assert "correlated_telecom_id" not in source.provenance
    assert "telecom_correlation" not in source.provenance
    assert "telecom_footprint_speed" not in source.data


@pytest.mark.parametrize("threshold", [True, None, "85", 0, -1, 101, float("nan"), float("inf")])
def test_invalid_thresholds_fail_explicitly(threshold):
    with pytest.raises(ValueError, match="minimum_similarity"):
        DataCorrelator.correlate({}, minimum_similarity=threshold)
