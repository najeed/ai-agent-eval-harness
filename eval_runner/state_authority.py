"""
eval_runner.state_authority
External State Observation Connectors (P0-05) and Bounded State Capture (P0-06).
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import ipaddress
import json
import logging
import os
import socket
import ssl
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.contracts import EvidenceBoundednessLimits
from eval_runner import config
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)


class StateAuthorityPolicyError(ValueError):
    """Raised when an external-state request violates the egress contract."""


class StateAuthorityKeyMissingError(ValueError):
    """Raised when state authority trust key material is missing, unreadable, or empty."""


def _configured_authority_origins() -> set[str]:
    """Return the explicit egress allow-list for scenario-owned authorities.

    An authority is evidence input, not an arbitrary HTTP client.  Keeping the
    policy in one environment variable makes both CI fixtures and deployments
    declare exactly which authority origins they trust.
    """
    entries = os.getenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "").split(",")
    origins: set[str] = set()
    for entry in entries:
        parsed = urlparse(entry.strip())
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}".lower())
    return origins


def _validate_external_authority_url(url: str) -> str:
    """Validate a connector URL before opening a network connection.

    The URL must target an explicitly configured origin.  Private, loopback,
    link-local, metadata, and otherwise non-global addresses are prohibited
    unless that exact origin is explicitly allow-listed (the latter supports a
    deliberately declared local CI oracle without making localhost generally
    reachable from scenario input).
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StateAuthorityPolicyError("External state authority requires an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise StateAuthorityPolicyError("External state authority URL must not contain credentials")

    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed_origins = _configured_authority_origins()
    if origin not in allowed_origins:
        raise StateAuthorityPolicyError(
            f"External state authority origin is not allow-listed: {origin}"
        )

    try:
        addresses = {
            record[4][0]
            for record in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except OSError as exc:
        raise StateAuthorityPolicyError(
            f"External state authority host could not be resolved: {parsed.hostname}"
        ) from exc

    if not addresses:
        raise StateAuthorityPolicyError("External state authority host resolved to no addresses")
    allow_private = os.getenv("AGENTV_ALLOW_PRIVATE_STATE_AUTHORITIES", "").lower() in ("1", "true")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            is_local_ci_exception = allow_private or (
                ip.is_loopback
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and origin in allowed_origins
            )
            if not is_local_ci_exception:
                raise StateAuthorityPolicyError(
                    f"External state authority resolves to a non-global address: {address}"
                )
    return url


def _safe_default(obj: Any) -> str:
    if inspect.iscoroutine(obj):
        try:
            obj.close()
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.debug("Failed closing unawaited coroutine: %s", exc, exc_info=True)
    return str(obj)


class StateLimitExceededError(ValueError):
    """Raised when state snapshot violates strict boundedness limits."""


def bound_state_snapshot(
    state: Any,
    projection: list[str] | None = None,
    max_bytes: int = EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES,
    max_items: int = EvidenceBoundednessLimits.MAX_INLINE_ITEMS,
) -> tuple[Any, str]:
    """
    Bounded State Capture Contract (P0-06).

    1. If projection selectors are provided (e.g. ['authorizations.*', 'status']),
       extracts only the projected paths from the state.
    2. Computes the authoritative SHA3-256 content hash of the full/projected data.
    3. If serialized bytes exceed max_bytes or list collections exceed max_items,
       returns a bounded truncated structure carrying the exact digest commitment.

    Returns:
        (bounded_state, sha3_256_digest)
    """
    if state is None:
        return None, "sha3_256:" + hashlib.sha3_256(b"null").hexdigest()

    # Step 1: Apply projection if specified
    projected_state = state
    if projection and isinstance(state, dict):
        projected_state = {}
        for path in projection:
            val = PathResolver.resolve(state, path)
            if val is not None:
                parts = path.split(".")
                curr = projected_state
                for part in parts[:-1]:
                    if part not in curr or not isinstance(curr[part], dict):
                        curr[part] = {}
                    curr = curr[part]
                curr[parts[-1]] = copy.deepcopy(val)

    # Step 2: Compute full canonical SHA3-256 digest
    try:
        c_bytes = canonical_json_encode(projected_state)
    except (ValueError, TypeError, OverflowError):
        logger.debug(
            "bound_state_snapshot failed",
            extra={"operation": "bound_state_snapshot"},
            exc_info=True,
        )
        c_bytes = json.dumps(projected_state, sort_keys=True, default=_safe_default).encode("utf-8")
    full_digest = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"

    # Step 3: Check byte size boundary
    if len(c_bytes) <= max_bytes:
        # Check nested item counts
        def _bound_collections(val: Any) -> Any:
            if isinstance(val, list):
                if len(val) > max_items:
                    bounded_items = [_bound_collections(x) for x in val[:max_items]]
                    return {
                        "__BOUNDED_COLLECTION__": {
                            "total_items": len(val),
                            "retained_items": max_items,
                            "items": bounded_items,
                            "truncated": True,
                        }
                    }
                return [_bound_collections(x) for x in val]
            if isinstance(val, dict):
                return {k: _bound_collections(v) for k, v in val.items()}
            return val

        return _bound_collections(projected_state), full_digest

    # Step 4: Oversized state - produce bounded commitment structure
    sample: Any
    if isinstance(projected_state, dict):
        sample = {k: projected_state[k] for k in list(projected_state.keys())[:5]}
    elif isinstance(projected_state, list):
        sample = projected_state[:5]
    else:
        sample = str(projected_state)[:256]

    bounded_repr = {
        "__BOUNDED_STATE__": {
            "status": "BOUNDED_STATE_LIMIT_EXCEEDED",
            "original_byte_size": len(c_bytes),
            "max_allowed_bytes": max_bytes,
            "full_state_sha3_256": full_digest,
            "sample": sample,
            "truncated": True,
        }
    }
    return bounded_repr, full_digest


def get_state_authority_trust_key() -> bytes:
    """Resolve the independently configured secret/trust key for state authority receipts.

    Fails closed if secret material is missing, unreadable, or empty.
    Fallback to synthetic or hardcoded default keys is strictly prohibited.
    """
    key_env = os.getenv("AGENTV_STATE_AUTHORITY_KEY") or os.getenv("STATE_AUTHORITY_KEY")
    if key_env and key_env.strip():
        return key_env.strip().encode("utf-8")
    trust_root = getattr(config, "TRUST_ROOT", None)
    if trust_root:
        key_path = Path(trust_root) / "state_authority.key"
        if key_path.is_file():
            try:
                key_bytes = key_path.read_bytes().strip()
                if key_bytes:
                    return key_bytes
            except OSError:
                pass
    raise StateAuthorityKeyMissingError(
        "State authority trust key is required but missing, unreadable, or empty. "
        "Explicitly provision AGENTV_STATE_AUTHORITY_KEY or <TRUST_ROOT>/state_authority.key. "
        "Falling back to default or synthetic keys is prohibited."
    )


CONNECTOR_RECEIPT_PROFILE_V2 = "agentv.connector-receipt.v2"


def canonical_receipt_payload_bytes(receipt_data: Mapping[str, Any]) -> bytes:
    """Generate unambiguous canonical bytes for receipt MAC computation.

    Uses versioned, structured canonical JSON encoding to prevent delimiter-injection
    and tuple-collision attacks. Enforces strict, unambiguous v2 encoding/profile
    consistency to prevent field-level downgrade attacks.
    """
    enc_ver = str(receipt_data.get("encoding_version") or "").strip()
    profile = str(receipt_data.get("profile") or "").strip()
    ver = str(receipt_data.get("version") or "").strip()
    has_v2_fields = bool(receipt_data.get("phase") or receipt_data.get("run_id"))

    is_v2 = (
        enc_ver in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2)
        or profile in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2)
        or ver in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2)
        or has_v2_fields
    )
    if is_v2:
        # Prevent field-level downgrade/spoofing: ALL present version fields must be consistent v2
        if enc_ver and enc_ver not in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2):
            raise ValueError(
                f"Ambiguous or conflicting receipt version: encoding_version={enc_ver!r} is not v2"
            )
        if profile and profile not in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2):
            raise ValueError(
                f"Ambiguous or conflicting receipt version: profile={profile!r} is not v2"
            )
        if ver and ver not in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2):
            raise ValueError(f"Ambiguous or conflicting receipt version: version={ver!r} is not v2")

        phase_raw = receipt_data.get("phase")
        if not phase_raw or str(phase_raw) not in ("pre", "post"):
            raise ValueError(
                f"Connector receipt v2 requires phase to be 'pre' or 'post', got {phase_raw!r}"
            )
        run_id_raw = receipt_data.get("run_id")
        if not run_id_raw or not str(run_id_raw).strip():
            raise ValueError("Connector receipt v2 requires nonempty 'run_id'")
        canonical_dict = {
            "authenticated": bool(receipt_data.get("authenticated", False)),
            "connector_id": str(receipt_data.get("connector_id", "")),
            "execution_id": str(receipt_data.get("execution_id", "")),
            "phase": str(phase_raw),
            "profile": CONNECTOR_RECEIPT_PROFILE_V2,
            "request": str(receipt_data.get("request", "")),
            "response_digest": str(receipt_data.get("response_digest", "")),
            "run_id": str(run_id_raw).strip(),
            "source_id": str(receipt_data.get("source_id", "")),
            "timestamp": str(receipt_data.get("timestamp", "")),
        }
        return canonical_json_encode(canonical_dict)
    else:
        # Legacy v1 delimiter-based encoding for backward compatibility with v1 receipts
        fields = [
            str(receipt_data.get("connector_id", "")),
            str(receipt_data.get("source_id", "")),
            str(bool(receipt_data.get("authenticated", False))).lower(),
            str(receipt_data.get("request", "")),
            str(receipt_data.get("response_digest", "")),
            str(receipt_data.get("timestamp", "")),
            str(receipt_data.get("execution_id", "")),
        ]
        return ":".join(fields).encode("utf-8")


