"""Require complete local signing evidence; never infer live KMS feature readiness."""

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REQUIRED = {
    "test_large_payload_is_an_envelope_signature_with_independent_offline_verification": 1,
    "test_every_envelope_binding_is_enforced_even_with_a_genuine_signature": 18,
    "test_malformed_or_ambiguous_responses_do_not_downgrade": 12,
    "test_external_trust_policy_restricts_valid_signatures": 5,
    "test_raw_legacy_evidence_requires_explicit_policy": 1,
    "test_remote_outage_and_wrong_key_fail_without_local_fallback": 1,
    "test_noncanonical_payloads_cannot_claim_rfc8785": 4,
    "test_resolved_backend_outage_cannot_use_existing_local_private_key": 1,
    "test_full_certification_preserves_envelopes_and_verifies_without_backend": 1,
    "test_large_finalization_round_trip_preserves_and_verifies_envelope": 1,
    "test_bad_structured_response_cannot_publish_or_seal": 10,
    "test_exact_certificate_projection_excludes_only_frozen_fields": 1,
    "test_offline_process_reconstructs_frozen_projection": 4,
    "test_cross_implementation_canonicalization_vectors": 4,
    "test_strict_transport_json_rejects_ambiguous_or_unsupported_inputs": 11,
    "test_hardware_failure_never_consults_available_local_key": 28,
    "test_signature_semantics_and_exact_field_types_are_not_inferred": 6,
    "test_mutable_kms_alias_is_not_an_immutable_key_binding": 1,
    "test_digest_signature_release_matrix": 22,
    "test_invalid_or_oversized_signer_identity_never_reaches_remote": 2,
    "test_envelope_shape_is_strict_for_json_inputs": 7,
    "test_external_resolver_cannot_change_the_expected_identity": 3,
    "test_external_resolver_policy_must_match_the_selected_public_anchor": 1,
    "test_nonzero_base64_padding_bits_are_rejected_even_for_valid_signature_bytes": 1,
    "test_raw_signing_response_cannot_use_permissive_hex_whitespace": 1,
    "test_raw_backend_hex_whitespace_is_not_silently_normalized": 1,
}


def verify(path: Path) -> dict:
    root = ET.parse(path).getroot()  # nosec B314
    observed = Counter()
    names = set()
    for case in root.iter("testcase"):
        name = case.get("name", "")
        function = name.split("[", 1)[0]
        if function not in REQUIRED:
            raise ValueError(f"Unexpected signing-matrix test: {name}")
        if name in names:
            raise ValueError(f"Duplicate signing-matrix test: {name}")
        names.add(name)
        if any(case.find(tag) is not None for tag in ("failure", "error", "skipped")):
            raise ValueError(f"Signing-matrix test did not pass: {name}")
        observed[function] += 1
    if dict(observed) != REQUIRED:
        raise ValueError(f"Incomplete signing matrix: expected {REQUIRED}, got {dict(observed)}")
    return {
        "profile": "agentv.signature.digest-envelope.v1",
        "core_local_evidence_verified": True,
        "passed_cases": len(names),
        "evidence_type": "local-and-transport-double",
        "live_kms_evidence_verified": False,
        "enterprise_adapter_verified": False,
        "large_payload_kms_feature_claim_ready": False,
        "release_approval": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.junit)
    except (ValueError, OSError, ET.ParseError) as exc:
        parser.exit(1, f"Signing acceptance gate failed: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Core signing contract: {result['passed_cases']} passed; live KMS feature gate pending")


if __name__ == "__main__":
    main()
