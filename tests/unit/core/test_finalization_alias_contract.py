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


def _signed_payload(provider):
    return dict(provider.get_events("run-a", offset=0, limit=100)[-1]["data"])


@pytest.mark.parametrize("signature_field", ["evaluator_signature", "signature"])
def test_unknown_field_is_rejected_for_either_signature_alias(finalization_source, signature_field):
    provider, _ = finalization_source
    original = _signed_payload(provider)
    payload = {k: v for k, v in original.items() if k not in {"evaluator_signature", "signature"}}
    payload[signature_field] = original["evaluator_signature"]
    payload["unreviewed_extra_field"] = "x"

    with pytest.raises(ValueError, match="Unknown field outside finalization"):
        EvaluatorFinalizationRecord.parse_untrusted(payload)


def test_conflicting_signature_aliases_are_ambiguous(finalization_source):
    provider, _ = finalization_source
    payload = _signed_payload(provider)
    payload["signature"] = {**payload["evaluator_signature"], "signature": "AAAA"}

    with pytest.raises(ValueError, match="Ambiguous finalization signature aliases"):
        EvaluatorFinalizationRecord.parse_untrusted(payload)


def test_conflicting_manifest_aliases_are_ambiguous(finalization_source):
    provider, _ = finalization_source
    payload = _signed_payload(provider)
    payload["manifest_hash"] = "0" * 64
    assert payload["execution_manifest_hash"] != payload["manifest_hash"]

    with pytest.raises(ValueError, match="Ambiguous finalization manifest aliases"):
        EvaluatorFinalizationRecord.parse_untrusted(payload)


@pytest.mark.parametrize("signature_alias", ["signature", "evaluator_signature"])
def test_agreeing_manifest_aliases_are_accepted(finalization_source, signature_alias):
    provider, _ = finalization_source
    original = _signed_payload(provider)
    payload = {k: v for k, v in original.items() if k not in {"evaluator_signature", "signature"}}
    payload[signature_alias] = original["evaluator_signature"]
    payload["manifest_hash"] = original["execution_manifest_hash"]

    record = EvaluatorFinalizationRecord.parse_untrusted(payload)

    assert record.execution_manifest_hash == original["execution_manifest_hash"]
