"""
agentv_runtime.extension_contract
RuntimeExtension contract — PUBLIC API SURFACE, SemVer-guaranteed (v1.0.0).

STABILITY GUARANTEE
===================
This module is covered by the AgentV Runtime public API SemVer guarantee:

  - Within major version 1.x: strictly ADDITIVE. Existing fields, enums,
    helper signatures and canonical serialization never change semantics.
    New fields arrive optional with safe defaults.
  - Any removal, rename, type change or semantic change REQUIRES a bump to
    2.0.0 of EXTENSION_CONTRACT_VERSION.
  - The canonical_bytes() serialization is part of the guarantee: manifests
    signed under 1.x verify identically across all 1.x runtimes.

The OSS Runtime owns ONLY:
    Runtime GUI Shell + Runtime extension host + capability-scoped extension APIs

SRI integrity digests are necessary but NOT sufficient: a manifest may change
its URL and matching digest at will. Trust requires a SIGNED manifest with
explicit publisher identity and capability declarations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

EXTENSION_CONTRACT_VERSION = "1.0.0"
EXTENSION_CONTRACT_STATUS = "stable"  # SemVer-guaranteed public API


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parses 'MAJOR.MINOR.PATCH' (pre-release suffixes tolerated)."""
    core = version.strip().lstrip("v").split("-", 1)[0]
    parts = core.split(".")
    if len(parts) < 2:
        raise ValueError(f"Not a SemVer core: {version!r}")
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError as err:
        raise ValueError(f"Not a SemVer core: {version!r}") from err
    return major, minor, patch


def is_compatible(manifest_api_version: str, host_api_version: str) -> bool:
    """
    SemVer compatibility rule for extension manifests targeting a host.

    Compatible when majors match AND the manifest's minor does not exceed the
    host's minor (a newer host may serve older manifests; never vice versa).
    Patch level is irrelevant.
    """
    try:
        mj, mn, _ = parse_semver(manifest_api_version)
        hmj, hmn, _ = parse_semver(host_api_version)
    except ValueError:
        return False
    return mj == hmj and mn <= hmn


class ExtensionContractError(ValueError):
    """Raised when an extension manifest violates the runtime contract."""


# Capability and host-API registries are ADDITIVE within 1.x: new entries are
# non-breaking; removal or semantic change of an existing entry is breaking.
KNOWN_CAPABILITIES = {
    "routes",  # contribute SPA routes
    "navigation",  # contribute nav entries
    "lifecycle",  # mount/unmount/error hooks
    "runs:read",  # scoped host API: read runs
    "scenarios:read",  # scoped host API: read scenarios
}

KNOWN_HOST_APIS = {
    "runtime.health.get",
    "runtime.runs.list",
    "runtime.runs.get",
    "runtime.scenarios.list",
    "runtime.evidence.link",
}


@dataclass(frozen=True)
class ExtensionRoute:
    path: str
    label: str
    icon: str | None = None
    required_role: str | None = None


@dataclass(frozen=True)
class ExtensionLifecycle:
    on_mount: str | None = None  # exported hook names in the remote module
    on_unmount: str | None = None
    on_error: str | None = None


