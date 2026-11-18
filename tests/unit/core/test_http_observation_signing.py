"""Built-in HTTP receipts reuse the system signer and public trust without HMAC."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.reference.signing import LocalEd25519SigningBackend
from eval_runner.session_components.state_parity import SessionStateParityVerifier
from eval_runner.state_authority import (
    ExternalStateAuthorityRegistry,
    HttpStateAuthorityConnector,
    canonical_receipt_payload_bytes,
    verify_connector_receipt_authenticity,
)


@pytest.fixture
def observation_identity(tmp_path, monkeypatch):
    root = tmp_path / "trust"
    monkeypatch.setattr(config, "TRUST_ROOT", root)
    for variable in (
        "AGENTV_STATE_AUTHORITY_KEY",
        "STATE_AUTHORITY_KEY",
        "FLIGHT_RECORDER_KEY_PATH",
        "CORE_ARTIFACT_SIGNING_PEM",
        "CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID",
        "AES_PUBLIC_KEY_SYSTEM_ID",
    ):
        monkeypatch.delenv(variable, raising=False)
    private = IdentityService._provision_local_identity("system_id")
    monkeypatch.setattr(
        "eval_runner.state_authority._validate_external_authority_url", lambda url: url
    )

    def forbidden_hmac_lookup():
        raise AssertionError("Built-in observations must not resolve an HMAC secret")

    monkeypatch.setattr(
        "eval_runner.state_authority.get_state_authority_trust_key", forbidden_hmac_lookup
    )
    return private, root


class ConfiguredObserverBackend:
    requires_private_key_material = False
    identity = "system_id"

    def __init__(self, private):
        self.private = private
        self.calls = []

    def can_sign(self):
        return True

    def sign_payload(self, payload, key_identifier):
        self.calls.append((payload, key_identifier))
        assert key_identifier == self.identity
        return self.private.sign(payload).hex()


@pytest.mark.parametrize("backend_kind", ["local", "configured", "path", "inline"])
def test_http_receipts_reuse_system_signer_without_hmac(
    observation_identity, monkeypatch, backend_kind
):
    private, root = observation_identity
    backend = (
        ConfiguredObserverBackend(private)
        if backend_kind == "configured"
        else LocalEd25519SigningBackend()
    )
    if backend_kind == "path":
        monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(root / "system_id/private_key.pem"))
    elif backend_kind == "inline":
        monkeypatch.setenv(
            "CORE_ARTIFACT_SIGNING_PEM",
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
        )
    connector = HttpStateAuthorityConnector(
        "https://authority.example/state",
        default_headers={"Authorization": "Bearer fixture"},
        signing_backend=backend,
    )
    receipt = connector.observation_identity(
        response_digest="sha3_256:state", execution_id="review:1", phase="pre", run_id="run-1"
    )["connector_receipt"]
    assert receipt["connector_id"] == "system_id"
    assert receipt["algorithm"] == "ed25519"
    assert receipt["profile"] == "agentv.connector-receipt.v2"
    assert verify_connector_receipt_authenticity(receipt)
    assert not (root / "state_authority.key").exists()
    if backend_kind == "configured":
        assert backend.calls == [(canonical_receipt_payload_bytes(receipt), "system_id")]
    # Detached verification retains only the configured public anchor.
    (root / "system_id/private_key.pem").unlink()
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    with patch.object(
        IdentityService,
        "get_private_key",
        side_effect=AssertionError("No issuer secrets in verification"),
    ):
        assert verify_connector_receipt_authenticity(receipt)
    for field in (
        "source_id",
        "connector_id",
        "request",
        "response_digest",
        "execution_id",
        "run_id",
        "phase",
        "timestamp",
    ):
        modified = copy.deepcopy(receipt)
        modified[field] = "changed"
        assert not verify_connector_receipt_authenticity(modified), field


@pytest.mark.parametrize(
    "failure", ["unavailable", "outage", "short_signature", "wrong_key", "envelope"]
)
def test_http_observer_never_falls_back_from_selected_backend(
    observation_identity, monkeypatch, failure
):
    private, _ = observation_identity
    backend = ConfiguredObserverBackend(private)
    if failure == "unavailable":
        backend.can_sign = lambda: False
    elif failure == "outage":

        def outage(*args):
            raise ConnectionError("managed signer outage")

        backend.sign_payload = outage
    elif failure == "short_signature":
        backend.sign_payload = lambda *args: "00"
    elif failure == "wrong_key":
        backend.private = ed25519.Ed25519PrivateKey.generate()
    else:
        backend.sign_payload = lambda *args: {"signature": "unversioned"}
    with patch.object(
        IdentityService, "get_private_key", side_effect=AssertionError("No local fallback")
    ):
        with pytest.raises((RuntimeError, ConnectionError, ValueError, InvalidSignature)):
            HttpStateAuthorityConnector(
                "https://authority.example/state", signing_backend=backend
            ).observation_identity()


@pytest.mark.asyncio
async def test_session_observation_uses_its_selected_backend(observation_identity, monkeypatch):
    private, _ = observation_identity
    backend = ConfiguredObserverBackend(private)
    scenario = {
        "metadata": {
            "state_authorities": {
                "orders": {
                    "url": "https://authority.example/state",
                    "headers": {"Authorization": "Bearer fixture"},
                }
            }
        }
    }
    session = SimpleNamespace(
        signing_backend=backend,
        scenario=scenario,
        run_id="selected-run",
        current_execution_instance_id="review:1",
        execution_mode="diagnostic",
    )
    verifier = SessionStateParityVerifier(session)
    with patch.object(
        HttpStateAuthorityConnector,
        "fetch_state",
        new_callable=AsyncMock,
        return_value={"status": "ready"},
    ):
        observations = await verifier.capture_external_prestate(
            {
                "id": "review",
                "expected_outcome": [{"target": "authority:orders", "property": "status"}],
            },
            None,
            [],
        )
    receipt = observations["authority:orders"]["observation_identity"]["connector_receipt"]
    assert len(backend.calls) == 2
    assert receipt["phase"] == "pre"
    assert verify_connector_receipt_authenticity(receipt)


def test_registered_independent_observer_keeps_its_identity(observation_identity):
    private, _ = observation_identity
    independent = SimpleNamespace(
        observation_identity=lambda: {"connector_id": "independent-observer"}
    )
    registry = ExternalStateAuthorityRegistry()
    registry.register_authority("source", independent)
    resolved = registry.get_connector("source", signing_backend=ConfiguredObserverBackend(private))
    assert resolved is independent
    assert resolved.observation_identity()["connector_id"] == "independent-observer"


def test_registered_http_signer_binding_is_run_local(observation_identity):
    private, _ = observation_identity
    registry = ExternalStateAuthorityRegistry()
    registered = HttpStateAuthorityConnector("https://authority.example/state")
    registry.register_authority("source", registered)
    first, second = ConfiguredObserverBackend(private), ConfiguredObserverBackend(private)
    first_connector = registry.get_connector("source", signing_backend=first)
    second_connector = registry.get_connector("source", signing_backend=second)
    first_connector.observation_identity()
    second_connector.observation_identity()
    assert len(first.calls) == len(second.calls) == 1
    assert registered.signing_backend is None
    assert first_connector.signing_backend is first
    assert second_connector.signing_backend is second


def test_local_signer_rejects_mismatched_system_anchor(observation_identity, monkeypatch):
    _, root = observation_identity
    other = ed25519.Ed25519PrivateKey.generate()
    path = root / "different-system-key.pem"
    path.write_bytes(
        other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(path))
    with pytest.raises(ValueError, match="does not match its public trust anchor"):
        HttpStateAuthorityConnector("https://authority.example/state").observation_identity()


def test_independent_http_identity_does_not_inherit_system_credentials(
    observation_identity, monkeypatch
):
    system_key, _ = observation_identity
    IdentityService._provision_local_identity("independent_observer")
    monkeypatch.setenv(
        "CORE_ARTIFACT_SIGNING_PEM",
        system_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    backend = LocalEd25519SigningBackend()
    backend.identity = "independent_observer"
    observer = HttpStateAuthorityConnector(
        "https://authority.example/state", signing_backend=backend
    )
    registry = ExternalStateAuthorityRegistry()
    registry.register_authority("independent", observer)
    resolved = registry.get_connector(
        "independent", signing_backend=ConfiguredObserverBackend(system_key)
    )
    assert resolved is observer
    receipt = resolved.observation_identity()["connector_receipt"]
    assert receipt["connector_id"] == "independent_observer"
    assert verify_connector_receipt_authenticity(receipt)
    assert not verify_connector_receipt_authenticity(dict(receipt, connector_id="system_id"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,headers",
    [
        ("https://authority.example/state", {"Authorization": "Bearer fixture"}),
        ("https://authority.example/state", {}),
        ("http://127.0.0.1:8080/healthcare/state", {}),
    ],
)
@pytest.mark.parametrize("agent", [None, "http://127.0.0.1:8080/agent"])
async def test_http_state_transition_verifies_with_public_trust_only(
    observation_identity, url, headers, agent
):
    from eval_runner.certification_truth import state_claim_failures

    private, root = observation_identity
    backend = ConfiguredObserverBackend(private)
    node = {
        "id": "review",
        "expected_outcome": [
            {
                "oracle_id": "orders:settled",
                "target": "authority:orders",
                "property": "status",
                "expected": "settled",
            }
        ],
    }
    scenario = {
        "metadata": {
            "agent": agent,
            "state_authorities": {"orders": {"url": url, "headers": headers}},
        },
        "workflow": {"nodes": [node], "edges": []},
    }
    session = SimpleNamespace(
        signing_backend=backend,
        scenario=scenario,
        run_id="public-state-run",
        current_execution_instance_id="review:1",
        execution_mode="live",
    )
    verifier = SessionStateParityVerifier(session)
    with patch.object(
        HttpStateAuthorityConnector,
        "fetch_state",
        new_callable=AsyncMock,
        side_effect=[{"status": "pending"}, {"status": "settled"}],
    ):
        before = await verifier.capture_external_prestate(node, None, [])
        passed, evidence = await verifier.verify_state_parity(
            node, None, [], external_state_before=before
        )
    assert passed
    assert verifier.preexecution_failure(node, before) is None
    for phase in ("pre", "post"):
        identity = evidence[0][f"{phase}_observation_identity"]
        assert identity["transport"] == url.split(":", 1)[0]
        assert identity["authenticated"] is (url.startswith("https:") and bool(headers))
        assert verify_connector_receipt_authenticity(identity["connector_receipt"])
    assert evidence[0]["pre_observation_identity"]["connector_id"] == "system_id"
    events = [
        {
            "event": "execution_graph_node",
            "scenario_node_id": "review",
            "execution_instance_id": "review:1",
            "status": "completed",
            "transition_evidence": evidence,
        }
    ]
    (root / "system_id/private_key.pem").unlink()
    with patch.object(
        IdentityService,
        "get_private_key",
        side_effect=AssertionError("Public verification must not read issuer keys"),
    ):
        assert state_claim_failures(scenario, events, run_id="public-state-run") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [True, False])
async def test_capture_does_not_replace_mismatched_source_receipt(
    observation_identity, authenticated
):
    from eval_runner.state_authority import (
        bound_state_snapshot,
        create_authenticated_connector_receipt,
    )

    private, _ = observation_identity
    source_receipt = create_authenticated_connector_receipt(
        "independent-source",
        "source-id",
        is_authenticated=authenticated,
        signing_key=private,
        response_digest=bound_state_snapshot({"status": "original"})[1],
        phase="pre",
        run_id="source-run",
        execution_id="review:1",
    )
    unchanged = copy.deepcopy(source_receipt)
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    verifier._observation_identities.set(
        {
            "authority:source": {
                "authenticated": authenticated,
                "connector_id": "independent-source",
                "connector_receipt": source_receipt,
            }
        }
    )
    with patch.object(
        verifier,
        "_resolve_target",
        new_callable=AsyncMock,
        return_value=({"status": "changed"}, None),
    ):
        observations = await verifier.capture_external_prestate(
            {"id": "review", "expected_outcome": [{"target": "authority:source"}]}, None, []
        )
    assert observations["authority:source"]["invalid"] is True
    assert observations["authority:source"]["error_type"] == "ObservationReceiptMismatch"
    assert source_receipt == unchanged
