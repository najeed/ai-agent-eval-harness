"""
Public API surface tests for the RuntimeExtension extension contract.

The contract is SemVer-guaranteed for this release: within 1.x the surface is
additive-only. These tests lock the guaranteed behaviors so accidental breaking
changes fail CI.
"""

from __future__ import annotations

import json

import pytest

import agentv_runtime
from agentv_runtime.extension_contract import (
    EXTENSION_CONTRACT_STATUS,
    EXTENSION_CONTRACT_VERSION,
    ExtensionContractError,
    ExtensionLifecycle,
    ExtensionRoute,
    RuntimeExtension,
    is_compatible,
    parse_semver,
    validate_remote_module_exports,
)

VALID_MANIFEST = {
    "extension_id": "com.acme.control-plane",
    "display_name": "ACME Control Plane",
    "version": "1.2.3",
    "api_version": "1.0.0",
    "capabilities": ["routes", "navigation", "runs:read"],
    "required_permissions": ["runs:read"],
    "routes": [{"path": "/acme/fleet", "label": "Fleet", "required_role": "admin"}],
    "nav_group": "enterprise",
    "remote_entry": "https://cp.example.com/extensions/acme/remoteEntry.js",
    "sri_hash": "sha3-256:deadbeef",
    "publisher": "acme-publisher",
    "signature": "ab" * 64,
    "host_apis": ["runtime.runs.list"],
}


# ---------------------------------------------------------------------------
# Public surface locks (SemVer: additive-only within 1.x)
# ---------------------------------------------------------------------------


def test_contract_version_is_stable_public_api():
    assert EXTENSION_CONTRACT_VERSION == "1.0.0"
    assert EXTENSION_CONTRACT_STATUS == "stable"
    assert agentv_runtime.__extension_contract_version__ == "1.0.0"


def test_package_root_reexports_contract_surface():
    for name in (
        "RuntimeExtension",
        "ExtensionRoute",
        "ExtensionLifecycle",
        "ExtensionContractError",
        "EXTENSION_CONTRACT_VERSION",
        "EXTENSION_CONTRACT_STATUS",
        "extension_api_is_compatible",
    ):
        assert hasattr(agentv_runtime, name), f"public export missing: {name}"


def test_valid_manifest_round_trips_losslessly():
    ext = RuntimeExtension.from_dict(VALID_MANIFEST)
    restored = RuntimeExtension.from_dict(ext.to_dict())

    assert restored == ext  # frozen dataclass equality over full surface
    assert json.loads(restored.canonical_bytes())["extension_id"] == "com.acme.control-plane"


def test_canonical_bytes_excludes_signature_and_is_deterministic():
    ext = RuntimeExtension.from_dict(VALID_MANIFEST)
    b1 = ext.canonical_bytes()
    b2 = RuntimeExtension.from_dict(json.loads(json.dumps(ext.to_dict()))).canonical_bytes()

    assert b1 == b2
    assert b"signature" not in b1  # signature commits to everything else


def test_validate_accepts_fully_signed_manifest():
    ext = RuntimeExtension.from_dict(VALID_MANIFEST)
    assert ext.validate(host_api_version="1.0.0") == []
    assert ext.validate(host_api_version="1.4.2") == []  # newer host, older manifest


def test_validate_requires_signature_by_default():
    unsigned = {**VALID_MANIFEST, "signature": "", "publisher": ""}
    violations = RuntimeExtension.from_dict(unsigned).validate()
    # SRI alone proves bytes, not trust — publisher+signature are mandatory.
    assert any("signature" in v for v in violations)
    assert any("publisher" in v for v in violations)


def test_validate_rejects_unknown_capabilities_and_host_apis():
    bad = {
        **VALID_MANIFEST,
        "capabilities": ["routes", "make_me_admin"],
        "host_apis": ["runtime.kernel.exec"],
    }
    violations = RuntimeExtension.from_dict(bad).validate()
    assert any("make_me_admin" in v for v in violations)
    assert any("runtime.kernel.exec" in v for v in violations)


def test_validate_enforces_semver_and_absolute_routes():
    bad = {
        **VALID_MANIFEST,
        "version": "not-semver",
        "routes": [{"path": "relative/path", "label": "Bad"}],
    }
    violations = RuntimeExtension.from_dict(bad).validate(require_signature=False)
    assert any("SemVer" in v for v in violations)
    assert any("absolute" in v for v in violations)


# ---------------------------------------------------------------------------
# Compatibility policy
# ---------------------------------------------------------------------------


def test_semver_compatibility_rule():
    assert is_compatible("1.0.0", "1.0.0")
    assert is_compatible("1.2.0", "1.5.0")  # older manifest on newer host
    assert not is_compatible("1.6.0", "1.5.0")  # manifest ahead of host minor
    assert not is_compatible("2.0.0", "1.9.9")  # major boundary requires host bump
    assert not is_compatible("garbage", "1.0.0")

    with pytest.raises(ValueError):
        parse_semver("nope")


def test_incompatible_api_version_flagged_against_host():
    ext = RuntimeExtension.from_dict({**VALID_MANIFEST, "api_version": "2.0.0"})
    violations = ext.validate(host_api_version="1.0.0")
    assert any("incompatible" in v for v in violations)


def test_from_dict_missing_required_field_raises_typed_error():
    broken = {k: v for k, v in VALID_MANIFEST.items() if k != "extension_id"}
    with pytest.raises(ExtensionContractError):
        RuntimeExtension.from_dict(broken)


def test_validate_remote_module_exports():
    class FakeModule:
        manifest = VALID_MANIFEST

    assert validate_remote_module_exports(FakeModule) == []

    class BrokenModule:
        manifest = {"hello": True}

    violations = validate_remote_module_exports(BrokenModule)
    assert violations

    class EmptyModule:
        pass

    assert validate_remote_module_exports(EmptyModule) == [
        "Remote module exports no 'manifest' (RuntimeExtension contract)"
    ]


def test_lifecycle_hooks_round_trip():
    ext = RuntimeExtension.from_dict(
        {
            **VALID_MANIFEST,
            "lifecycle": {"on_mount": "onMount", "on_unmount": "onUnmount"},
        }
    )
    assert ext.lifecycle == ExtensionLifecycle(on_mount="onMount", on_unmount="onUnmount")
    assert RuntimeExtension.from_dict(ext.to_dict()).lifecycle == ext.lifecycle

    route = ext.routes[0]
    assert isinstance(route, ExtensionRoute) and route.required_role == "admin"
