import os
import unittest.mock as mock

from flask import Flask, jsonify

from eval_runner.console.auth_manager import (
    Permission,
    StaticKeyProvider,
    extract_credentials_from_context,
    require_permission,
)


def test_extract_credentials():
    # Test Authorization header
    headers = {"Authorization": "Bearer my-jwt-token"}
    args = {}
    bearer, api_key = extract_credentials_from_context(headers, args)
    assert bearer == "my-jwt-token"
    assert api_key is None

    # Test space-trimmed Authorization header
    headers = {"Authorization": "Bearer  another-token  "}
    bearer, api_key = extract_credentials_from_context(headers, args)
    assert bearer == "another-token"
    assert api_key is None

    # Test X-AES-API-KEY
    headers = {"X-AES-API-KEY": "my-api-key"}
    bearer, api_key = extract_credentials_from_context(headers, args)
    assert bearer is None
    assert api_key == "my-api-key"

    # Test query params apiKey
    headers = {}
    args = {"apiKey": "query-api-key"}
    bearer, api_key = extract_credentials_from_context(headers, args)
    assert bearer is None
    assert api_key == "query-api-key"


def test_static_key_provider_verify_token_fallback():
    provider = StaticKeyProvider("master-key-123")
    # Verify fallback to authenticate when OIDC is not configured
    user = provider.verify_token("master-key-123")
    assert user is not None
    assert user["id"] == "root-admin"
    assert user["type"] == "static-root"

    assert provider.verify_token("invalid-key") is None


def test_oidc_jwt_verification_success():
    # Mock config settings
    jwks_url = "https://auth.example.com/.well-known/jwks.json"
    with (
        mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url),
        mock.patch("eval_runner.config.OIDC_ISSUER", "https://auth.example.com"),
        mock.patch("eval_runner.config.OIDC_AUDIENCE", "agentv-service"),
    ):
        provider = StaticKeyProvider("master-key-123")

        # Mock PyJWKClient and jwt.decode
        mock_jwks_client = mock.MagicMock()
        mock_signing_key = mock.MagicMock()
        mock_signing_key.key = "public-key-content"
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        mock_payload = {
            "sub": "user-456",
            "email": "user@example.com",
            "name": "Jane Doe",
            "permissions": [Permission.SCENARIOS_READ, Permission.RUNS_READ],
            "iss": "https://auth.example.com",
            "aud": "agentv-service",
        }

        with (
            mock.patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            mock.patch("jwt.decode", return_value=mock_payload) as mock_decode,
        ):
            user = provider.verify_token("valid-jwt-token-string")

            assert user is not None
            assert user["id"] == "user-456"
            assert user["email"] == "user@example.com"
            assert user["name"] == "Jane Doe"
            assert Permission.SCENARIOS_READ in user["permissions"]
            assert user["type"] == "oidc-sso"

            mock_decode.assert_called_once_with(
                "valid-jwt-token-string",
                "public-key-content",
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                leeway=10,
                audience="agentv-service",
                issuer="https://auth.example.com",
            )


def test_oidc_jwt_verification_roles_and_scope():
    jwks_url = "https://auth.example.com/.well-known/jwks.json"
    with mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url):
        provider = StaticKeyProvider("master-key-123")

        mock_jwks_client = mock.MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock.MagicMock()

        # Test roles -> admin mapping
        mock_payload = {
            "sub": "admin-1",
            "roles": ["system-admin"],
        }
        with (
            mock.patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            mock.patch("jwt.decode", return_value=mock_payload),
        ):
            user = provider.verify_token("token")
            assert user["permissions"] == Permission.ADMIN()

        # Test scope mapping
        mock_payload_scope = {
            "sub": "scope-user",
            "scope": "scenarios:read runs:read",
        }
        with (
            mock.patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            mock.patch("jwt.decode", return_value=mock_payload_scope),
        ):
            user = provider.verify_token("token")
            assert user["permissions"] == ["scenarios:read", "runs:read"]


def test_oidc_jwt_verification_failure():
    jwks_url = "https://auth.example.com/.well-known/jwks.json"
    with mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url):
        provider = StaticKeyProvider("master-key-123")

        with mock.patch("jwt.PyJWKClient", side_effect=Exception("Failed to load JWKS")):
            # Enable DEBUG to test debug print branch
            with mock.patch.dict(os.environ, {"DEBUG": "true"}):
                user = provider.verify_token("invalid-jwt")
                assert user is None


