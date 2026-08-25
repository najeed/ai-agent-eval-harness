# RuntimeExtension Manifest Specification — Exhaustive Guide

**Schema:** `extension-manifest.schema.json` · **Semantic validator:** `agentv_runtime.extension_contract.RuntimeExtension.validate` · **Contract version:** 1.0.0 (SemVer; additive-only within 1.x) · **TS mirror:** `ui/visual-console/src/types/extension-contract.ts`

Audience: Control Plane publishers mounting remote micro-frontends into the OSS GUI shell.

---

## 1. Trust model (memorize this)

> **SRI proves bytes. Signatures prove publisher. The BACKEND decides tier.**

| Layer | Mechanism | Guarantees |
|---|---|---|
| Integrity | `sri_hash` (SHA3-256) verified byte-for-byte before mount | Module is exactly what the manifest pinned |
| Publisher | Ed25519 signature over canonical manifest bytes (every field EXCEPT `signature`), verified server-side via `POST /api/v1/extensions/verify-publisher` against the trust-root public key | Manifest authorship |
| Authorization | Backend returns an authoritative `tier`; the host grants host-APIs strictly by tier (`hostApisForTier`) and **ignores any tier the manifest declares about itself** | Privilege boundary |

Fail-closed rules: unsigned remotes are unmountable; local-origin unsigned modules degrade to `unsigned-local` (READ_ONLY_HOST_APIS only); missing manifest ⇒ no mount; SRI mismatch ⇒ hard block with visible error.

## 2. Fields

### Required
| Field | Constraints |
|---|---|
| `extension_id` | Slug `^[a-z0-9][a-z0-9._-]{1,63}$`. Immutable identity. |
| `display_name` | Non-empty. |
| `version` | SemVer of the extension. |
| `api_version` | Contract targeted; host enforces same major, host-minor ≥ manifest-minor (`is_compatible`). |

### Trust & integrity
| Field | Notes |
|---|---|
| `publisher` | Signing identity in the trust root. REQUIRED when signed. |
| `signature` | Hex Ed25519 over canonical bytes. REQUIRED when signed. Canonicalization: deterministic serialization with `signature` removed — never re-serialize by hand; use `RuntimeExtension.canonical_bytes()`. |
| `sri_hash` | SHA3-256 hex of the ESM bundle. Required for any cross-origin entry. |
| `remote_entry` | ESM URL for dynamic import after verification. |

### Capabilities & permissions
| Field | Notes |
|---|---|
| `capabilities[]` | Subset of KNOWN_CAPABILITIES: `routes`, `navigation`, `lifecycle`, `runs:read`, `scenarios:read`. Unknown values are contract violations. Today all capabilities are read-oriented; the FIRST mutating capability must land together with tier-gated TRUSTED_HOST_APIS. |
| `required_permissions[]` | Free-form permission nodes surfaced to operators pre-mount. |

### Routing & lifecycle
| Field | Notes |
|---|---|
| `routes[].path/label/icon?/required_role?` | Declared SPA routes contributed under the extension host. |
| `nav_group` | Target nav section (default `extensions`). |
| `lifecycle.on_mount / on_unmount / on_error` | Exported hook names in the remote module; invoked by the host around mount/unmount and on render errors (failure isolation). |

### Compatibility
`compatibility_version` (minimum host) and/or `compatible_runtime_versions[]` — advisory today; enforcement point is the host loader's api_version gate.

## 3. Tier classification (authoritative, backend-owned)

On successful signature verification, `/api/v1/extensions/verify-publisher` returns:

```json
{ "valid": true, "tier": "official" | "community", "reason": "signature-verified", ... }
```

- `official`: publisher identity is listed in `AGENTV_OFFICIAL_PUBLISHERS` (comma-separated).
- `community`: valid signature from any other trust-root publisher.
- Failures return `valid:false` with tier `unsigned-local` or `invalid-signature` plus a machine-readable `reason` (`missing-signature`, `missing-publisher`, `unknown-publisher`, `contract-violation`, `signature-mismatch`).

The frontend consumes `data.tier` exclusively. A manifest field claiming `tier: official` has NO effect — this closed the self-promotion trap.

## 4. Mount pipeline (host side)

1. Fetch `remote_entry` → byte buffer.
2. Verify SRI (`sri_hash`) → else `sri_failed`.
3. Blob-URL + dynamic `import()` → module must export `manifest`.
4. Structural validation → violations list ⇒ `contract_violation` screen.
5. `POST verify-publisher` → resolveTier (authoritative) ⇒ failure ⇒ `publisher_failed`.
6. Mount inside ExtensionHostProvider(tier) with capability-scoped APIs; unsigned-local renders the LOCAL warning strip.


---

## Reference Walkthrough: Signed Community Manifest

```json
{
  "extension_id": "control-plane-fleet",
  "display_name": "Control Plane — Fleet",
  "version": "2.3.1",
  "api_version": "1.0.0",
  "compatibility_version": ">=2.0.0",
  "compatible_runtime_versions": ["2.0.0", "2.1.0"],
  "capabilities": ["routes", "navigation", "runs:read"],
  "required_permissions": [],
  "routes": [
    { "path": "/cp/fleet", "label": "Fleet Overview", "icon": "server" },
    { "path": "/cp/fleet/packs", "label": "Managed Packs", "required_role": "System Admin" }
  ],
  "nav_group": "extensions",
  "remote_entry": "https://cp.acme.example.com/remote/fleet.esm.js",
  "sri_hash": "9f1c…e70a",
  "publisher": "acme-platform",
  "signature": "5b2d…88f1",
  "lifecycle": { "on_mount": "cpOnMount", "on_unmount": "cpOnUnmount", "on_error": "cpOnError" }
}
```

Walkthrough notes:

- `sri_hash` is the SHA3-256 of the exact ESM bytes at `remote_entry`; a
  single flipped bit hard-blocks the mount before any code executes.
- `signature` covers canonical manifest bytes with the `signature` field
  removed — computed by the publisher via
  `RuntimeExtension.canonical_bytes()`; hand-rolled JSON re-serialization
  will fail verification.
- On verify-publisher success, the response's authoritative `tier` decides
  capability scope: this publisher is **not** in
  `AGENTV_OFFICIAL_PUBLISHERS`, so the host mounts it as `community`.
- `/cp/fleet/packs` is nav-gated to `System Admin` via `required_role`;
  RBAC enforcement still happens server-side per API call — the route flag
  is presentation gating only.
- If `cpOnError` is exported, render-time failures inside the remote are
  contained by the host error boundary and reported to the hook instead of
  crashing the OSS shell.
