"""
tests/unit/console/test_extension_host_contracts.py
Contract locks for the Runtime Extension Host ([D2]).

1. Manifest validation — signed-valid passes; an unknown capability violates
   (reuses agentv_runtime.extension_contract.RuntimeExtension.validate).
2. Capability authorization — the 'unsigned-local' tier grant is capped at
   READ_ONLY_HOST_APIS and excludes every trusted-tier entry.
3. Host-API authorization — can()/canCallHostApi() is default-deny for every
   name outside the tier allow-list (the REAL TypeScript predicate is
   executed from src/types/extension-contract.ts via the docmodel build).
4. Failure isolation — RemoteErrorBoundary renders ExtensionLoadError when a
   child throws. Behavioral coverage lives in
   ui/visual-console/tests/document-model/remoteErrorBoundary.test.ts
   (jsdom-free direct method calls, run by `npm run test:docmodel`);
   this suite asserts the extraction + host wiring statically.
"""

import json
import subprocess
from pathlib import Path

from agentv_runtime.extension_contract import (
    EXTENSION_CONTRACT_VERSION,
    KNOWN_CAPABILITIES,
    KNOWN_HOST_APIS,
    READ_ONLY_HOST_APIS,
    ExtensionRoute,
    RuntimeExtension,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = PROJECT_ROOT / "ui" / "visual-console"
CONTRACT_TS = UI_ROOT / "src" / "types" / "extension-contract.ts"
BOUNDARY_TSX = UI_ROOT / "src" / "components" / "RemoteErrorBoundary.tsx"
APP_TSX = UI_ROOT / "src" / "App.tsx"
TEST_DIST = UI_ROOT / "test-dist"


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _ensure_compiled_contract() -> Path:
    """
    Returns the compiled extension-contract module, rebuilding the docmodel
    TS harness when missing or stale relative to its sources.
    """
    compiled = TEST_DIST / "src" / "types" / "extension-contract.js"
    sources = [CONTRACT_TS, BOUNDARY_TSX]
    stale = not compiled.exists() or any(
        s.exists() and s.stat().st_mtime > compiled.stat().st_mtime for s in sources
    )
    if stale:
        tsc_bin = UI_ROOT / "node_modules" / "typescript" / "bin" / "tsc"
        assert tsc_bin.exists(), (
            "TypeScript toolchain missing — run `npm install --prefix ui/visual-console`"
        )
        subprocess.run(
            ["node", str(tsc_bin), "-p", "tsconfig.test.json"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(UI_ROOT),
        )
    assert compiled.exists(), "docmodel build did not emit extension-contract.js"
    return compiled


def _eval_ts_contract(payload_expr: str) -> dict:
    """Executes a JSON-producing expression against the REAL TS contract."""
    module_uri = _ensure_compiled_contract().as_uri()
    script = f'import("{module_uri}").then(m => console.log(JSON.stringify({payload_expr})))'
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )
    assert proc.returncode == 0, f"TS contract harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# 1. Manifest validation
# ---------------------------------------------------------------------------


def _signed_manifest(**overrides) -> RuntimeExtension:
    fields = dict(
        extension_id="ext.demo",
        display_name="Demo Extension",
        version="1.2.3",
        api_version=EXTENSION_CONTRACT_VERSION,
        capabilities=["routes", "navigation"],
        routes=[ExtensionRoute(path="/demo-ext", label="Demo Extension")],
        remote_entry="https://cdn.example.com/demo.esm.js",
        sri_hash="sha3-256-" + ("0a" * 32),
        publisher="acme-corp",
        signature="de" * 64,
        tier="community",
    )
    fields.update(overrides)
    return RuntimeExtension(**fields)


def test_manifest_validation_signed_valid_passes_and_unknown_capability_violates():
    ext = _signed_manifest()
    assert ext.validate() == []

    rogue = "make_coffee"
    assert rogue not in KNOWN_CAPABILITIES
    violations = _signed_manifest(capabilities=["routes", rogue]).validate()
    assert any("Unknown capabilities declared" in v for v in violations), violations
    assert any(rogue in v for v in violations), violations


# ---------------------------------------------------------------------------
# 2. Capability / tier authorization
# ---------------------------------------------------------------------------


def test_capability_authorization_unsigned_local_is_read_only_and_excludes_trusted():
    # Server-side truth: read-only surface is a strict subset of known APIs.
    assert READ_ONLY_HOST_APIS <= KNOWN_HOST_APIS

    # Client-side policy mirror (real implementation, executed under node):
    out = _eval_ts_contract(
        "{"
        "'unsigned': m.hostApisForTier('unsigned-local'), "
        "'invalidSignature': m.hostApisForTier('invalid-signature'), "
        "'readOnly': m.READ_ONLY_HOST_APIS, "
        "'trusted': m.TRUSTED_HOST_APIS"
        "}"
    )
    for tier_grant in (out["unsigned"], out["invalidSignature"]):
        for api in tier_grant:
            assert api in out["readOnly"], f"{api} granted beyond READ_ONLY surface"
        for trusted_api in out["trusted"]:
            assert trusted_api not in tier_grant, (
                f"{trusted_api} must never be granted to an unverified tier"
            )


# ---------------------------------------------------------------------------
# 3. Host-API authorization (default-deny outside tier allow-list)
# ---------------------------------------------------------------------------


def test_host_api_authorization_can_denies_everything_outside_tier_list():
    outside_names = [
        "runtime.evidence.write",
        "runtime.scenarios.delete",
        "runtime.runs.purge",
        "admin.shell.exec",
        "totally.unknown.future.api",
    ]
    for name in outside_names:
        assert name not in KNOWN_HOST_APIS
    probe = ",".join(json.dumps(n) for n in outside_names)
    tiers = ["official", "community", "unsigned-local", "invalid-signature"]

    for tier in tiers:
        allowed = set(_eval_ts_contract(f"m.hostApisForTier({json.dumps(tier)})"))
        denied = _eval_ts_contract(
            f"[{probe}].filter(c => !m.canCallHostApi({json.dumps(tier)}, c))"
        )
        assert sorted(denied) == sorted(outside_names), (
            f"tier {tier} granted calls outside its allow-list: "
            f"{sorted(set(outside_names) - set(denied))}"
        )
        # Consistency: everything actually in the allow-list passes.
        for api in allowed:
            verdict = _eval_ts_contract(f"m.canCallHostApi({json.dumps(tier)}, {json.dumps(api)})")
            assert verdict is True


# ---------------------------------------------------------------------------
# 4. Failure isolation (static wiring; behavior covered by the docmodel suite)
# ---------------------------------------------------------------------------


def test_failure_isolation_boundary_renders_extension_load_error_on_child_throw():
    assert BOUNDARY_TSX.exists(), "RemoteErrorBoundary must stay extracted for jsdom-free testing"

    src = BOUNDARY_TSX.read_text(encoding="utf-8")
    assert "static getDerivedStateFromError" in src
    assert "hasError: true" in src
    assert "<ExtensionLoadError" in src
    assert "this.state.hasError" in src

    app_src = APP_TSX.read_text(encoding="utf-8")
    # The host wires the extracted boundary around remote mounting...
    assert "from './components/RemoteErrorBoundary'" in app_src
    assert "<RemoteErrorBoundary entryUrl={" in app_src
    # ...and no longer carries a divergent inline copy of the class.
    assert "class RemoteErrorBoundary" not in app_src
