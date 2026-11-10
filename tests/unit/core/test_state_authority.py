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


@pytest.mark.asyncio
async def test_live_state_observation_rejects_unauthenticated_declared_authority():
    from types import SimpleNamespace

    session = SimpleNamespace(
        execution_mode="live",
        scenario={
            "metadata": {
                "state_authorities": {"orders": {"url": "https://authority.example/state"}}
            }
        },
    )
    connector = MagicMock()
    connector.observation_identity.return_value = {"authenticated": False}
    connector.fetch_state = AsyncMock(return_value={"status": "approved"})
    verifier = SessionStateParityVerifier(session)
    with patch.object(state_authority_registry, "get_connector", return_value=connector):
        state, path = await verifier._resolve_target(
            {"target": "authority:orders", "property": "status"}, None, [], {}
        )
    assert state is None
    assert path == "__unobserved_source__"
    connector.fetch_state.assert_not_awaited()


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
    async def test_authority_transition_evidence_uses_independent_pre_and_post_snapshots(self):
        session_mock = MagicMock()
        session_mock.scenario = {}
        verifier = SessionStateParityVerifier(session_manager=session_mock)
        connector = AsyncMock()
        connector.fetch_state.side_effect = [
            {"state": {"authorizations": []}},
            {"state": {"authorizations": [{"decision": "APPROVE"}]}},
        ]
        state_authority_registry.register_authority("healthcare_transition", connector)
        node = {
            "expected_outcome": [
                {
                    "target": "authority:healthcare_transition",
                    "property": "state.authorizations[0].decision",
                    "expected": "APPROVE",
                }
            ],
            "timeout": 0.05,
        }

        pre_state = await verifier.capture_external_prestate(node, sandbox=None, history=[])
        passed, evidence = await verifier.verify_state_parity(
            node, sandbox=None, history=[], external_state_before=pre_state
        )

        assert passed is True
        assert evidence[0]["actual_before"] is None
        assert evidence[0]["actual_after"] == "APPROVE"
        assert evidence[0]["source"] == "authority:healthcare_transition"
        assert evidence[0]["pre_snapshot_hash"].startswith("sha3_256:")
        assert evidence[0]["post_snapshot_hash"].startswith("sha3_256:")

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
        session_mock.scenario = {
            "metadata": {"state_authorities": {"url": "http://127.0.0.1:9999/state"}}
        }
        verifier = SessionStateParityVerifier(session_manager=session_mock)

        mock_connector = AsyncMock()
        mock_connector.fetch_state.return_value = {"balance": 500}
        state_authority_registry.register_authority("default", mock_connector)

        assertion = {
            "target": "external_state",
            "property": "balance",
            "expected": 500,
        }
        with patch(
            "eval_runner.state_authority.HttpStateAuthorityConnector", return_value=mock_connector
        ):
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


def test_state_authority_connector_identity_and_receipt_tokens(monkeypatch: pytest.MonkeyPatch):
    """Verify HttpStateAuthorityConnector observation identity and cryptographic tokens."""
    from eval_runner.state_authority import (
        HttpStateAuthorityConnector,
        compute_connector_receipt_token,
    )

    monkeypatch.setattr(
        "eval_runner.state_authority._validate_external_authority_url",
        lambda url: url,
    )

    # 1. Authenticated HTTPS connector
    https_conn = HttpStateAuthorityConnector(
        base_url="https://api.authority.example.com/v1",
        default_headers={"Authorization": "Bearer secret_token"},
    )
    ident_auth = https_conn.observation_identity()
    assert ident_auth["authenticated"] is True
    assert ident_auth["transport"] == "https"
    assert ident_auth["connector_id"].startswith("connector:http:")
    receipt_auth = ident_auth["connector_receipt"]
    assert receipt_auth["authenticated"] is True
    assert receipt_auth["source_id"] == ident_auth["source_id"]
    assert receipt_auth["connector_id"] == ident_auth["connector_id"]
    assert receipt_auth["retrieval_token"] == compute_connector_receipt_token(
        ident_auth["connector_id"], ident_auth["source_id"]
    )

    # 2. Unauthenticated HTTP connector
    http_conn = HttpStateAuthorityConnector(
        base_url="http://insecure.authority.local",
        default_headers={},
    )
    ident_unauth = http_conn.observation_identity()
    assert ident_unauth["authenticated"] is False
    assert ident_unauth["transport"] == "http"
    receipt_unauth = ident_unauth["connector_receipt"]
    assert receipt_unauth["authenticated"] is False
    assert receipt_unauth["retrieval_token"] == compute_connector_receipt_token(
        ident_unauth["connector_id"], ident_unauth["source_id"]
    )