def compute_connector_receipt_mac(
    receipt_data: Mapping[str, Any],
    key: bytes | None = None,
) -> str:
    """Compute HMAC-SHA3-256 over bounded canonical receipt fields."""
    import hmac

    resolved_key = key if key is not None else get_state_authority_trust_key()
    payload = canonical_receipt_payload_bytes(receipt_data)
    return hmac.new(resolved_key, payload, hashlib.sha3_256).hexdigest()


def compute_connector_receipt_token(
    connector_id: str,
    source_id: str,
    key: bytes | None = None,
) -> str:
    """Compute deterministic cryptographic receipt token binding connector identity to source."""
    resolved_key = key if key is not None else get_state_authority_trust_key()
    import hmac

    return hmac.new(
        resolved_key,
        f"connector_receipt:{connector_id}:{source_id}".encode(),
        hashlib.sha3_256,
    ).hexdigest()


def create_authenticated_connector_receipt(
    connector_id: str,
    source_id: str,
    *,
    is_authenticated: bool = True,
    request_spec: str | dict[str, Any] | None = None,
    response_digest: str | None = None,
    execution_id: str | None = None,
    phase: str | None = None,
    run_id: str | None = None,
    timestamp: str | None = None,
    encoding_version: str = "v2",
    key: bytes | None = None,
    signing_key: Any | None = None,
) -> dict[str, Any]:
    """Create an authenticated connector receipt with cryptographic MAC or asymmetric signature."""
    ts = str(timestamp or datetime.now(UTC).isoformat())
    req = str(request_spec or "")
    resp_digest = str(response_digest or "")
    exec_id = str(execution_id or "")

    is_v2 = encoding_version in ("2", "v2", CONNECTOR_RECEIPT_PROFILE_V2)
    if is_v2:
        if not phase or str(phase) not in ("pre", "post"):
            raise ValueError(
                f"Connector receipt v2 requires phase to be 'pre' or 'post', got {phase!r}"
            )
        if not run_id or not str(run_id).strip():
            raise ValueError("Connector receipt v2 requires nonempty 'run_id'")

    resolved_token = None
    if key is not None:
        resolved_token = compute_connector_receipt_token(connector_id, source_id, key=key)
    elif signing_key is None:
        try:
            resolved_token = compute_connector_receipt_token(connector_id, source_id, key=None)
        except StateAuthorityKeyMissingError:
            resolved_token = hashlib.sha3_256(
                f"connector_receipt:{connector_id}:{source_id}".encode()
            ).hexdigest()
    else:
        resolved_token = hashlib.sha3_256(
            f"connector_receipt:{connector_id}:{source_id}".encode()
        ).hexdigest()

    receipt: dict[str, Any] = {
        "encoding_version": encoding_version,
        "profile": (CONNECTOR_RECEIPT_PROFILE_V2 if is_v2 else "v1"),
        "connector_id": connector_id,
        "source_id": source_id,
        "authenticated": bool(is_authenticated),
        "request": req,
        "response_digest": resp_digest,
        "timestamp": ts,
        "execution_id": exec_id,
        "retrieval_token": resolved_token,
    }
    if phase:
        receipt["phase"] = str(phase)
    if run_id:
        receipt["run_id"] = str(run_id).strip()

    if signing_key is not None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        priv = signing_key
        if isinstance(priv, (str, bytes)):
            pem_b = priv.encode("utf-8") if isinstance(priv, str) else priv
            priv = serialization.load_pem_private_key(pem_b, password=None)
        if not isinstance(priv, ed25519.Ed25519PrivateKey):
            raise TypeError("signing_key must be an Ed25519PrivateKey or valid PEM bytes")

        payload = canonical_receipt_payload_bytes(receipt)
        sig_bytes = priv.sign(payload)
        sig_hex = sig_bytes.hex()
        receipt["algorithm"] = "ed25519"
        receipt["signature_ed25519"] = sig_hex
        receipt["signature"] = sig_hex
        receipt["mac"] = sig_hex
        pub = priv.public_key()
        pub_pem = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        receipt["public_key_pem"] = pub_pem
    else:
        receipt["mac"] = compute_connector_receipt_mac(receipt, key=key)
        receipt["signature"] = receipt["mac"]
    return receipt


