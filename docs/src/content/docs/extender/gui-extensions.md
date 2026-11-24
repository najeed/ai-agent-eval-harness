---
title: Visual Console GUI Extensibility & Micro-Frontends
description: Learn how to build and integrate custom GUI micro-frontends, navigation routes, and sidebar badges into the AgentV Visual Console without modifying core source code.
---

The Visual Console loads signed ESM releases without rebuilding the host.
Extensions execute as React components in the host; this is a publisher trust
boundary, not an iframe sandbox. Production rejects unsigned and community
modules and mounts only backend-verified official publishers.

## Build a host React peer

Export a React component and keep `react`/`react-dom` external so imports resolve
to the host singleton. Keep imported relative chunks inside the entry directory.
Use the authenticated host API supplied to mounted pages for requests and context
switching rather than deriving permissions from client-controlled labels.

The host page contract includes `context`, `switchContext`, `authorizedFetch` and
the declared route. Server endpoints must independently enforce permissions and
the provider-owned active scope. Navigation fields such as badges and icons are
presentation only.

## Declare a release

Save a declaration such as `extension-declaration.json` alongside your build:

```json
{
  "extension_id": "fleet-monitor",
  "display_name": "Fleet Monitor",
  "version": "1.0.0",
  "api_version": "1.0.0",
  "compatibility_version": "2.0.0",
  "compatible_runtime_versions": ["2.0.0"],
  "capabilities": ["routes", "navigation", "runs:read"],
  "required_permissions": ["runs:read"],
  "routes": [{"path": "/fleet", "label": "Fleet Monitor", "required_permissions": ["runs:read"]}],
  "navigation": [{"path": "/fleet", "title": "Fleet Monitor", "group": "Govern"}],
  "nav_group": "extensions",
  "host_apis": ["runtime.runs.list"],
  "react_peer": true,
  "lifecycle": {}
}
```

This is a frontend release declaration, not the more limited generic JSON Schema.
The publisher supplies `remote_entry`, `sri_hash`, `verified_chunks`, `publisher`
and `signature`, bound to the actual entry/chunk bytes.

## Publish and activate

Configure a publisher identity and trusted public key before publishing. The
example identity must be authorized as an official publisher by the deployment
to load in production; publishing alone does not confer that status.

```bash
agentv extension publish --entry dist/fleet.js --extension-id fleet-monitor --publisher PUBLISHER_ID --extension-version 1.0.0 --manifest extension-declaration.json --activate
agentv extension verify --extension-id fleet-monitor --extension-version 1.0.0
```

The publisher signs and atomically installs the release under the configured
artifact root (`AGENTV_EXTENSION_ARTIFACT_DIR`, default `.agentv/extensions`).
It writes the sidecar and integrity map used by pre-execution validation.
Production requires `react_peer: true`; declare all relative chunks and do not
bundle a second React runtime.

```bash
agentv extension activate --extension-id fleet-monitor --extension-version 1.0.0
agentv extension rollback --extension-id fleet-monitor --extension-version 1.0.0
agentv extension unpublish --extension-id fleet-monitor --extension-version 1.0.0
```

Rollback selects a retained verified version. Repair requires bytes matching a
retained signed release and an entry path; it cannot bless arbitrary new bytes.
Use `agentv extension repair --help` for its required arguments.

## Loader policy

The host fetches entry bytes and validates SRI, reads the signed sidecar, checks
API/route/permission declarations and publisher trust, then verifies relative
chunks. It imports verified in-memory blobs to avoid a second unverified fetch.
Cross-origin releases require pinned integrity and the same publisher checks.
Self-declared trust tiers never override backend classification.

An error boundary contains rendering failures, but does not isolate a module's
JavaScript privileges. `ExtensionRuntimeContextApi` is the supported host
communication surface; `postMessage` is not an iframe integration protocol here.
