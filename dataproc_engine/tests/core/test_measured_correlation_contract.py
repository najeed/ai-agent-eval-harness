"""Correlation scores are measured, thresholded and independent of optional libraries."""

import builtins
import copy
from difflib import SequenceMatcher
from itertools import permutations

import pytest

from dataproc_engine.core.base_provider import StandardSchema
from dataproc_engine.core.correlator import DataCorrelator


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