def verify_connector_receipt_authenticity(
    receipt: Mapping[str, Any],
    key: bytes | None = None,
    trusted_public_key: Any | None = None,
) -> bool:
    """Cryptographically verify the signature or MAC of a connector
    receipt under public anchors or trust key.

    Supports asymmetric public-key verification under connector identities for zero-trust
    detached verification, as well as symmetric HMAC verification under the secret key.
    Observation-specific MAC or signature binding the observation payload and
    metadata is strictly required. Retrieval-token-only authentication is prohibited.
    """
    import hmac

    if not isinstance(receipt, Mapping):
        return False
    mac = receipt.get("mac") or receipt.get("signature")
    if not mac or not isinstance(mac, str):
        return False

    is_asymmetric = (
        receipt.get("algorithm") == "ed25519"
        or "signature_ed25519" in receipt
        or "public_key_pem" in receipt
        or trusted_public_key is not None
    )

    if is_asymmetric:
        try:
            from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519

            pub_key = None
            if trusted_public_key is not None:
                if isinstance(trusted_public_key, ed25519.Ed25519PublicKey):
                    pub_key = trusted_public_key
                elif isinstance(trusted_public_key, (str, bytes)):
                    raw_b = (
                        trusted_public_key.encode("utf-8")
                        if isinstance(trusted_public_key, str)
                        else trusted_public_key
                    )
                    pub_key = serialization.load_pem_public_key(raw_b)
            else:
                conn_id = str(receipt.get("connector_id", "")).strip()
                if conn_id:
                    # Read public anchors only. IdentityService can derive a public
                    # key from private issuer material, which detached verification
                    # must never require. Receipt-carried keys are not trust anchors.
                    env_anchor = os.getenv(f"AES_PUBLIC_KEY_{conn_id.upper()}")
                    if env_anchor:
                        pub_key = serialization.load_pem_public_key(env_anchor.encode("utf-8"))
                    elif getattr(config, "TRUST_ROOT", None):
                        root = Path(config.TRUST_ROOT).resolve()
                        candidate_file = (root / conn_id / "public_key.pem").resolve()
                        if not candidate_file.is_relative_to(root):
                            return False
                        if candidate_file.is_file():
                            pub_key = serialization.load_pem_public_key(candidate_file.read_bytes())

            if pub_key is None or not isinstance(pub_key, ed25519.Ed25519PublicKey):
                return False

            sig_hex = receipt.get("signature_ed25519") or receipt.get("signature") or mac
            sig_bytes = bytes.fromhex(sig_hex)
            payload = canonical_receipt_payload_bytes(receipt)
            pub_key.verify(sig_bytes, payload)
            return True
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
            InvalidSignature,
            UnsupportedAlgorithm,
        ) as exc:
            logger.debug(
                "Ed25519 connector receipt signature verification failed: %s",
                exc,
                exc_info=True,
            )
            return False

    try:
        resolved_key = key if key is not None else get_state_authority_trust_key()
        expected_mac = compute_connector_receipt_mac(receipt, key=resolved_key)
    except (ValueError, StateAuthorityKeyMissingError):
        return False
    if not hmac.compare_digest(mac, expected_mac):
        return False

    # If a retrieval token is also present, validate token binding as defense-in-depth
    token = receipt.get("retrieval_token")
    if token:
        if not isinstance(token, str):
            return False
        expected_token = compute_connector_receipt_token(
            str(receipt.get("connector_id", "")),
            str(receipt.get("source_id", "")),
            key=resolved_key,
        )
        if not hmac.compare_digest(token, expected_token):
            return False

    return True


