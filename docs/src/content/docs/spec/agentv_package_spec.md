---
title: "Verification Package Specification (.agentv-package.json)"
description: "Signed verification attestations, console export wrappers, their distinct hashes, and required offline verification evidence."
---

AgentV exposes two package layers. Their hashes, versions and authority differ.

## Signed verification attestation

`agentv_runtime.package.VerificationPackage` is the typed signed attestation
contract (package/schema version `1.0.0`). It commits to scenario identity/hash,
execution manifest, execution identity, raw trace hash/seal, evidence root,
required and executed oracles, finalization and decision, plus producer and
parent-artifact metadata.

`canonical_payload_dict()` defines its exact unsigned projection. It sorts
`required_oracle_ids` and `parent_artifact_refs`, normalizes absent optional text
commitments, and excludes transport signature/key attachments. Its content hash
is the SHA3-256 hex digest of `canonical_json_encode()` applied to that projection.
Do not hash all serialized transport fields to verify this commitment.

Authoritative artifact signatures use
[`agentv.signature.digest-envelope.v1`](/spec/digest-signature-envelope/).
The envelope's SHA-256 payload commitment and the package's SHA3-256 content hash
serve different purposes. External policy/key anchoring is mandatory; an embedded
public key cannot authorize itself.

## Console export wrapper

`GET /api/v1/evidence/packages/<run_id>` returns a presentation/export wrapper with
`format: "agentv_verification_package"` and version `2.0.0`. Its structural schema
is [agentv-package.schema.json](/spec/agentv-package/agentv-package.schema.json).

It contains scenario and manifest views, chain metadata, verdict, cryptographic
verification state, evidence manifest/graph, observed assertions and signatures.
The signed typed package is retained inside the manifest. The wrapper itself is
not a substitute for that signed attestation or the provider's exact trace bytes.

The wrapper's `package_hash` hashes compact, sorted `json.dumps` output over its
export fields before `package_hash` and `package_created_at` are added. This
export checksum is not the typed package's RFC 8785 commitment. Treat wrapper
observations as preliminary until authoritative verification succeeds.

## Offline verification

For the console export, provide exact raw trace bytes and an external trust key:

```bash
agentv verify-package evidence.agentv-package.json --trace run.jsonl --public-key trusted-public.pem
```

For a standalone typed package also provide the actual execution manifest and
scenario:

```bash
agentv verify-package signed-package.json --trace run.jsonl --execution-manifest execution_manifest.json --scenario scenario.json --require-scenario --public-key trusted-public.pem
```

`--diagnostic` explicitly selects non-authoritative analysis. A signature-only
check cannot prove execution, required oracle outcomes or lifecycle sealing.
See [verification](/auditor/verification/) for the authoritative contract and
REST endpoint's server-owned trust policy.
