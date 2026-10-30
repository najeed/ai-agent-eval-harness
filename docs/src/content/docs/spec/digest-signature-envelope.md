---
title: Digest signature envelope v1
description: Frozen unsigned artifact projections and offline verification for bounded RAW Ed25519 signers.
---

AgentV Runtime implements `agentv.signature.digest-envelope.v1` in
`agentv_runtime.signatures`. This profile is ordinary Ed25519 over the canonical
envelope bytes. It is neither direct signing of the original artifact nor
Ed25519ph. SHA-256 of the projected payload is a separate commitment inside the
envelope; it does not change the Ed25519 signing algorithm.

The provider response has exactly three fields: `profile`, `envelope`, and
`signature`. `profile` is `agentv.signature.digest-envelope.v1`. The signature is
the canonical, padded RFC 4648 base64 encoding of exactly 64 bytes. Extra fields,
missing fields, unknown profiles, alternate encodings, and ambiguous unversioned
`signature`/`sig` response wrappers are rejected. A rejected envelope is never
retried as raw evidence.

## Signed envelope

The exhaustive repository guide is
`spec/signatures/SIGNATURES_SPEC_EXHAUSTIVE_GUIDE.md`; its machine-readable schema
is `spec/signatures/digest-envelope.schema.json`. Together they freeze the field
types, unsigned projections, trust rules, provider handoff, and acceptance gate.

The envelope has exactly the following fields. Every field is signed and checked
against reconstructed inputs and external trust policy. No optional fields exist
in v1. Changing a projection, canonicalization, algorithm, encoding, or field set
requires a new version; implementations must not change these meanings in place.

| Field | Required value or source |
| --- | --- |
| `profile` | `agentv.signature.digest-envelope.v1` |
| `version` | JSON integer `1`, not a boolean |
| `envelope_canonicalization` | `RFC8785` |
| `purpose` | One of the artifact purposes below |
| `payload_projection` | Exact corresponding projection identifier below |
| `payload_canonicalization` | `RFC8785` |
| `payload_digest` | SHA-256 of canonical projected payload bytes, 64 lowercase hex characters |
| `payload_digest_algorithm` | `sha256` |
| `payload_digest_encoding` | `hex-lowercase` |
| `signing_algorithm` | `Ed25519` |
| `signing_semantics` | `raw-ed25519-over-canonical-envelope-bytes` |
| `signer_identity` | Logical identity authorized by the external trust store |
| `key_id` | Immutable KMS key ARN, or `sha256:` followed by the external key fingerprint |
| `public_key_fingerprint` | SHA-256 of external public key SPKI DER bytes, lowercase hex |
| `fingerprint_algorithm` | `sha256` |
| `public_key_encoding` | `spki-der` |
| `signature_encoding` | `base64-rfc4648-padded` |
| `signature_length` | JSON integer `64` |

The canonical envelope must contain at most 4,096 bytes. Signing fails if the
bound identities or other required fields make it exceed this size. Signing an
oversized original artifact directly remains an error for bounded RAW providers.

## Frozen unsigned projections

Canonicalization applies **after** projection. It does not define the projection.
Signature-bearing transport responses are outside the envelope being signed.

### Certificate

Purpose: `agentv.certificate`. Projection: `agentv.certificate.unsigned.v1`.

Copy the certificate object, excluding exactly these top-level fields:

```text
provenance_chain
signing_context
certification_diagnostics
verification_package
package_hash
evaluation_hash
verification_hash
certificate_hash
```

If `certification` is an object, exclude exactly its immediate `stages` member.
Retain every other certificate field, including the complete `execution_manifest`,
scenario commitments, restrictions, execution mode, and metadata. Do not delete
fields recursively: a `signature` or `provenance_chain` member inside metadata or
the execution manifest remains signed data. Derived package/hash attachments are
verified separately through their own signatures and the evidence-chain checks.

### Verification package

Purpose: `agentv.verification-package`. Projection:
`agentv.verification-package.unsigned.v1`.

The projected object contains exactly these fields, produced by the public
`VerificationPackage.canonical_payload_dict()` contract:

```text
algorithm certificate_hash decision evaluation_hash evidence_root_hash
executed_oracle_results execution_identity finalization_hash key_id
manifest_hash manifest_id metadata package_id package_version
parent_artifact_refs producer_identity producer_version required_oracle_ids
scenario_hash scenario_id scenario_version schema_version signer_identity
trace_hash trace_seal verification_hash
```

`required_oracle_ids` and `parent_artifact_refs` are sorted. Optional textual
commitments, `key_id`, and `signer_identity` use the empty string when absent.
`finalization_hash` uses the finalization hash, otherwise the evaluation hash,
otherwise the empty string. Remaining values are retained as represented by the
typed contract, including all nested metadata and oracle evidence.