def test_state_authority_receipt_tampering_and_forgery_rejection():
    """Verify authenticated connector receipt creation and authenticity verification."""
    import hashlib
    import os
    import tempfile
    from pathlib import Path

    from eval_runner import config
    from eval_runner.certification_truth import state_claim_failures
    from eval_runner.state_authority import (
        StateAuthorityKeyMissingError,
        bound_state_snapshot,
        compute_connector_receipt_token,
        create_authenticated_connector_receipt,
        get_state_authority_trust_key,
        verify_connector_receipt_authenticity,
    )
    from eval_runner.utils import crypto

    source_id = "sha3_256:" + crypto.checksum("https://api.authority.example/orders")
    connector_id = f"connector:http:{source_id}"
    resp_digest = "sha3_256:" + hashlib.sha3_256(b'{"status":"approved"}').hexdigest()

    # 1. Authentic receipt verifies cleanly
    receipt = create_authenticated_connector_receipt(
        connector_id=connector_id,
        source_id=source_id,
        is_authenticated=True,
        request_spec="GET /orders/123",
        response_digest=resp_digest,
        execution_id="exec-1",
        timestamp="2026-01-01T00:00:00Z",
    )
    assert verify_connector_receipt_authenticity(receipt) is True

    # 2. Tampered request is rejected
    receipt_tampered_req = dict(receipt)
    receipt_tampered_req["request"] = "GET /orders/999"
    assert verify_connector_receipt_authenticity(receipt_tampered_req) is False

    # 3. Tampered response_digest is rejected
    receipt_tampered_digest = dict(receipt)
    receipt_tampered_digest["response_digest"] = "sha3_256:" + "0" * 64
    assert verify_connector_receipt_authenticity(receipt_tampered_digest) is False

    # 4. Tampered MAC/signature is rejected
    receipt_tampered_mac = dict(receipt)
    receipt_tampered_mac["mac"] = "bad_forged_mac_0000"
    receipt_tampered_mac["signature"] = "bad_forged_mac_0000"
    receipt_tampered_mac.pop("retrieval_token", None)
    assert verify_connector_receipt_authenticity(receipt_tampered_mac) is False

    # 5. Non-mapping or empty receipt is rejected
    assert verify_connector_receipt_authenticity("not-a-dict") is False  # type: ignore[arg-type]
    assert verify_connector_receipt_authenticity({}) is False

    # 6. Mismatched response_digest in state_claim_failures produces failure
    assertion = {"target": "authority:orders", "property": "status", "expected": "approved"}
    scenario = {
        "metadata": {
            "agent": {"endpoint": "https://agent.example/api"},
            "state_authorities": {"orders": {"url": "https://api.authority.example/orders"}},
        },
        "workflow": {"nodes": [{"id": "node-1", "expected_outcome": [assertion]}]},
    }
    before, before_hash = bound_state_snapshot({"status": "pending"})
    after, after_hash = bound_state_snapshot({"status": "approved"})

    # Receipt claiming a different response digest than actual post_snapshot_hash
    tampered_receipt = create_authenticated_connector_receipt(
        connector_id=connector_id,
        source_id=source_id,
        is_authenticated=True,
        response_digest="sha3_256:" + "f" * 64,
    )
    row = {
        "assertion": assertion,
        "source": "authority:orders",
        "pre_snapshot_hash": before_hash,
        "post_snapshot_hash": after_hash,
        "pre_observation": before,
        "post_observation": after,
        "pre_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": connector_id,
            "connector_receipt": tampered_receipt,
        },
        "post_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": connector_id,
            "connector_receipt": tampered_receipt,
        },
        "actual_before": "pending",
        "actual_after": "approved",
        "passed": True,
    }
    events = [
        {
            "event": "execution_graph_node",
            "scenario_node_id": "node-1",
            "execution_instance_id": "node-1:attempt:1",
            "status": "completed",
            "transition_evidence": [row],
        }
    ]
    failures = state_claim_failures(scenario, events)
    assert any("InvalidIndependentStateEvidence" in f for f in failures)

    # 7. Additional branch coverage for receipt validation and trust keys
    # Environment variable trust key resolution
    os.environ["AGENTV_STATE_AUTHORITY_KEY"] = "custom_test_env_key"
    try:
        assert get_state_authority_trust_key() == b"custom_test_env_key"
    finally:
        os.environ.pop("AGENTV_STATE_AUTHORITY_KEY", None)

    # Trust root file on disk and fail-closed OSError behavior
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        key_file = tdp / "state_authority.key"
        key_file.write_bytes(b"file_based_key_123")
        old_root = getattr(config, "TRUST_ROOT", None)
        try:
            config.TRUST_ROOT = str(tdp)
            assert get_state_authority_trust_key() == b"file_based_key_123"

            # Test OSError reading key file fails closed rather than deriving synthetic keys
            def mock_read_bytes():
                raise OSError("Permission denied")

            with patch.object(Path, "read_bytes", side_effect=mock_read_bytes):
                with pytest.raises(StateAuthorityKeyMissingError):
                    get_state_authority_trust_key()
        finally:
            config.TRUST_ROOT = old_root

    # Default trust key fails closed when TRUST_ROOT is None or key missing
    old_root = getattr(config, "TRUST_ROOT", None)
    try:
        config.TRUST_ROOT = None
        with pytest.raises(StateAuthorityKeyMissingError):
            get_state_authority_trust_key()
    finally:
        config.TRUST_ROOT = old_root

    # Token-only receipt without MAC must fail verification
    token_only_receipt = {
        "connector_id": connector_id,
        "source_id": source_id,
        "authenticated": True,
        "retrieval_token": compute_connector_receipt_token(
            connector_id, source_id, key=b"custom_test_env_key"
        ),
    }
    assert (
        verify_connector_receipt_authenticity(token_only_receipt, key=b"custom_test_env_key")
        is False
    )

    bad_token_receipt = dict(token_only_receipt, retrieval_token="bad_token_123")
    assert verify_connector_receipt_authenticity(bad_token_receipt) is False

    invalid_types_receipt = {
        "connector_id": connector_id,
        "source_id": source_id,
        "mac": 12345,
        "retrieval_token": 12345,
    }
    assert verify_connector_receipt_authenticity(invalid_types_receipt) is False

    # Coverage for state_claim_failures failure branches
    # a. Receipt not mapping
    row_bad_receipt = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"], connector_receipt="not-a-dict"
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_bad_receipt],
                }
            ],
        )
    )

    # b. Receipt source mismatch
    row_source_mismatch = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"],
            connector_receipt=dict(receipt, source_id="sha3_256:other"),
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_source_mismatch],
                }
            ],
        )
    )

    # c. Receipt unauthenticated
    row_unauth = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"], connector_receipt=dict(receipt, authenticated=False)
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_unauth],
                }
            ],
        )
    )

    # d. Observation snapshot hash mismatch
    row_hash_mismatch = dict(row, pre_snapshot_hash="sha3_256:corrupt_hash")
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_hash_mismatch],
                }
            ],
        )
    )

    # e. Pre vs post authority mismatch
    row_diff_auth = dict(
        row,
        post_observation_identity=dict(
            row["post_observation_identity"], connector_id="connector:http:different"
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_diff_auth],
                }
            ],
        )
    )

    # f. Receipt missing response digest binding
    receipt_no_resp_digest = dict(receipt)
    receipt_no_resp_digest.pop("response_digest", None)
    row_no_resp_digest = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"],
            connector_receipt=receipt_no_resp_digest,
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_no_resp_digest],
                }
            ],
        )
    )


