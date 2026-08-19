"""
tests/unit/console/test_console_routes_hitl.py

Unit tests for eval_runner.console.routes.hitl.
Covers: GET /hitl/queue, POST /hitl/<id>/resolve, GET /hitl/stream (SSE).
"""

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner.console.routes.hitl import hitl_bp


@pytest.fixture
def hitl_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(hitl_bp, url_prefix="/api")

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# GET /hitl/queue
# ---------------------------------------------------------------------------


def test_hitl_queue_empty(hitl_client):
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg.pending.return_value = []
        res = hitl_client.get("/api/v1/hitl/queue")
    assert res.status_code == 200
    assert res.get_json()["pending"] == []


def test_hitl_queue_with_items(hitl_client):
    item = MagicMock()
    item.to_dict.return_value = {
        "id": "appr-1",
        "task_id": "t1",
        "prompt": "Confirm?",
        "action": None,
    }

    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg.pending.return_value = [item]
        res = hitl_client.get("/api/v1/hitl/queue")

    assert res.status_code == 200
    data = res.get_json()
    assert len(data["pending"]) == 1
    assert data["pending"][0]["id"] == "appr-1"


# ---------------------------------------------------------------------------
# POST /hitl/<id>/resolve
# ---------------------------------------------------------------------------


def test_hitl_resolve_missing_action(hitl_client):
    res = hitl_client.post(
        "/api/v1/hitl/appr-123/resolve",
        json={"response": "ok"},
        content_type="application/json",
    )
    assert res.status_code == 400
    assert "Invalid action" in res.get_json()["error"]


def test_hitl_resolve_invalid_action(hitl_client):
    res = hitl_client.post(
        "/api/v1/hitl/appr-123/resolve",
        json={"action": "skip"},
        content_type="application/json",
    )
    assert res.status_code == 400


def test_hitl_resolve_not_found(hitl_client):
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg.resolve.return_value = False
        res = hitl_client.post(
            "/api/v1/hitl/nonexistent/resolve",
            json={"action": "approve", "response": "yes"},
            content_type="application/json",
        )
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]


def test_hitl_resolve_approve_success(hitl_client):
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg.resolve.return_value = True
        res = hitl_client.post(
            "/api/v1/hitl/appr-456/resolve",
            json={"action": "approve", "response": "Looks good"},
            content_type="application/json",
        )
    assert res.status_code == 200
    data = res.get_json()
    assert data["resolved"] is True
    assert data["approval_id"] == "appr-456"


def test_hitl_resolve_reject_success(hitl_client):
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg.resolve.return_value = True
        res = hitl_client.post(
            "/api/v1/hitl/appr-789/resolve",
            json={"action": "reject", "response": "Unauthorized"},
            content_type="application/json",
        )
    assert res.status_code == 200
    assert res.get_json()["resolved"] is True


def test_hitl_resolve_session_user_identity_forwarded(hitl_client):
    """Verify that resolve is called with user identity from session when present."""
    # Patch the resolve endpoint's session and registry together
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        with patch("eval_runner.console.routes.hitl.session", {"user": {"id": "analyst-99"}}):
            mock_reg.resolve.return_value = True
            res = hitl_client.post(
                "/api/v1/hitl/appr-sess/resolve",
                json={"action": "approve", "response": "signed"},
                content_type="application/json",
            )

    assert res.status_code == 200
    call_args = mock_reg.resolve.call_args
    # resolved_by must match the patched session user id
    assert call_args[0][3] == "analyst-99"


def test_hitl_resolve_no_session_uses_default_resolved_by(hitl_client):
    """Verify that when session has no user, resolved_by defaults to 'root-admin'."""
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        with patch("eval_runner.console.routes.hitl.session", {}):
            mock_reg.resolve.return_value = True
            res = hitl_client.post(
                "/api/v1/hitl/appr-def/resolve",
                json={"action": "reject"},
                content_type="application/json",
            )
    assert res.status_code == 200
    call_args = mock_reg.resolve.call_args
    assert call_args[0][3] == "root-admin"


