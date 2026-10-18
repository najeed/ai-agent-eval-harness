"""
tests.unit.core.test_scope_policy
Exhaustive unit tests for agentv_runtime.scope and auth_manager scope integration.
"""

from __future__ import annotations

import pytest
from flask import Flask

from agentv_runtime.scope import (
    EnterpriseTaggedScopePolicy,
    LocalOrSingleTenantScopePolicy,
    ScopeToken,
)
from eval_runner.console.auth_manager import (
    active_runtime_context,
    active_runtime_scope,
    context_allows_record,
    get_active_scope_policy,
    require_permission,
    set_active_scope_policy,
)


class TestScopeToken:
    def test_empty_and_none_tags(self):
        token_none = ScopeToken.from_tags(None)
        assert token_none.tags == {}
        assert token_none.digest == ""
        assert not token_none.is_system

        token_empty = ScopeToken.from_tags({})
        assert token_empty.tags == {}
        assert token_empty.digest == ""

        token_all_filtered = ScopeToken.from_tags({"key": None})
        assert token_all_filtered.tags == {}
        assert token_all_filtered.digest == ""

        token_system = ScopeToken.from_tags(None, is_system=True)
        assert token_system.is_system

    def test_canonical_digest_determinism(self):
        tags1 = {"tenant_id": "t1", "org_id": "o1"}
        tags2 = {"org_id": "o1", "tenant_id": "t1"}

        token1 = ScopeToken.from_tags(tags1)
        token2 = ScopeToken.from_tags(tags2)

        assert token1.digest == token2.digest
        assert token1.digest != ""
        assert token1.tags == {"tenant_id": "t1", "org_id": "o1"}

    def test_type_filtering_and_normalization(self):
        raw = {"org": "o1", "count": 42, "active": True, "ratio": 3.14, "null_val": None}
        token = ScopeToken.from_tags(raw)
        assert token.tags == {
            "org": "o1",
            "count": "42",
            "active": "True",
            "ratio": "3.14",
        }
        assert "null_val" not in token.tags

    def test_matches_predicate(self):
        token_a = ScopeToken.from_tags({"org": "o1"})
        token_b = ScopeToken.from_tags({"org": "o1"})
        token_c = ScopeToken.from_tags({"org": "o2"})
        token_sys = ScopeToken.from_tags(None, is_system=True)

        assert token_a.matches(token_b)
        assert not token_a.matches(token_c)
        assert token_a.matches(token_sys)
        assert token_sys.matches(token_c)
        assert not token_a.matches(None)


class TestLocalOrSingleTenantScopePolicy:
    def test_mandatory_flag(self):
        policy = LocalOrSingleTenantScopePolicy()
        assert not policy.is_scope_mandatory()

    def test_resolve_scope_branches(self):
        policy = LocalOrSingleTenantScopePolicy(default_tags={"workspace": "local"})

        # 1. Non-dict principal
        assert policy.resolve_scope(None) is None  # type: ignore
        assert policy.resolve_scope("invalid") is None  # type: ignore

        # 2. Explicit context on principal
        scoped_user = {"id": "u1", "context": {"org": "alpha", "tenant": "t1"}}
        token = policy.resolve_scope(scoped_user)
        assert token is not None
        assert token.tags == {"org": "alpha", "tenant": "t1"}
        assert not token.is_system

        # 3. Wildcard permissions
        admin_user = {"id": "admin", "permissions": ["*"]}
        token_admin = policy.resolve_scope(admin_user)
        assert token_admin is not None
        assert token_admin.is_system

        # 4. Service backend types
        backend_key = {"id": "svc", "type": "backend-auth", "permissions": ["runs:read"]}
        token_backend = policy.resolve_scope(backend_key)
        assert token_backend is not None
        assert token_backend.is_system

        api_key_user = {"id": "key1", "type": "api-key", "permissions": ["runs:read"]}
        token_api = policy.resolve_scope(api_key_user)
        assert token_api is not None
        assert token_api.is_system

        # 5. Default tags fallback
        plain_user = {"id": "viewer", "permissions": ["runs:read"]}
        token_plain = policy.resolve_scope(plain_user)
        assert token_plain is not None
        assert token_plain.tags == {"workspace": "local"}

        # 6. Policy without default tags
        policy_no_defaults = LocalOrSingleTenantScopePolicy()
        token_no_def = policy_no_defaults.resolve_scope(plain_user)
        assert token_no_def is not None
        assert token_no_def.tags == {}
        assert not token_no_def.is_system

    def test_allows_record_filtering(self):
        policy = LocalOrSingleTenantScopePolicy()

        # System and None scopes allow everything
        assert policy.allows_record({"context": {"org": "o1"}}, None)
        assert policy.allows_record(
            {"context": {"org": "o1"}}, ScopeToken.from_tags(None, is_system=True)
        )
        assert policy.allows_record({"context": {"org": "o1"}}, ScopeToken.from_tags({}))

        # Scoped token matching
        token = ScopeToken.from_tags({"org": "alpha", "ws": "w1"})
        assert policy.allows_record({"context": {"org": "alpha", "ws": "w1", "extra": "x"}}, token)
        assert not policy.allows_record({"context": {"org": "beta", "ws": "w1"}}, token)

        # Metadata runtime_context check
        record_with_meta = {"metadata": {"runtime_context": {"org": "alpha", "ws": "w1"}}}
        assert policy.allows_record(record_with_meta, token)

        # Untagged or invalid context record is rejected for tenanted token
        assert not policy.allows_record({"context": "invalid"}, token)
        # Non-dict record allows access in OSS
        assert policy.allows_record("invalid-record-format", token)
        # Metadata with non-matching runtime_context is rejected
        assert not policy.allows_record({"metadata": {"runtime_context": "invalid"}}, token)
        # allows_permission defers to provider
        assert policy.allows_permission({"id": "u1"}, "runs:read") is None


