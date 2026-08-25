---
title: "Extension Manifest & SRI Specification"
description: "Authoritative specification for sandboxed micro-frontend extensions, dynamic navigation manifests, and Subresource Integrity digests."
---

The **Extension Manifest Specification** (`extension-manifest.schema.json`) governs how third-party and enterprise plugins inject custom navigation items, REST routes, and isolated React micro-frontends into the AgentV Visual Console.

---

## 1. Extension Manifest Schema (`extension-manifest.schema.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AgentV Extension Manifest",
  "type": "object",
  "required": ["manifest_version", "id", "name", "version", "entrypoint", "integrity"],
  "properties": {
    "manifest_version": { "type": "string", "enum": ["1.0.0", "2.0.0"] },
    "id": { "type": "string", "pattern": "^[a-z0-9_-]+$" },
    "name": { "type": "string" },
    "version": { "type": "string" },
    "description": { "type": "string" },
    "entrypoint": { "type": "string" },
    "integrity": {
      "type": "string",
      "pattern": "^(sha3-256|sha3-384|sha3-512|sha384|sha256)-[A-Za-z0-9+/=]+$"
    },
    "routes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "label"],
        "properties": {
          "path": { "type": "string" },
          "label": { "type": "string" },
          "icon": { "type": "string" },
          "group": { "type": "string" },
          "badge": { "type": "string" },
          "required_role": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "permissions": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

---

## 2. Subresource Integrity (SRI) Verification

The Visual Console's `RemoteComponentLoader` verifies the remote ESM bundle before execution:

1. **Digest Fetching**: The loader fetches the raw script text from `entrypoint`.
2. **Cryptographic Validation**:
   - The browser computes the digest using WebCrypto or FIPS 202 SHA-3.
   - If the computed digest does not match the manifest's `integrity` string, loading is aborted immediately with a `SecurityError`.
3. **Sandboxed Isolation**:
   - Verified components mount inside an isolated iframe sandbox with `allow-scripts` and communicate with the host console via origin-checked `postMessage` envelopes.
