"""
tests/unit/core/test_state_authority.py
Unit tests for External State Authority (P0-05) and Bounded State Capture Contract (P0-06).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from eval_runner.session_components.state_parity import SessionStateParityVerifier
from eval_runner.state_authority import (
    ExternalStateAuthorityRegistry,
    HttpStateAuthorityConnector,
    StateAuthorityPolicyError,
    _safe_default,
    bound_state_snapshot,
    state_authority_registry,
)


class TestBoundedStateCaptureContract:
    """Tests for Bounded State Capture Contract (P0-06)."""

    def test_safe_default_coroutine_and_objects(self):
        # 1. Regular object
        obj = object()
        assert str(obj) in _safe_default(obj)

        # 2. Coroutine
        async def dummy():
            pass

        coro = dummy()
        res_str = _safe_default(coro)
        assert "dummy" in res_str

        # 3. Coroutine with failing close
        mock_coro = MagicMock()
        mock_coro.close.side_effect = RuntimeError("cannot close")
        with patch("inspect.iscoroutine", return_value=True):
            res_mock = _safe_default(mock_coro)
            assert str(mock_coro) in res_mock

    def test_bound_state_snapshot_none(self):
        bounded, digest = bound_state_snapshot(None)
        assert bounded is None
        assert digest.startswith("sha3_256:")

    def test_bound_state_snapshot_projection(self):
        raw_state = {
            "authorizations": [{"id": "AUTH-1", "status": "APPROVED"}],
            "patients": [{"id": "P-100", "secret_ssn": "000-00-0000"}],
            "unrelated_large_table": {"rows": [1, 2, 3]},
        }
        # Project only authorizations
        bounded, digest = bound_state_snapshot(raw_state, projection=["authorizations"])
        assert "authorizations" in bounded
        assert "patients" not in bounded
        assert "unrelated_large_table" not in bounded
        assert bounded["authorizations"][0]["status"] == "APPROVED"
        assert digest.startswith("sha3_256:")

    def test_bound_state_snapshot_nested_projection(self):
        raw_state = {
            "meta": {"clinic": {"name": "Seattle General", "id": 42}},
            "records": [1, 2, 3],
        }
        bounded, _ = bound_state_snapshot(raw_state, projection=["meta.clinic.name"])
        assert bounded == {"meta": {"clinic": {"name": "Seattle General"}}}

    def test_bound_state_snapshot_max_items_truncation(self):
        items = [{"id": i} for i in range(150)]
        bounded, _ = bound_state_snapshot({"items": items}, max_items=50)
        assert "__BOUNDED_COLLECTION__" in bounded["items"]
        b_col = bounded["items"]["__BOUNDED_COLLECTION__"]
        assert b_col["total_items"] == 150
        assert b_col["retained_items"] == 50
        assert len(b_col["items"]) == 50
        assert b_col["truncated"] is True

    def test_bound_state_snapshot_max_bytes_truncation(self):
        # Create an oversized payload that exceeds max_bytes
        oversized = {"big_data": "A" * 2000}
        bounded, digest = bound_state_snapshot(oversized, max_bytes=500)
        assert "__BOUNDED_STATE__" in bounded
        b_state = bounded["__BOUNDED_STATE__"]
        assert b_state["status"] == "BOUNDED_STATE_LIMIT_EXCEEDED"
        assert b_state["truncated"] is True
        assert b_state["full_state_sha3_256"] == digest

    def test_bound_state_snapshot_oversized_list(self):
        oversized_list = ["item"] * 500
        bounded, _ = bound_state_snapshot(oversized_list, max_bytes=100)
        assert "__BOUNDED_STATE__" in bounded
        assert len(bounded["__BOUNDED_STATE__"]["sample"]) == 5

    def test_bound_state_snapshot_oversized_scalar(self):
        oversized_scalar = "X" * 1000
        bounded, _ = bound_state_snapshot(oversized_scalar, max_bytes=100)
        assert "__BOUNDED_STATE__" in bounded
        assert len(bounded["__BOUNDED_STATE__"]["sample"]) == 256

    def test_bound_state_snapshot_canonical_fallback(self):
        from unittest.mock import patch

        with patch(
            "eval_runner.state_authority.canonical_json_encode",
            side_effect=TypeError("Non-canonical"),
        ):
            bounded, digest = bound_state_snapshot({"key": "val"})
            assert bounded == {"key": "val"}
            assert digest.startswith("sha3_256:")


class TestHttpStateAuthorityConnector:
    """Tests for HttpStateAuthorityConnector (P0-05)."""

    @pytest.mark.asyncio
    async def test_http_connector_fetch_state_success(self, aiohttp_client, monkeypatch):
        async def handler(request):
            return web.json_response({"status": "READY", "count": 10})

        app = web.Application()
        app.router.add_get("/api/state", handler)
        client = await aiohttp_client(app)

        base_url = str(client.make_url(""))
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", base_url)
        connector = HttpStateAuthorityConnector(base_url=base_url)
        state = await connector.fetch_state("/api/state")
        assert state == {"status": "READY", "count": 10}

    @pytest.mark.asyncio
    async def test_http_connector_rejects_absolute_endpoint(self, aiohttp_client, monkeypatch):
        async def handler(request):
            return web.json_response({"active": True})

        app = web.Application()
        app.router.add_get("/state", handler)
        client = await aiohttp_client(app)

        base_url = str(client.make_url(""))
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", base_url)
        connector = HttpStateAuthorityConnector(base_url=base_url)
        with pytest.raises(StateAuthorityPolicyError, match="relative"):
            await connector.fetch_state(str(client.make_url("/state")))

    @pytest.mark.asyncio
    async def test_http_connector_fetch_state_non_dict_payload(self, aiohttp_client, monkeypatch):
        async def handler(request):
            return web.json_response([1, 2, 3])

        app = web.Application()
        app.router.add_get("/list", handler)
        client = await aiohttp_client(app)

        base_url = str(client.make_url(""))
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", base_url)
        connector = HttpStateAuthorityConnector(base_url=base_url)
        state = await connector.fetch_state("/list")
        assert state == {"data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_http_connector_error_response(self, aiohttp_client, monkeypatch):
        async def handler(request):
            return web.json_response({"error": "unauthorized"}, status=403)

        app = web.Application()
        app.router.add_get("/forbidden", handler)
        client = await aiohttp_client(app)

        base_url = str(client.make_url(""))
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", base_url)
        connector = HttpStateAuthorityConnector(base_url=base_url)
        with pytest.raises(ValueError, match="HTTP 403"):
            await connector.fetch_state("/forbidden")

    @pytest.mark.asyncio
    async def test_http_connector_network_error(self, monkeypatch):
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "http://127.0.0.1:59999")
        connector = HttpStateAuthorityConnector(base_url="http://127.0.0.1:59999")
        with pytest.raises(ConnectionError):
            await connector.fetch_state("/fail", timeout=0.5)

    def test_http_connector_requires_explicit_origin_allowlist(self, monkeypatch):
        monkeypatch.delenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", raising=False)
        with pytest.raises(StateAuthorityPolicyError, match="not allow-listed"):
            HttpStateAuthorityConnector(base_url="https://example.com/state")


class TestExternalStateAuthorityRegistry:
    """Tests for ExternalStateAuthorityRegistry (P0-05)."""

    def test_registry_registration_and_get(self):
        reg = ExternalStateAuthorityRegistry()
        mock_conn = MagicMock()
        reg.register_authority("authorizations_db", mock_conn)
        assert reg.get_connector("authorizations_db") is mock_conn

    def test_registry_get_from_scenario_authorities(self, monkeypatch):
        reg = ExternalStateAuthorityRegistry()
        scenario_authorities = {
            "tester_mcp": {
                "url": "http://127.0.0.1:8080/mcp/state",
                "headers": {"X-Custom": "test"},
            }
        }
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "http://127.0.0.1:8080")
        conn = reg.get_connector("tester_mcp", scenario_authorities=scenario_authorities)
        assert isinstance(conn, HttpStateAuthorityConnector)
        assert conn.base_url == "http://127.0.0.1:8080/mcp/state"
        assert conn.default_headers == {"X-Custom": "test"}

    def test_registry_get_dynamic_url(self, monkeypatch):
        reg = ExternalStateAuthorityRegistry()
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "http://127.0.0.1:9090")
        conn = reg.get_connector("http://127.0.0.1:9090/state")
        assert isinstance(conn, HttpStateAuthorityConnector)
        assert conn.base_url == "http://127.0.0.1:9090/state"

    def test_registry_get_dynamic_url_path_preservation(self, monkeypatch):
        reg = ExternalStateAuthorityRegistry()
        monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "http://127.0.0.1:8080")
        conn = reg.get_connector("http://127.0.0.1:8080/healthcare/state")
        assert isinstance(conn, HttpStateAuthorityConnector)
        assert conn.base_url == "http://127.0.0.1:8080/healthcare/state"

    def test_registry_key_error_for_unknown(self):
        reg = ExternalStateAuthorityRegistry()
        with pytest.raises(KeyError, match="No external state authority registered"):
            reg.get_connector("unknown_authority")

    def test_registry_clear(self):
        reg = ExternalStateAuthorityRegistry()
        reg.register_authority("dummy", MagicMock())
        assert "dummy" in reg._connectors
        reg.clear()
        assert len(reg._connectors) == 0


class TestSessionStateParityWithExternalAuthority:
    """Tests for SessionStateParityVerifier with external authorities & regulations."""

    @pytest.mark.asyncio
    async def test_parity_verifier_resolves_external_authority(self):
        session_mock = MagicMock()
        session_mock.scenario = {}
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        mock_connector = AsyncMock()
        mock_connector.fetch_state.return_value = {
            "authorizations": [{"id": "AUTH-100", "status": "APPROVED"}]
        }
        state_authority_registry.register_authority("auth_service", mock_connector)

        assertion = {
            "target": "authority:auth_service",
            "property": "authorizations[0].status",
            "expected": "APPROVED",
        }

        val, prop = await verifier._resolve_target(
            assertion, sandbox=None, history=[], shim_snapshots={}
        )
        assert prop == "authorizations[0].status"
        assert val["authorizations"][0]["status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_parity_verifier_unobserved_external_authority_fails_closed(self):
        session_mock = MagicMock()
        session_mock.scenario = {}
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        # Non-existent authority
        assertion = {
            "target": "authority:non_existent_authority",
            "property": "status",
            "expected": "APPROVED",
        }
        val, prop = await verifier._resolve_target(
            assertion, sandbox=None, history=[], shim_snapshots={}
        )
        assert val is None
        assert prop == "__unobserved_source__"

    @pytest.mark.asyncio
    async def test_parity_verifier_policy_uses_declared_external_evidence(self):
        session_mock = MagicMock()
        session_mock.scenario = {
            "metadata": {
                "policies": {
                    "adverse_requires_human_review": {
                        "required": True,
                        "oracle_id": "policy:adverse_requires_human_review",
                        "evidence_target": "authority:healthcare",
                        "rules": [
                            {
                                "when": {"field": "decision", "operator": "eq", "value": "DENY"},
                                "require_all": ["human_review_id"],
                                "required_values": {"decision_source": "HUMAN_REVIEWED"},
                            }
                        ],
                    }
                }
            }
        }
        verifier = SessionStateParityVerifier(session_manager=session_mock)
        connector = AsyncMock()
        connector.fetch_state.return_value = {
            "decision": "DENY",
            "human_review_id": "review-1",
            "decision_source": "HUMAN_REVIEWED",
        }
        state_authority_registry.register_authority("healthcare", connector)

        allowed, prop = await verifier._resolve_target(
            {
                "id": "policy:adverse_requires_human_review",
                "target": "policy:adverse_requires_human_review",
            },
            sandbox=None,
            history=[],
            shim_snapshots={},
        )
        assert allowed is True
        assert prop is None

    @pytest.mark.asyncio
    async def test_parity_verifier_external_authority_subpath_and_fetch_failure(self):
        session_mock = MagicMock()
        session_mock.scenario = {}
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        # 1. external:auth_name.prop subpath resolution
        mock_connector = AsyncMock()
        mock_connector.fetch_state.return_value = {"user": {"role": "admin"}}
        state_authority_registry.register_authority("user_service", mock_connector)

        assertion_subpath = {
            "target": "external:user_service.user",
            "property": "role",
        }
        val, prop = await verifier._resolve_target(
            assertion_subpath, sandbox=None, history=[], shim_snapshots={}
        )
        assert prop == "user.role"
        assert val == {"user": {"role": "admin"}}

        # 2. fetch_state throws exception -> returns None, "__unobserved_source__"
        mock_err_conn = AsyncMock()
        mock_err_conn.fetch_state.side_effect = RuntimeError("network drop")
        state_authority_registry.register_authority("error_service", mock_err_conn)

        assertion_err = {"target": "authority:error_service"}
        val_err, prop_err = await verifier._resolve_target(
            assertion_err, sandbox=None, history=[], shim_snapshots={}
        )
        assert val_err is None
        assert prop_err == "__unobserved_source__"

    @pytest.mark.asyncio
    async def test_parity_verifier_rejects_policy_without_declared_external_evidence(self):
        session_mock = MagicMock()
        session_mock.scenario = {"metadata": {"policies": {}}}
        verifier = SessionStateParityVerifier(session_manager=session_mock)
        observed, marker = await verifier._resolve_target(
            {"target": "policy:unbound_control"},
            sandbox=None,
            history=[],
            shim_snapshots={},
        )
        assert observed is None
        assert marker == "__unobserved_source__"

    @pytest.mark.asyncio
    async def test_parity_verifier_target_external_state_and_dict_authorities(self):
        session_mock = MagicMock()
        session_mock.scenario = {"state_authorities": {"url": "http://127.0.0.1:9999/state"}}
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        mock_connector = AsyncMock()
        mock_connector.fetch_state.return_value = {"balance": 500}
        state_authority_registry.register_authority("default", mock_connector)

        assertion = {
            "target": "external_state",
            "property": "balance",
            "expected": 500,
        }
        val, prop = await verifier._resolve_target(
            assertion, sandbox=None, history=[], shim_snapshots={}
        )
        assert val["balance"] == 500
        assert prop == "balance"

    @pytest.mark.asyncio
    async def test_parity_verifier_unobserved_source_in_verify_state_parity(self):
        session_mock = MagicMock()
        session_mock.scenario = {}
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        node = {
            "expected_outcome": [
                {
                    "target": "authority:missing_auth_service",
                    "expected": "ANY",
                }
            ],
            "timeout": 0.05,
        }
        all_passed, evidence = await verifier.verify_state_parity(
            node=node,
            sandbox=None,
            history=[],
            state_before={},
        )
        assert all_passed is False
        assert evidence[0]["invalid"] is True
        assert evidence[0]["outcome"] == "INVALID"

    def test_parity_verifier_before_value_resolution_paths(self):
        session_mock = MagicMock()
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        # 1. state_before is None
        assert verifier._before_value(None, {"target": "authority:test"}, None) is None

        # 2. target is message or shim -> returns None
        assert verifier._before_value({"a": 1}, {"target": "message"}, "a") is None

        # 3. target is authority with no property_path -> returns entire state_before
        state_before = {"counter": 42}
        res_before = verifier._before_value(state_before, {"target": "authority:test"}, None)
        assert res_before == state_before

        # 4. target is external:test with valid property_path -> resolves path
        assert verifier._before_value(state_before, {"target": "external:test"}, "counter") == 42

        # 5. target is external_state with failing path -> catches exception and returns None
        with patch(
            "eval_runner.utils.path_resolver.PathResolver.resolve",
            side_effect=ValueError("boom"),
        ):
            res_bad = verifier._before_value(state_before, {"target": "external_state"}, "bad_path")
            assert res_bad is None
