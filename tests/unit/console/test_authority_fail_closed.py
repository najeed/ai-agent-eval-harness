"""Acceptance of the canonical authorization authority boundary."""

import time
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from eval_runner.console.auth_manager import StaticKeyProvider
from eval_runner.interfaces.auth import AuthorizationBackend, AuthPrincipal
from eval_runner.reference.auth import OIDCAuthorizationBackend, SimpleAPIKeyAuthBackend


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        True,
        "root-admin",
        AuthPrincipal("admin", permissions="*"),
        AuthPrincipal("admin", metadata={"authorized_contexts": []}),
        AuthPrincipal("admin", metadata={"context_version": "1"}),
        AuthPrincipal("admin", metadata={"context": {"tenant": []}}),
    ],
)
def test_denial_and_malformed_principals_cannot_use_legacy_key(result):
    backend = Mock(spec=AuthorizationBackend)
    backend.validate_token.return_value = result
    provider = StaticKeyProvider("legacy-key", backend=backend)
    assert provider.get_authorization_backend() is backend
    assert provider.authenticate("legacy-key") is None
    assert provider.verify_token("legacy-key") is None


def test_outage_and_permission_denial_cannot_fall_back():
    backend = Mock(spec=AuthorizationBackend)
    backend.validate_token.side_effect = RuntimeError("offline")
    backend.check_permission.side_effect = RuntimeError("offline")
    backend.get_service_credential.return_value = None
    provider = StaticKeyProvider("legacy-key", backend=backend)
    assert provider.authenticate("legacy-key") is None
    assert provider.verify_token("legacy-key") is None
    assert not provider.has_permission(
        {"id": "root-admin", "roles": ["admin"], "permissions": ["*"]}, "system:config"
    )
    backend.check_permission.side_effect = None
    backend.check_permission.return_value = False
    assert not provider.has_permission(
        {"id": "root-admin", "permissions": ["system:config"]}, "system:config"
    )
    assert provider.get_service_credential() is None


def test_configured_authority_supersedes_oidc(monkeypatch):
    monkeypatch.setattr("eval_runner.config.OIDC_JWKS_URL", "https://issuer/jwks")
    backend = Mock(spec=AuthorizationBackend)
    backend.validate_token.return_value = None
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("jwt.PyJWKClient", lambda *a, **k: pytest.fail("local OIDC bypass"))
        assert StaticKeyProvider("legacy", backend=backend).verify_token("legacy") is None


def test_missing_keys_and_oidc_configuration_fail_closed(monkeypatch):
    for key in ("EVAL_MASTER_KEY", "CONSOLE_MASTER_KEY", "SERVICE_API_KEY", "DASHBOARD_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    backend = SimpleAPIKeyAuthBackend()
    assert backend.get_service_credential() is None
    assert backend.validate_token("admin") is None
    for config in [
        (None, "issuer", "audience"),
        ("jwks", None, "audience"),
        ("jwks", "issuer", None),
    ]:
        assert OIDCAuthorizationBackend(*config).validate_token("legacy") is None


@pytest.mark.parametrize(
    "mutation",
    [
        "valid",
        "expired",
        "issuer",
        "audience",
        "signature",
        "missing_exp",
        "wildcard",
        "malformed",
        "admin",
    ],
)
def test_oidc_crypto_and_entitlement_boundaries(mutation):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {
        "sub": "root-admin",
        "iss": "https://issuer",
        "aud": "console",
        "exp": time.time() + 300,
        "roles": ["admin", "system-admin"],
        "permissions": ["runs:read"],
    }
    if mutation == "expired":
        claims["exp"] = time.time() - 60
    if mutation == "issuer":
        claims["iss"] = "https://other"
    if mutation == "audience":
        claims["aud"] = "other"
    if mutation == "missing_exp":
        del claims["exp"]
    if mutation == "wildcard":
        claims["permissions"] = ["*"]
    if mutation == "malformed":
        claims["authorized_contexts"] = "admin"
    if mutation == "admin":
        del claims["permissions"]
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if mutation == "signature"
        else key
    )
    backend = OIDCAuthorizationBackend("https://issuer/jwks", "https://issuer", "console")
    backend._jwks_client = Mock()
    backend._jwks_client.get_signing_key_from_jwt.return_value = Mock(key=key.public_key())
    provider = StaticKeyProvider("legacy", backend=backend)
    user = provider.verify_token(jwt.encode(claims, signing_key, algorithm="RS256"))
    if mutation in ("valid", "admin"):
        assert user is not None
        assert not provider.has_permission(user, "system:config")
        assert provider.has_permission(user, "runs:read") == (mutation == "valid")
    else:
        assert user is None


def test_discovered_authority_load_failure_cannot_create_local_root(monkeypatch):
    from agentv_runtime.discovery import reset_extensions
    from eval_runner.runtime_services import resolve_authorization_backend

    reset_extensions("authorization_backends")
    entry = Mock(name="default")
    entry.name = "default"
    entry.dist.name = "agentv"
    entry.load.side_effect = RuntimeError("provider offline")
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kwargs: [entry])
    with pytest.raises(RuntimeError, match="provider failed to load"):
        resolve_authorization_backend(master_key="legacy")


def test_current_user_cannot_invent_local_admin_after_provider_denial(monkeypatch):
    from flask import Flask

    from eval_runner.console.auth import get_current_user

    backend = Mock(spec=AuthorizationBackend)
    backend.validate_token.return_value = None
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.get_auth_provider",
        lambda: StaticKeyProvider("legacy", backend=backend),
    )
    monkeypatch.setattr("eval_runner.config.ENABLE_DEMO", True)
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    with app.test_request_context(
        "/api/auth/me", headers={"X-API-Key": "legacy"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}
    ):
        response, status = get_current_user()
        assert status == 200
        assert response.json["authenticated"] is False
        assert response.json["user"] is None


def test_registered_runtime_authority_supersedes_oidc(monkeypatch):
    from agentv_runtime.discovery import get_registered_extension, set_extension

    previous = get_registered_extension("authorization_backends")
    backend = Mock(spec=AuthorizationBackend)
    backend.validate_token.return_value = None
    monkeypatch.setattr("eval_runner.config.OIDC_JWKS_URL", "https://issuer/jwks")
    try:
        set_extension("authorization_backends", backend)
        provider = StaticKeyProvider("legacy")
        assert provider.get_authorization_backend() is backend
        assert provider.verify_token("legacy") is None
    finally:
        set_extension("authorization_backends", previous)


@pytest.mark.parametrize("result", [None, object()])
def test_malformed_discovered_provider_cannot_create_local_root(monkeypatch, result):
    from agentv_runtime.discovery import get_registered_extension, set_extension
    from eval_runner.runtime_services import resolve_authorization_backend

    previous = get_registered_extension("authorization_backends")
    entry = Mock()
    entry.name = "default"
    entry.dist.name = "agentv"
    entry.load.return_value = lambda: result
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kwargs: [entry])
    try:
        set_extension("authorization_backends", None)
        with pytest.raises(RuntimeError):
            resolve_authorization_backend(master_key="legacy")
    finally:
        set_extension("authorization_backends", previous)
