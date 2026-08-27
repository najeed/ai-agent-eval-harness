# Scenario Pack Specification — Exhaustive Guide

**Manifest:** `pack.yaml` (pack root) · **Schema:** `scenario-pack.schema.json` · **Installer:** `eval_runner.catalog.install_pack` · **Sample:** `samples/packs/sample-pack/`

Companion specs: [`spec/aes/`](../aes/AES_SCHEMA_EXHAUSTIVE_GUIDE.md) (the scenarios a pack contains) · [`spec/agent-targets/`](../agent-targets/AGENT_TARGETS_EXHAUSTIVE_GUIDE.md).

---

## 1. Purpose

A Scenario Pack is the distribution unit for curated AES scenarios: a directory (or zip/tar.gz of one) whose root carries a `pack.yaml` manifest. `agentv install <path>` copies it into the catalog namespace with **fail-closed integrity verification**, then re-indexes.

There is **no upstream registry in OSS** — bare names like `finance-FINRA@1.2.3` are refused by design. Packs come from sources that exist: a local checkout, or an archive you already have.

## 2. Layout

```
my-pack/
├── pack.yaml                  # REQUIRED manifest (this spec)
└── scenarios/
    └── any_scenario.json      # AES documents (spec/aes)
```

Archives must contain either the pack root directly, or exactly one top-level folder wrapping it.

## 3. Manifest fields (`pack.yaml`)

| Field | Req | Default | Semantics |
|---|---|---|---|
| `name` | ✔ | — | Install namespace slug `^[a-z0-9][a-z0-9._-]{0,63}$`. Target: `industries/<name>/`. |
| `flavor` | – | `STANDARD` | Regulatory/vertical segment (`FINRA`, `HIPAA`, …). |
| `version` | – | `latest` | Version segment; prefer the git ref tag for repo-hosted packs. |
| `description` | – | — | Informational only. |
| `files` | – | `{}` | **Tamper-evidence map**: relative path → lowercase sha256 hex. See §4. |
| `scenarios[]` | – | `[]` | Informational index (`id`, `path`). |

Unknown keys are preserved (forward-compatible), but only the fields above drive behavior.

## 4. Integrity model (fail-closed)

- For every entry in `files`, the installer computes sha256 over file bytes and compares to the manifest. **Any mismatch aborts installation before a single byte is copied into `industries/`** and prints each offending path.
- Listed files that are missing also fail (hash of nothing never matches).
- Unlisted files are copied but recorded as unverified: `pack_manifest.json.checksums_enforced=false` tells consumers whether the install was digest-audited.
- Recommendation: always ship `files` covering every payload artifact.

## 5. Install pipeline

1. **Resolve source**: existing dir | `.zip` | `.tar.gz`/`.tgz`. Anything else (bare name, remote URL) is refused with guidance.
2. **Stage**: archives extract into `~/.aes` jailed staging (`<root>/.aes/pack_staging/<digest>_label`) using PEP-706 data-filter extraction.
3. **Read manifest** → require non-empty `name` (never guess a namespace).
4. **Verify checksums** (§4).
5. **Archive-on-reinstall**: an existing target moves to `<target>/.archived/<timestamp>_<name>` (no data loss).
6. **Copy** staged files → write `pack_manifest.json` (`verified_files`, `checksums_enforced`, transport, source, timestamp).
7. **Reindex** the ScenarioCatalog.

## 6. Installed artifacts

`industries/<name>/<flavor>/<version>/pack_manifest.json`:

```json
{
  "pack": "sample", "flavor": "STANDARD", "version": "1.0.0",
  "transport": "local-dir", "source": "<path given>",
  "installed_at": "<iso8601>",
  "verified_files": 1, "checksums_enforced": true
}
```

## 7. Authoring checklist

- Every scenario validates against `spec/aes`; starter nodes carry at least one oracle (`state_hygiene` rule) so the minimum-oracle compile rule accepts them.
- Generate the checksum map mechanically:
  `sha256sum $(find . -type f ! -name 'pack.yaml')`.
- Bump `version` per release; never mutate a published version in place.

## 8. Validation

```bash
python - <<'PY'
import yaml, jsonschema
doc = yaml.safe_load(open("pack.yaml"))
schema = json.load(open("spec/scenario-pack/scenario-pack.schema.json"))
jsonschema.validate(doc, schema)
PY
```

Contract test: `tests/unit/spec/test_spec_contracts.py::test_sample_pack_matches_schema`.

---

## Reference Walkthrough: Sample Pack, End to End

### 1. Source tree (exactly as committed at `samples/packs/sample-pack/`)

```
sample-pack/
├── pack.yaml
└── scenarios/
    └── sample_greeting.json
```

`pack.yaml`:

```yaml
name: sample
flavor: STANDARD
version: 1.0.0
description: Sample AgentV scenario pack for testing 'agentv install <path>'.
files:
  scenarios/sample_greeting.json: 2302b5db710c587f70332874aba638ce60b25d44cacb88e9a8d95f36fd67c32c
```

### 2. Install command

```bash
agentv install samples/packs/sample-pack
```

Installer log:

```
[Catalog] Installing 'sample-STANDARD@1.0.0' from samples/packs/sample-pack [local-dir]
[Catalog] ✅ Installed 1 file(s) -> industries/sample/STANDARD/1.0.0  (checksums verified)
[Catalog] Re-indexed 37 total scenarios.
```

### 3. Resulting installed artifacts

```
industries/sample/STANDARD/1.0.0/
├── pack_manifest.json
└── scenarios/
    └── sample_greeting.json
```

`pack_manifest.json`:

```json
{
  "pack": "sample",
  "flavor": "STANDARD",
  "version": "1.0.0",
  "installed_at": "2026-08-25T12:04:51.204418",
  "transport": "local-dir",
  "source": "samples/packs/sample-pack",
  "verified_files": 1,
  "checksums_enforced": true
}
```

Walkthrough notes:

- `checksums_enforced: true` proves the digest map was present and every
  listed file matched before copying — an auditor can re-hash the installed
  payload and reproduce the verdict.
- A second install of the same source moves the first into
  `industries/sample/STANDARD/.archived/<timestamp>_1.0.0/` (no data loss).
- Tampering with `scenarios/sample_greeting.json` in the SOURCE after writing
  `pack.yaml` aborts the install with the offending path printed; nothing is
  copied into `industries/`.