Excluded transport fields are `signature` and `public_key_pem`. Export-derived
`package_hash`, `content_hash`, and `commitment_graph` are also excluded. The
embedded public key is informational and must agree with the external anchor;
it cannot authorize its own signature.
Unknown top-level package fields are rejected for versioned responses rather than
silently excluded from the projection.

### Evaluator finalization

Purpose: `agentv.evaluator-finalization`. Projection:
`agentv.evaluator-finalization.unsigned.v1`.

The projected object contains exactly:

```text
evaluator_config_hash evaluator_identity evidence_root_hash
execution_manifest_hash finalization_id finalized_at metadata outcome
required_oracle_ids run_id scenario_hash scenario_id scenario_version
schema_version score terminal_seq
```

`required_oracle_ids` is sorted; all other values come from the typed
`EvaluatorFinalizationRecord`. Exclude `evaluator_signature`, its transport alias
`signature`, `finalization_hash`, and the export alias `manifest_hash`.
The finalization content hash is recomputed independently from the same unsigned
projection. Every metadata member remains signed.
Unknown top-level finalization fields and conflicting manifest/signature aliases
are rejected for versioned responses.

## External authorization and compatibility

`SignaturePolicy` is trusted configuration, never data read from an envelope.
It binds logical identity, immutable key identity, external public key, permitted
purposes/profiles, legacy policy, revocation, and timezone-aware validity bounds.
Revoked keys, disallowed purposes/profiles, expired keys, and not-yet-valid keys
fail verification, including legacy verification. Current v1 validity checks use
verification time; historical validation requires a separately defined trusted
timestamp policy and must not infer time from an unsigned claim.

The file-backed trust store reads `<TRUST_ROOT>/<identity>/signature_policy.json`
alongside its trusted `public_key.pem`. Example for a pinned KMS key:

```json
{
  "version": 1,
  "key_id": "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012",
  "permitted_profiles": ["agentv.signature.digest-envelope.v1"],
  "permitted_purposes": ["agentv.certificate", "agentv.verification-package"],
  "allow_legacy_raw": false,
  "revoked": false,
  "not_before": "2026-10-30T00:00:00+00:00"
}
```

An external resolver may instead implement `get_signature_policy(identity)` and
return a `SignaturePolicy`. With no policy file, the explicitly defined default
uses the trusted public-key fingerprint as key identity and permits both v1
envelopes and existing raw Ed25519 evidence. Set `allow_legacy_raw: false` and
remove `ed25519-raw` from permitted profiles to enforce migration. Unknown or
malformed envelope responses never enter that legacy path.

The existing raw path verifies the original frozen artifact projection directly
with Ed25519 and exactly 64 hex-encoded signature bytes. It does not guess an
algorithm from signature size. Legacy trace-only diagnostics remain
non-authoritative under the separate certification verdict contract.

## Provider handoff and independent verification

Wrap a deliberately selected `SigningBackend` with
`DigestEnvelopeSigningBackend(raw_backend, trusted_policy)`. AgentV Runtime artifact callers pass the `purpose` keyword. The adapter computes the payload digest, constructs and bounds the canonical envelope, calls the RAW backend, and checks the response against the pinned key before returning the complete structured response. AgentV Runtime retains it in manifest provenance, verification packages, and finalization records; it does not extract and discard the envelope bindings.

The wrapped `SigningBackend.sign_payload()` returns the RAW signature as hex.
An Enterprise adapter whose native provider returns base64 must perform an
explicit, strict encoding conversion at that adapter boundary. An unversioned
metadata tuple/dictionary is not an interchangeable response contract.

For AWS KMS, the wrapped provider must send these canonical envelope bytes using
`SigningAlgorithm=ED25519_SHA_512` and `MessageType=RAW`, pin the returned immutable
key ARN, and verify the response with its pinned public key. It must not substitute
`ED25519_PH_SHA_512`/`DIGEST`. AWS documents their different hashing semantics in
the [Sign API contract](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html).
No provider exception selects a locally generated signature. A local provider
must be deliberately configured as the selected provider.

An offline verifier reconstructs the exact artifact projection, canonicalizes
it, recomputes SHA-256, resolves external trust policy, validates every envelope
field and strict encoding, canonicalizes the expected envelope, and verifies
the Ed25519 signature. It requires neither KMS access nor the signing process.
Cryptographic validity alone does not establish a successful execution: the
existing scenario, manifest, raw trace, graph, oracle, finalization, and sealed-state
checks remain mandatory for an authoritative verdict.

Release evidence is exercised by `test_digest_signature_release_matrix.py` with
real HTTP execution and independent state observation, and by
`test_digest_signature_contract.py` with a bounded signer, offline subprocess,
genuinely signed invalid bindings, policy restrictions, outages, and rejected
responses before publication/sealing. These local tests do not attest a live AWS
deployment; Enterprise must retain direct RAW size rejection until its adapter
is wired to this profile and passes its KMS integration checks.