def test_require_permission_decorator():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "super-secret-key"

    @app.route("/test-route")
    @require_permission(Permission.SCENARIOS_READ)
    def test_endpoint():
        return jsonify({"status": "success"})

    client = app.test_client()

    # 1. No credentials -> 401
    resp = client.get("/test-route")
    assert resp.status_code == 401

    # 2. Invalid static key -> 401
    with mock.patch("eval_runner.config.SERVICE_API_KEY", "secret-key"):
        resp = client.get("/test-route", headers={"X-AES-API-KEY": "wrong-key"})
        assert resp.status_code == 401

    # 3. Valid static key -> 200
    with mock.patch("eval_runner.config.SERVICE_API_KEY", "secret-key"):
        resp = client.get("/test-route", headers={"X-AES-API-KEY": "secret-key"})
        assert resp.status_code == 200

    # 4. Valid session user -> 200
    with app.test_request_context():
        # Session check via client cookie session simulation
        with client.session_transaction() as sess:
            sess["user"] = {"permissions": [Permission.SCENARIOS_READ], "id": "session-user"}
        resp = client.get("/test-route")
        assert resp.status_code == 200

    # 5. Insufficient permissions in session -> 403
    with app.test_request_context():
        with client.session_transaction() as sess:
            sess["user"] = {"permissions": [Permission.RUNS_READ], "id": "session-user-no-perm"}
        resp = client.get("/test-route")
        assert resp.status_code == 403

    # Clear session cookie for header tests
    with app.test_request_context():
        with client.session_transaction() as sess:
            sess.clear()

    # 6. Valid Bearer Token (Simulated OIDC context) -> 200
    jwks_url = "https://auth.example.com/.well-known/jwks.json"
    with mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url):
        provider_mock = mock.MagicMock()
        provider_mock.verify_token.return_value = {
            "permissions": [Permission.SCENARIOS_READ],
            "id": "jwt-user",
        }
        provider_mock.has_permission.side_effect = lambda u, p: p in u["permissions"]

        patch_path = "eval_runner.console.auth_manager.get_auth_provider"
        with mock.patch(patch_path, return_value=provider_mock):
            resp = client.get("/test-route", headers={"Authorization": "Bearer valid-jwt"})
            assert resp.status_code == 200
            provider_mock.verify_token.assert_called_once_with("valid-jwt")

    # 7. Bearer Token but insufficient permissions -> 403
    with mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url):
        provider_mock = mock.MagicMock()
        provider_mock.verify_token.return_value = {
            "permissions": [Permission.RUNS_READ],
            "id": "jwt-user-no-perm",
        }
        provider_mock.has_permission.side_effect = lambda u, p: p in u["permissions"]

        patch_path = "eval_runner.console.auth_manager.get_auth_provider"
        with mock.patch(patch_path, return_value=provider_mock):
            resp = client.get("/test-route", headers={"Authorization": "Bearer valid-jwt-no-perm"})
            assert resp.status_code == 403

    # 8. Invalid Bearer Token -> 401
    with mock.patch("eval_runner.config.OIDC_JWKS_URL", jwks_url):
        provider_mock = mock.MagicMock()
        provider_mock.verify_token.return_value = None

        patch_path = "eval_runner.console.auth_manager.get_auth_provider"
        with mock.patch(patch_path, return_value=provider_mock):
            resp = client.get("/test-route", headers={"Authorization": "Bearer invalid-jwt"})
            assert resp.status_code == 401

    # 9. Valid API key but insufficient permissions -> 403
    provider_mock = mock.MagicMock()
    provider_mock.authenticate.return_value = {
        "permissions": [Permission.RUNS_READ],
        "id": "api-user-no-perm",
    }
    provider_mock.has_permission.side_effect = lambda u, p: p in u["permissions"]

    patch_path = "eval_runner.console.auth_manager.get_auth_provider"
    with mock.patch(patch_path, return_value=provider_mock):
        resp = client.get("/test-route", headers={"X-AES-API-KEY": "some-key"})
        assert resp.status_code == 403

    # 10. Local trust mode verification -> 200 (outside is_testing mode)
    app.config["TESTING"] = False
    with mock.patch("eval_runner.config.ENABLE_DEMO", True):
        # Refresh client with TESTING=False
        trust_client = app.test_client()
        resp = trust_client.get("/test-route")
        assert resp.status_code == 200
