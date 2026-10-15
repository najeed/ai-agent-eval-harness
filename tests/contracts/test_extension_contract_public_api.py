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
    ExtensionNavigation,
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
        "ExtensionNavigation",
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


def test_routes_are_mountable_without_presentation_and_navigation_is_signed():
    manifest = {
        **VALID_MANIFEST,
        "routes": [{"path": "/generic", "required_permissions": ["runs:read"]}],
        "navigation": [
            {
                "path": "/generic",
                "id": "generic-nav",
                "title": "Generic",
                "icon": "shield",
                "group": "Extensions",
                "badge": "NEW",
                "provenance": "publisher",
            }
        ],
    }
    extension = RuntimeExtension.from_dict(manifest)
    assert extension.validate() == []
    assert isinstance(extension.navigation[0], ExtensionNavigation)
    published_route = extension.to_dict()["routes"][0]
    assert "label" not in published_route
    assert "required_role" not in published_route
    assert b'"badge":"NEW"' in extension.canonical_bytes()
    assert b'"required_role":null' not in extension.canonical_bytes()
    assert (
        extension.canonical_bytes()
        != RuntimeExtension.from_dict(
            {**manifest, "navigation": [{**manifest["navigation"][0], "icon": "activity"}]}
        ).canonical_bytes()
    )


def test_duplicate_signed_route_or_navigation_metadata_is_rejected():
    duplicate_route = RuntimeExtension.from_dict(
        {**VALID_MANIFEST, "routes": [{"path": "/generic"}, {"path": "/generic"}]}
    )
    assert any("Duplicate route path" in item for item in duplicate_route.validate())
    duplicate_navigation = RuntimeExtension.from_dict(
        {
            **VALID_MANIFEST,
            "navigation": [
                {"path": "/acme/fleet", "id": "duplicate"},
                {"path": "/acme/fleet", "id": "duplicate"},
            ],
        }
    )
    violations = duplicate_navigation.validate()
    assert any("Duplicate navigation path" in item for item in violations)
    assert any("Duplicate navigation id" in item for item in violations)


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


# ---------------------------------------------------------------------------
# [D2] Trust tier contract (additive within 1.x)
# ---------------------------------------------------------------------------


def _base_valid_manifest() -> dict:
    return {
        "extension_id": "com.acme.fleet",
        "display_name": "Fleet Analytics",
        "version": "1.0.0",
        "api_version": "1.0.0",
        "capabilities": ["routes", "navigation"],
        "routes": [{"path": "/fleet", "label": "Fleet"}],
        "remote_entry": "/static/extensions/fleet.js",
        "sri_hash": "sha3-256-QUJDRA==",
        "publisher": "acme",
        "signature": "00" * 64,
        "host_apis": ["runtime.runs.list"],
    }


def test_tier_round_trips_losslessly():
    manifest = {**_base_valid_manifest(), "tier": "community"}
    ext = RuntimeExtension.from_dict(manifest)
    assert ext.tier == "community"
    assert ext.to_dict()["tier"] == "community"


def test_tier_defaults_to_none():
    ext = RuntimeExtension.from_dict(_base_valid_manifest())
    assert ext.tier is None


def test_unknown_tier_rejected():
    ext = RuntimeExtension.from_dict({**_base_valid_manifest(), "tier": "superuser"})
    violations = ext.validate()
    assert any("trust tier" in v for v in violations)


def test_all_declared_tiers_accepted():
    for tier in ("official", "community", "unsigned-local", "invalid-signature"):
        ext = RuntimeExtension.from_dict({**_base_valid_manifest(), "tier": tier})
        assert ext.validate() == []


def test_read_only_host_api_registry_is_subset():
    from agentv_runtime.extension_contract import KNOWN_HOST_APIS, READ_ONLY_HOST_APIS

    assert READ_ONLY_HOST_APIS <= KNOWN_HOST_APIS


# ---------------------------------------------------------------------------
# [F1] Single truth-version namespace
# ---------------------------------------------------------------------------


def test_versions_namespace_is_single_source():
    import eval_runner.execution_ir as ir_mod
    import eval_runner.verifier as verifier_mod
    from agentv_runtime import extension_contract as ec, versions as V
    from eval_runner.console.routes import evidence as ev

    assert ec.EXTENSION_CONTRACT_VERSION == V.EXTENSION_CONTRACT_VERSION == "1.0.0"
    assert ir_mod.EXECUTION_IR_VERSION == V.EXECUTION_IR_VERSION == "2.0.0"
    assert verifier_mod.VC_V3_SCHEMA_VERSION == V.VC_SCHEMA_VERSION == "3.0.0"
    assert ev.VERIFICATION_PACKAGE_VERSION == V.VERIFICATION_PACKAGE_VERSION