class TestEnterpriseTaggedScopePolicy:
    def test_mandatory_flag(self):
        policy = EnterpriseTaggedScopePolicy()
        assert policy.is_scope_mandatory()

    def test_resolve_scope_validation(self):
        policy = EnterpriseTaggedScopePolicy(
            required_tags=("org_id", "tenant_id", "workspace_id", "active_environment")
        )

        # 1. Non-dict
        assert policy.resolve_scope(None) is None  # type: ignore

        # 2. Wildcard system override
        admin = {"id": "root", "permissions": ["*"]}
        token_admin = policy.resolve_scope(admin)
        assert token_admin is not None
        assert token_admin.is_system

        strict_no_wildcard = EnterpriseTaggedScopePolicy(allow_wildcard_system_principals=False)
        assert strict_no_wildcard.resolve_scope(admin) is None

        # 3. Missing context
        user_no_context = {"id": "u1", "permissions": ["runs:read"]}
        assert policy.resolve_scope(user_no_context) is None

        # 4. Partial context
        user_partial = {
            "id": "u1",
            "context": {"org_id": "o1", "tenant_id": "t1"},
        }
        assert policy.resolve_scope(user_partial) is None

        # 5. Empty field in context
        user_empty_field = {
            "id": "u1",
            "context": {
                "org_id": "o1",
                "tenant_id": "t1",
                "workspace_id": "",
                "active_environment": "prod",
            },
        }
        assert policy.resolve_scope(user_empty_field) is None

        # 6. Valid complete context
        user_valid = {
            "id": "u1",
            "context": {
                "org_id": "o1",
                "tenant_id": "t1",
                "workspace_id": "ws1",
                "active_environment": "prod",
            },
        }
        token_valid = policy.resolve_scope(user_valid)
        assert token_valid is not None
        assert token_valid.tags == user_valid["context"]
        assert not token_valid.is_system

    def test_allows_record_strict_filtering(self):
        policy = EnterpriseTaggedScopePolicy()
        token = ScopeToken.from_tags({"org_id": "o1", "tenant_id": "t1"})

        # None scope rejected
        assert not policy.allows_record({"context": {"org_id": "o1", "tenant_id": "t1"}}, None)

        # System scope allowed
        assert policy.allows_record(
            {"context": {"org_id": "o2"}}, ScopeToken.from_tags(None, is_system=True)
        )

        # Missing or non-dict record source rejected in enterprise
        assert not policy.allows_record({"context": "corrupt"}, token)
        assert not policy.allows_record({}, token)

        # Matching vs non-matching
        assert policy.allows_record({"context": {"org_id": "o1", "tenant_id": "t1"}}, token)
        assert not policy.allows_record({"context": {"org_id": "o1", "tenant_id": "t2"}}, token)

        # Metadata runtime_context check
        record_with_meta = {"metadata": {"runtime_context": {"org_id": "o1", "tenant_id": "t1"}}}
        assert policy.allows_record(record_with_meta, token)
        # Non-dict record rejected in enterprise
        assert not policy.allows_record("invalid-record-format", token)
        # Metadata with non-dict runtime_context rejected in enterprise
        assert not policy.allows_record({"metadata": {"runtime_context": "invalid"}}, token)
        # Unscoped user rejected by enterprise policy allows_permission
        assert not policy.allows_permission({"id": "u1"}, "runs:read", active_scope=None)
        # Wildcard root user defers (is allowed)
        assert (
            policy.allows_permission(
                {"id": "root", "permissions": ["*"]}, "runs:read", active_scope=None
            )
            is None
        )
        # Scoped user defers to provider
        assert policy.allows_permission({"id": "u1"}, "runs:read", active_scope=token) is None


