---
title: "Extension Manifest & SRI Specification"
description: "Authoritative specification for sandboxed micro-frontend extensions, dynamic navigation manifests, and Subresource Integrity digests."
---

Extension integration has three related contracts: navigation presentation,
the generic Python `RuntimeExtension`, and the signed frontend release sidecar.
Use [the generic schema](/spec/extensions/extension-manifest.schema.json) and
`agentv_runtime.extension_contract` for the Python declaration, and
`ui/visual-console/src/types/extension-contract.ts` for the frontend contract.
They are not interchangeable schemas.

## Generic declaration

Required generic fields are `extension_id`, `display_name`, `version` and
`api_version`. Optional fields include compatibility versions, capabilities,
required permissions, routes, navigation group, `remote_entry`, `sri_hash`,
publisher, signature and lifecycle declarations. Unknown generic fields are
rejected by the machine schema. In that schema `sri_hash` is a 64-character hex
SHA3-256 digest; the frontend release format uses prefixed SRI encodings.

## Frontend release

A production remote release must supply a signed `.manifest.json` sidecar before
its code executes. It binds `remote_entry`, SRI, publisher identity, version,
API compatibility, routes/permissions and the integrity map of relative chunks.
Production also requires `react_peer: true` and the host React singleton.
Use the [publish workflow](/extender/gui-extensions/) to generate and sign the
release fields rather than inventing digests or signatures.

## Execution and trust

The loader verifies entry/chunk bytes, manifest bindings and the publisher
against the server trust root. SRI proves bytes, not publisher authority.
Cross-origin loading can be permitted with pinned SRI and verified publisher
metadata. The backend determines the trust tier; self-declared `tier` values do
not grant trust.

Verified React modules mount in the host application. They do **not** execute in
isolated iframes. Production permits backend-verified official extensions and
rejects community and unsigned modules because an execution isolation boundary
is not implemented. Development can expose restricted unsigned-local modules.

Mounted extensions receive `ExtensionRuntimeContextApi` with authenticated
context, `switchContext` and `authorizedFetch`. Enforce resource permissions and
scope ownership on the server; UI context is not an authorization authority.
