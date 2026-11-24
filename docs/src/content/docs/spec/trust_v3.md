---
title: "Forensic Trust Protocol v3.0.0"
description: "Authoritative specification for cryptographic evaluation integrity"
---

The current trust protocol binds executed scenario, execution manifest, exact raw
trace bytes, observed oracle evidence, evaluator finalization and certificate
publication. Use [the VC schema](/spec/vc/vc.schema.json) and
[digest signature envelope](/spec/digest-signature-envelope/) together.

## Signature authority

Current artifact signatures are purpose-bound structured digest envelopes with
strict unsigned projections, canonical encoding and externally authorized keys.
Raw hexadecimal artifact signatures and embedded self-authorizing keys cannot
establish current certification authority. Package/finalization signatures and
their separate content hashes must also reconcile with the execution evidence.

## Provider ownership

Certification uses the run owner's scoped provider record, exact committed trace
bytes and manifest. Filesystem discovery and master logs are not alternative
evidence inputs. Resume preserves the existing contract snapshot and event
sequence; `run_end` remains the terminal execution event.

The provider must atomically publish a verified certificate and sealed lifecycle
state. Failed persistence, missing/invalid required oracles, absent finalization,
untrusted signatures or provisional execution prevent authoritative issuance.
Execution completion and signature validity alone do not imply a passing claim.

## Evidence and retention

The certificate binds the evidence root and relevant artifact commitments. Local
artifact filtering and sidecar handling must not be confused with independent
external state observation. Use bounded, declared state selectors and retain the
source evidence needed to reproduce oracle outcomes.

`LocalFileArtifactStore` provides `TAMPER_EVIDENT_LOGICAL_SEAL`. Its programmatic
seal can detect later modification, but privileged host administrators can alter
local storage. Physical WORM requires a retention-enforcing external store.
`REQUIRE_IMMUTABLE_WORM=true` fails certification on logical-only storage.

## Verification

Use the [complete verification workflow](/auditor/verification/) for raw trace,
actual manifest/scenario, external trust policy, graph and oracle reconciliation.
Signature-only or unsigned diagnostic checks do not authorize certification.
