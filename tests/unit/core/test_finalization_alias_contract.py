"""Supported wire aliases preserve one canonical finalization signature."""

import pytest

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("manifest_field", ["execution_manifest_hash", "manifest_hash"])
@pytest.mark.parametrize("signature_field", ["evaluator_signature", "signature"])
def test_finalization_aliases_preserve_authoritative_binding(
    finalization_source, manifest_field, signature_field
):
    provider, _ = finalization_source
    original = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    payload = {
        key: value
        for key, value in original.items()
        if key
        not in {"execution_manifest_hash", "manifest_hash", "evaluator_signature", "signature"}
    }
    payload[manifest_field] = original["execution_manifest_hash"]
    payload[signature_field] = original["evaluator_signature"]

    restored = EvaluatorFinalizationRecord.from_dict(payload, require_authoritative=True)

    assert restored.execution_manifest_hash == original["execution_manifest_hash"]
    assert restored.evaluator_signature == original["evaluator_signature"]
    assert restored.finalization_hash == original["finalization_hash"]