class TestConsoleScopeIntegration:
    @pytest.fixture(autouse=True)
    def reset_policy(self):
        set_active_scope_policy(None)
        yield
        set_active_scope_policy(None)

    def test_policy_resolution_and_override(self, monkeypatch):
        assert isinstance(get_active_scope_policy(), LocalOrSingleTenantScopePolicy)

        monkeypatch.setenv("AGENTV_REQUIRE_ENTERPRISE_CONTEXT", "1")
        assert isinstance(get_active_scope_policy(), EnterpriseTaggedScopePolicy)

        custom = LocalOrSingleTenantScopePolicy(default_tags={"custom": "tag"})
        set_active_scope_policy(custom)
        assert get_active_scope_policy() is custom

    def test_context_allows_record_tag_agnostic(self):
        # 1. None context allows all
        assert context_allows_record({"context": {"a": "1"}}, None)

        # 2. Non-dict source fails closed when context present
        assert not context_allows_record("not-a-dict", {"org": "o1"})  # type: ignore

        # 3. Arbitrary tag matching (not restricted to 4-tuple)
        custom_context = {"project_id": "proj-99", "cluster": "us-east-1"}
        assert context_allows_record(
            {"context": {"project_id": "proj-99", "cluster": "us-east-1"}}, custom_context
        )
        assert not context_allows_record(
            {"context": {"project_id": "proj-99", "cluster": "eu-west-1"}}, custom_context
        )

        # 4. Metadata runtime_context source
        rec_meta = {
            "metadata": {"runtime_context": {"project_id": "proj-99", "cluster": "us-east-1"}}
        }
        assert context_allows_record(rec_meta, custom_context)

    def test_require_permission_with_enterprise_policy_rejection(self, monkeypatch):
        monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)
        set_active_scope_policy(
            EnterpriseTaggedScopePolicy(
                required_tags=("tenant_id", "workspace_id"), allow_wildcard_system_principals=False
            )
        )

        app = Flask("test_scope_gate")
        app.secret_key = "test-secret"

        @app.route("/protected")
        @require_permission("scenarios:read")
        def protected_route():
            scope = active_runtime_scope()
            return {
                "ok": True,
                "scope_digest": scope.digest if scope else None,
                "context": active_runtime_context(),
            }

        client = app.test_client()

        # Unscoped user rejected under enterprise policy
        with client.session_transaction() as sess:
            sess["user"] = {"id": "viewer", "permissions": ["scenarios:read"]}

        resp = client.get("/protected")
        assert resp.status_code == 403
        assert resp.json == {"error": "An active authorized context is required."}

        # Properly scoped user accepted under enterprise policy
        with client.session_transaction() as sess:
            sess["user"] = {
                "id": "viewer",
                "permissions": ["scenarios:read"],
                "context": {"tenant_id": "t1", "workspace_id": "ws1"},
            }

        resp_ok = client.get("/protected")
        assert resp_ok.status_code == 200
        assert resp_ok.json["ok"] is True
        assert resp_ok.json["context"] == {"tenant_id": "t1", "workspace_id": "ws1"}
        assert resp_ok.json["scope_digest"] is not None

    def test_scope_digest_record_partitioning(self):
        token = ScopeToken.from_tags({"org_id": "o1", "tenant_id": "t1"})
        record_matching_digest = {"scope_digest": token.digest, "context": {}}
        record_mismatching_digest = {"scope_digest": "deadbeef" * 8, "context": {}}

        local_policy = LocalOrSingleTenantScopePolicy()
        assert local_policy.allows_record(record_matching_digest, token)
        assert not local_policy.allows_record(record_mismatching_digest, token)

        enterprise_policy = EnterpriseTaggedScopePolicy()
        assert enterprise_policy.allows_record(record_matching_digest, token)
        assert not enterprise_policy.allows_record(record_mismatching_digest, token)

        # In context_allows_record
        assert context_allows_record(record_matching_digest, token.tags)
        assert not context_allows_record(record_mismatching_digest, token.tags)

    def test_permission_guard_delegation_to_active_policy(self, monkeypatch):
        monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)

        class CustomDelegatedPolicy(LocalOrSingleTenantScopePolicy):
            def allows_permission(
                self, principal: dict, permission_node: str, active_scope: ScopeToken | None = None
            ) -> bool | None:
                if permission_node == "special:admin":
                    # Explicit policy override: only user "super-admin" is allowed
                    return principal.get("id") == "super-admin"
                return None

        set_active_scope_policy(CustomDelegatedPolicy())

        app = Flask("test_delegated_policy")
        app.secret_key = "test-secret"

        @app.route("/admin")
        @require_permission("special:admin")
        def admin_route():
            return {"status": "granted"}

        client = app.test_client()

        # Regular user denied by custom policy override
        with client.session_transaction() as sess:
            sess["user"] = {"id": "regular-user", "permissions": ["special:admin"]}

        resp_denied = client.get("/admin")
        assert resp_denied.status_code == 403

        # Super admin allowed by custom policy override
        with client.session_transaction() as sess:
            sess["user"] = {"id": "super-admin", "permissions": []}

        resp_allowed = client.get("/admin")
        assert resp_allowed.status_code == 200
        assert resp_allowed.json == {"status": "granted"}