@dataclass(frozen=True)
class RuntimeExtension:
    """
    Declarative, signable extension manifest.

    The `signature` covers the canonical JSON of every other field; the host
    MUST verify it against the publisher's public key BEFORE mounting, and
    MUST treat extension code as privileged (CSP/worker isolation where
    feasible). An SRI digest alone never grants trust.
    """

    extension_id: str
    display_name: str
    version: str  # SemVer of the extension itself
    api_version: str = EXTENSION_CONTRACT_VERSION  # contract version targeted
    compatibility_version: str = ""  # minimum AgentV host version required
    compatible_runtime_versions: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=lambda: ["routes", "navigation"])
    required_permissions: list[str] = field(default_factory=list)
    routes: list[ExtensionRoute] = field(default_factory=list)
    nav_group: str = "extensions"
    remote_entry: str = ""
    sri_hash: str = ""  # sha3-256 integrity digest of the ESM bundle
    publisher: str = ""  # signing publisher identity (required for trust)
    signature: str = ""  # hex signature over canonical manifest bytes
    lifecycle: ExtensionLifecycle = field(default_factory=ExtensionLifecycle)
    host_apis: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        # asdict() recursively converts nested frozen dataclasses
        # (ExtensionRoute / ExtensionLifecycle); signature is preserved as a
        # field so consumers can persist the full signed manifest.
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        """Deterministic serialization that `signature` commits to."""
        import json

        payload = self.to_dict()
        payload.pop("signature", None)
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeExtension:
        try:
            routes = [
                r if isinstance(r, ExtensionRoute) else ExtensionRoute(**r)
                for r in data.get("routes", [])
            ]
            lc_raw = data.get("lifecycle") or {}
            lifecycle = (
                lc_raw if isinstance(lc_raw, ExtensionLifecycle) else ExtensionLifecycle(**lc_raw)
            )
            return cls(
                extension_id=str(data["extension_id"]),
                display_name=str(data["display_name"]),
                version=str(data["version"]),
                api_version=str(data.get("api_version", EXTENSION_CONTRACT_VERSION)),
                compatibility_version=str(data.get("compatibility_version", "")),
                compatible_runtime_versions=list(data.get("compatible_runtime_versions", [])),
                capabilities=list(data.get("capabilities", ["routes", "navigation"])),
                required_permissions=list(data.get("required_permissions", [])),
                routes=routes,
                nav_group=str(data.get("nav_group", "extensions")),
                remote_entry=str(data.get("remote_entry", "")),
                sri_hash=str(data.get("sri_hash", "")),
                publisher=str(data.get("publisher", "")),
                signature=str(data.get("signature", "")),
                lifecycle=lifecycle,
                host_apis=list(data.get("host_apis", [])),
            )
        except KeyError as err:
            raise ExtensionContractError(f"Missing required manifest field: {err}") from err
        except TypeError as err:
            raise ExtensionContractError(f"Malformed manifest structure: {err}") from err

    # ------------------------------------------------------------------
    def validate(
        self, *, require_signature: bool = True, host_api_version: str | None = None
    ) -> list[str]:
        """Contract validation. Returns violation list; empty means valid."""
        violations: list[str] = []

        if not self.extension_id or not self.display_name:
            violations.append("extension_id and display_name are required")
        if not self.version:
            violations.append("version is required")
        if not self.remote_entry:
            violations.append("remote_entry is required")
        if not self.sri_hash:
            violations.append("sri_hash (integrity digest) is required")

        try:
            parse_semver(self.version)
        except ValueError:
            violations.append(f"version must be SemVer: {self.version!r}")

        if not is_compatible(self.api_version, host_api_version or EXTENSION_CONTRACT_VERSION):
            violations.append(
                f"api_version {self.api_version!r} is incompatible with host contract "
                f"{(host_api_version or EXTENSION_CONTRACT_VERSION)!r}"
            )

        if require_signature:
            if not self.publisher:
                violations.append("publisher identity is required for signed manifests")
            if not self.signature:
                violations.append("signature is required: SRI alone proves bytes, not trust")

        unknown_caps = set(self.capabilities) - KNOWN_CAPABILITIES
        if unknown_caps:
            violations.append(f"Unknown capabilities declared: {sorted(unknown_caps)}")

        unknown_apis = set(self.host_apis) - KNOWN_HOST_APIS
        if unknown_apis:
            violations.append(
                f"Undeclared host APIs referenced: {sorted(unknown_apis)} "
                "(extensions must enumerate every host API they call)"
            )

        for route in self.routes:
            if not route.path.startswith("/"):
                violations.append(f"Route path must be absolute: {route.path!r}")

        return violations


def validate_remote_module_exports(module: Any) -> list[str]:
    """
    Post-load validation: the dynamically imported ESM module must export a
    contract-conforming shape before the host mounts it.
    """
    violations: list[str] = []
    manifest = getattr(module, "manifest", None) or getattr(module, "default", None)
    if manifest is None:
        return ["Remote module exports no 'manifest' (RuntimeExtension contract)"]
    if isinstance(manifest, dict):
        try:
            ext = RuntimeExtension.from_dict(manifest)
        except ExtensionContractError as err:
            return [str(err)]
        violations.extend(ext.validate())
    return violations


__all__ = [
    "EXTENSION_CONTRACT_STATUS",
    "EXTENSION_CONTRACT_VERSION",
    "ExtensionContractError",
    "ExtensionLifecycle",
    "ExtensionRoute",
    "KNOWN_CAPABILITIES",
    "KNOWN_HOST_APIS",
    "RuntimeExtension",
    "is_compatible",
    "parse_semver",
    "validate_remote_module_exports",
]