def test_extension_contract_parse_semver_invalid_int():
    with pytest.raises(ValueError, match="Not a SemVer core"):
        parse_semver("1.invalid.0")


def test_runtime_extension_from_dict_non_dict():
    with pytest.raises(ExtensionContractError, match="manifest must be an object"):
        RuntimeExtension.from_dict(["not", "a", "dict"])


def test_runtime_extension_validation_missing_core_fields_and_bad_types():
    # Missing required core fields
    ext_missing = RuntimeExtension.from_dict(
        {
            "extension_id": "",
            "display_name": "",
            "version": "",
            "remote_entry": "",
            "sri_hash": "",
        }
    )
    v = ext_missing.validate()
    assert any("extension_id and display_name are required" in msg for msg in v)
    assert any("version is required" in msg for msg in v)
    assert any("remote_entry is required" in msg for msg in v)
    assert any("sri_hash (integrity digest) is required" in msg for msg in v)


def test_runtime_extension_validation_routes_and_slots_and_chunks():
    base = _base_valid_manifest()

    # Routes declared without "routes" or "navigation" in capabilities
    m_no_route_cap = {
        **base,
        "capabilities": ["runs:read"],
        "routes": [{"path": "/test/path"}],
    }
    v1 = RuntimeExtension.from_dict(m_no_route_cap).validate()
    assert any('Manifest declares routes but does not declare "routes"' in msg for msg in v1)

    # Slot validation
    m_bad_slot = {**base, "slot": "sidebar"}
    v2 = RuntimeExtension.from_dict(m_bad_slot).validate()
    assert any("Unknown extension slot" in msg for msg in v2)

    m_header_no_cap = {**base, "slot": "header", "capabilities": ["routes", "navigation"]}
    v3 = RuntimeExtension.from_dict(m_header_no_cap).validate()
    assert any('Header slot requires the "header" capability' in msg for msg in v3)

    # react_peer and verified_chunks type violations
    m_bad_types = {
        **base,
        "react_peer": "not_a_bool",
        "verified_chunks": "not_a_dict",
    }
    v4 = RuntimeExtension.from_dict(m_bad_types).validate()
    assert any("react_peer must be a boolean" in msg for msg in v4)
    assert any("verified_chunks must be a map" in msg for msg in v4)

    # verified_chunks unsafe path and integrity checks
    m_bad_chunks = {
        **base,
        "verified_chunks": {
            "/absolute/path.js": "sha3-256-abc",
            "../traversal.js": "sha3-256-abc",
            "safe.js": "sha256-wrong-prefix",
        },
    }
    v5 = RuntimeExtension.from_dict(m_bad_chunks).validate()
    assert any("verified_chunks path must be a safe relative path" in msg for msg in v5)
    assert any("verified_chunks integrity must be sha3-256 SRI" in msg for msg in v5)


def test_runtime_extension_validation_route_and_navigation_details():
    base = _base_valid_manifest()

    # Route bad label and bad permissions
    m_route_details = {
        **base,
        "routes": [
            {"path": "/acme/fleet", "label": 12345, "required_permissions": [123]},
        ],
    }
    v1 = RuntimeExtension.from_dict(m_route_details).validate()
    assert any("Route label must be a string" in msg for msg in v1)
    assert any("Route permissions must be non-empty strings" in msg for msg in v1)

    # Navigation path not matching route, bad id, duplicate id, bad string fields, bad icon
    m_nav_details = {
        **base,
        "navigation": [
            {
                "path": "/acme/fleet",
                "id": "",
                "title": 123,
                "icon": "",
            },
            {
                "path": "/acme/unknown",
                "id": "dup_id",
            },
            {
                "path": "/acme/fleet",
                "id": "dup_id",
            },
            {
                "path": "/acme/fleet",
                "title": "Fleet Overview",
            },
        ],
    }
    v2 = RuntimeExtension.from_dict(m_nav_details).validate()
    assert any("Navigation path must name a declared route" in msg for msg in v2)
    assert any("Navigation id must be a non-empty string" in msg for msg in v2)
    assert any("Navigation title must be a string when supplied" in msg for msg in v2)
    assert any("Navigation icon must be a non-empty string when supplied" in msg for msg in v2)


def test_validate_remote_module_exports_non_dict_manifest():
    class DummyModule:
        default = "not-a-dict-manifest"

    violations = validate_remote_module_exports(DummyModule)
    assert violations == []