def test_connector_receipt_mac_binds_authenticated_field():
    """Flipping authenticated from False to True invalidates the connector receipt MAC."""
    from eval_runner.state_authority import (
        create_authenticated_connector_receipt,
        verify_connector_receipt_authenticity,
    )

    unauth_receipt = create_authenticated_connector_receipt(
        connector_id="connector:http:test",
        source_id="sha3_256:abc",
        is_authenticated=False,
        request_spec="GET /test",
        response_digest="sha3_256:123",
    )
    assert unauth_receipt["authenticated"] is False
    assert verify_connector_receipt_authenticity(unauth_receipt) is True

    # Tamper authenticated: False -> True without recomputing MAC
    tampered = dict(unauth_receipt, authenticated=True)
    assert verify_connector_receipt_authenticity(tampered) is False


def test_private_ip_guard_rejects_non_global_addresses(monkeypatch):
    """_validate_external_authority_url rejects non-global addresses unless explicit CI loopback."""
    import socket

    from eval_runner.state_authority import (
        StateAuthorityPolicyError,
        _validate_external_authority_url,
    )

    # Allowlist an external domain
    monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "https://api.partner.example")

    # If api.partner.example resolves to 10.0.0.1 (private RFC 1918), must be rejected
    mock_addrs = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
    with patch("socket.getaddrinfo", return_value=mock_addrs):
        with pytest.raises(StateAuthorityPolicyError) as exc_info:
            _validate_external_authority_url("https://api.partner.example/state")
        assert "resolves to a non-global address" in str(exc_info.value)

    # If api.partner.example resolves to 169.254.169.254 (cloud metadata), must be rejected
    mock_meta_addrs = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]
    with patch("socket.getaddrinfo", return_value=mock_meta_addrs):
        with pytest.raises(StateAuthorityPolicyError) as exc_info:
            _validate_external_authority_url("https://api.partner.example/state")
        assert "resolves to a non-global address" in str(exc_info.value)

    # Opt-in via AGENTV_ALLOW_PRIVATE_STATE_AUTHORITIES allows private IPs
    monkeypatch.setenv("AGENTV_ALLOW_PRIVATE_STATE_AUTHORITIES", "1")
    with patch("socket.getaddrinfo", return_value=mock_addrs):
        assert (
            _validate_external_authority_url("https://api.partner.example/state")
            == "https://api.partner.example/state"
        )