def test_hitl_resolve_resumed_from_db_auto_resumes(hitl_client):
    """Verify that resolving an approval with resumed_from_db=True triggers backend.resume()."""
    mock_appr = MagicMock()
    mock_appr.id = "appr-resumed-001"
    mock_appr.resumed_from_db = True
    mock_appr.run_id = "run-resumed-999"
    mock_appr.resumption_token = "tok_abc123"

    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg._items.get.return_value = mock_appr
        mock_reg.resolve.return_value = True
        backend_patch = (
            "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance"
        )
        with patch(backend_patch) as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend_cls.return_value = mock_backend

            res = hitl_client.post(
                "/api/v1/hitl/appr-resumed-001/resolve",
                json={"action": "approve", "response": "OK"},
                content_type="application/json",
            )

            assert res.status_code == 200
            data = res.get_json()
            assert data["resolved"] is True
            assert data["resumed"] is True
            assert data["run_id"] == "run-resumed-999"
            mock_backend.resume.assert_called_once_with(
                "run-resumed-999", resumption_token="tok_abc123", background=True
            )


def test_hitl_resolve_not_found_in_items(hitl_client):
    """Verify that resolving returns 404 when item not in _items."""
    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg._items.get.return_value = None
        res = hitl_client.post(
            "/api/v1/hitl/missing-item/resolve",
            json={"action": "approve", "response": "OK"},
            content_type="application/json",
        )
        assert res.status_code == 404


def test_hitl_resolve_resume_exception_handled(hitl_client):
    """Verify that exception in backend.resume is caught and logged."""
    mock_appr = MagicMock()
    mock_appr.id = "appr-err-001"
    mock_appr.resumed_from_db = True
    mock_appr.run_id = "run-err-999"
    mock_appr.resumption_token = "tok_err"

    with patch("eval_runner.console.routes.hitl.global_registry") as mock_reg:
        mock_reg._items.get.return_value = mock_appr
        mock_reg.resolve.return_value = True
        backend_patch = (
            "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance"
        )
        with patch(backend_patch) as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.resume.side_effect = RuntimeError("Resume connection failed")
            mock_backend_cls.return_value = mock_backend

            res = hitl_client.post(
                "/api/v1/hitl/appr-err-001/resolve",
                json={"action": "approve", "response": "OK"},
                content_type="application/json",
            )
            assert res.status_code == 200
            data = res.get_json()
            assert data["resumed"] is False


# ---------------------------------------------------------------------------
# GET /hitl/stream (SSE)
# ---------------------------------------------------------------------------


def test_hitl_stream_yields_ping_and_events(hitl_client):
    """Verify SSE stream yields initial ping, then events from queue, then cleanup."""
    res = hitl_client.get("/api/v1/hitl/stream")
    assert res.status_code == 200
    assert "text/event-stream" in res.content_type

    from eval_runner.hitl.pending import _sse_listeners

    assert len(_sse_listeners) > 0
    request_listener = _sse_listeners[-1]

    # Trigger listener to cover line 55
    request_listener("create", {"id": "evt-1"})

    iterator = res.response
    ping_1 = next(iterator)
    assert b"ping" in ping_1

    event_1 = next(iterator)
    assert b"create" in event_1
    assert b"evt-1" in event_1

    # Triggers GeneratorExit and finally block
    iterator.close()


def test_hitl_stream_empty_timeout(hitl_client):
    """Verify SSE stream handles queue Empty timeout (line 71)."""
    from queue import Empty

    with patch("eval_runner.console.routes.hitl.Queue.get", side_effect=Empty):
        res = hitl_client.get("/api/v1/hitl/stream")
        assert res.status_code == 200
        iterator = res.response

        # Connection ping (line 61)
        ping_1 = next(iterator)
        assert b"ping" in ping_1

        # Keepalive ping from Empty timeout (line 71)
        ping_2 = next(iterator)
        assert b"ping" in ping_2

        iterator.close()