class StateAuthorityConnector(ABC):
    """Abstract interface for observing external system state authorities."""

    def observation_identity(
        self,
        response_digest: str | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """Custom connectors must establish authenticated provenance explicitly."""
        return {"authenticated": False}

    @abstractmethod
    async def fetch_state(
        self,
        endpoint_or_query: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Fetch raw state snapshot from external state authority."""


class HttpStateAuthorityConnector(StateAuthorityConnector):
    """
    HTTP / REST External State Authority Connector (P0-05).
    Observes external services via standard HTTP GET with timeout.
    """

    def __init__(
        self,
        base_url: str,
        default_headers: dict[str, str] | None = None,
        ssl_context: Any | None = None,
    ):
        self.base_url = _validate_external_authority_url(base_url.rstrip("/"))
        self.default_headers = default_headers or {}
        self.ssl_context = ssl_context

    def observation_identity(
        self,
        response_digest: str | None = None,
        execution_id: str | None = None,
        timestamp: str | None = None,
        phase: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        credentials = any(
            name.lower() in {"authorization", "x-api-key", "api-key"}
            and isinstance(value, str)
            and bool(value.strip())
            for name, value in self.default_headers.items()
        )
        source_id = "sha3_256:" + hashlib.sha3_256(self.base_url.encode()).hexdigest()
        is_auth = urlparse(self.base_url).scheme == "https" and credentials
        connector_id = f"connector:http:{source_id}"
        enc_ver = "v2" if (phase and run_id) else "v1"
        receipt = create_authenticated_connector_receipt(
            connector_id=connector_id,
            source_id=source_id,
            is_authenticated=is_auth,
            request_spec=self.base_url,
            response_digest=response_digest,
            execution_id=execution_id,
            phase=phase,
            run_id=run_id,
            timestamp=timestamp,
            encoding_version=enc_ver,
        )
        return {
            "source_id": source_id,
            "authenticated": is_auth,
            "transport": urlparse(self.base_url).scheme,
            "connector_id": connector_id,
            "connector_receipt": receipt,
        }

    async def fetch_state(
        self,
        endpoint_or_query: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = self.base_url
        if endpoint_or_query:
            endpoint = urlparse(endpoint_or_query)
            if endpoint.scheme or endpoint.netloc:
                raise StateAuthorityPolicyError(
                    "State authority endpoint must be relative to its declared origin"
                )
            url = urljoin(f"{self.base_url}/", endpoint_or_query.lstrip("/"))

        _validate_external_authority_url(url)

        req_headers = {**self.default_headers, **(headers or {})}
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            try:
                async with session.get(
                    url, headers=req_headers, allow_redirects=False, ssl=self.ssl_context
                ) as resp:
                    status_code = resp.status
                    if not 200 <= status_code < 300:
                        err_text = await resp.text()
                        logger.warning(
                            f"[StateAuthority] External authority {url} "
                            f"returned HTTP {status_code}: {err_text[:200]}"
                        )
                        raise ValueError(
                            f"External state authority {url} "
                            f"returned HTTP {status_code}: {err_text[:200]}"
                        )

                    content_length = resp.content_length
                    max_response_bytes = EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES
                    if content_length is not None and content_length > max_response_bytes:
                        raise StateLimitExceededError(
                            "External state response exceeds bounded snapshot limit"
                        )
                    raw_payload = await resp.content.read(max_response_bytes + 1)
                    if len(raw_payload) > max_response_bytes:
                        raise StateLimitExceededError(
                            "External state response exceeds bounded snapshot limit"
                        )
                    try:
                        payload = json.loads(raw_payload)
                    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError("External state authority returned invalid JSON") from exc
                    if not isinstance(payload, dict):
                        payload = {"data": payload}

                    return payload
            except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                logger.error(f"[StateAuthority] Network error querying {url}: {exc}", exc_info=True)
                raise ConnectionError(
                    f"Failed to query external state authority {url}: {exc}"
                ) from exc


class ExternalStateAuthorityRegistry:
    """Registry of state authorities declared across scenarios and nodes."""

    def __init__(self):
        self._connectors: dict[str, StateAuthorityConnector] = {}

    def register_authority(self, name: str, connector: StateAuthorityConnector):
        self._connectors[name] = connector

    def get_connector(
        self,
        target_name_or_url: str,
        scenario_authorities: dict[str, Any] | None = None,
    ) -> StateAuthorityConnector:
        # A scenario declaration must not reuse another session's credentials or URL.
        if scenario_authorities and target_name_or_url in scenario_authorities:
            auth_conf = scenario_authorities[target_name_or_url]
            if isinstance(auth_conf, dict):
                url = auth_conf.get("url") or auth_conf.get("endpoint")
                headers = auth_conf.get("headers")
                ssl_context = auth_conf.get("ssl_context") or auth_conf.get("ssl")
                cafile = (
                    auth_conf.get("cafile")
                    or auth_conf.get("ca_cert")
                    or auth_conf.get("ssl_ca_cert")
                )
                if cafile:
                    ssl_context = ssl.create_default_context(cafile=str(cafile))
                elif isinstance(ssl_context, (str, Path)):
                    ssl_context = ssl.create_default_context(cafile=str(ssl_context))
                if url:
                    connector = HttpStateAuthorityConnector(
                        base_url=url, default_headers=headers, ssl_context=ssl_context
                    )
                    return connector

        if target_name_or_url in self._connectors:
            return self._connectors[target_name_or_url]

        # 3. Dynamic HTTP URL target
        if target_name_or_url.startswith("http://") or target_name_or_url.startswith("https://"):
            connector = HttpStateAuthorityConnector(base_url=target_name_or_url)
            self._connectors[target_name_or_url] = connector
            return connector

        raise KeyError(
            f"No external state authority registered for '{target_name_or_url}' "
            "and target is not a valid URL."
        )

    def clear(self):
        self._connectors.clear()


# Authoritative Global Registry Instance
state_authority_registry = ExternalStateAuthorityRegistry()
