from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.openapi import DualNormalizationHub, adapter


class MockResponse:
    def __init__(self, status=200, json_data=None, headers=None):
        self.status = status
        self._json_data = json_data or {}
        self.headers = headers or {}

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_session():
    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = session_instance
        yield session_instance


@pytest.mark.asyncio
async def test_openapi_adapter_spec_discovery_success(mock_session):
    # Mock spec discovery (GET) and execution (POST)
    mock_session.get.return_value = MockResponse(json_data={"info": {"title": "Test API"}})
    mock_session.request.return_value = MockResponse(json_data={"status": "completed"})

    payload = {"input_payload": {"key": "val"}}
    res = await adapter(payload, "http://api/v1")

    assert res["action"] == "final_answer"
    assert mock_session.get.called
    assert mock_session.request.called


@pytest.mark.asyncio
async def test_openapi_adapter_spec_discovery_failure(mock_session):
    # Mock spec discovery failure (404)
    mock_session.get.return_value = MockResponse(status=404)
    mock_session.request.return_value = MockResponse(json_data={"status": "completed"})

    res = await adapter({}, "http://api/v1")
    assert res["action"] == "final_answer"  # Still works even if spec fails


@pytest.mark.asyncio
async def test_openapi_adapter_polling_location_absolute(mock_session):
    # Mock 202 with absolute Location header
    mock_session.get.side_effect = [
        MockResponse(json_data={"info": {"title": "Test"}}),  # Spec
        MockResponse(json_data={"status": "completed"}),  # First poll poll
    ]
    mock_session.request.return_value = MockResponse(
        status=202, headers={"Location": "http://api/v1/status/123"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        res = await adapter({}, "http://api/v1")

    assert res["action"] == "final_answer"
    # Verify it pulled from the location header
    mock_session.get.assert_any_call("http://api/v1/status/123")


@pytest.mark.asyncio
async def test_openapi_adapter_polling_location_relative(mock_session):
    # Mock 202 with relative Location header
    mock_session.get.side_effect = [
        MockResponse(json_data={"info": {"title": "Test"}}),  # Spec
        MockResponse(json_data={"status": "completed"}),  # First poll poll
    ]
    mock_session.request.return_value = MockResponse(
        status=202, headers={"Location": "/status/123"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        # Use a trailing slash in the base URL to ensure relative joins include the path segment
        res = await adapter({}, "http://api/v1/")

    assert res["action"] == "final_answer"
    # Verify it joined the URL correctly (Absolute from root of domain)
    mock_session.get.assert_any_call("http://api/status/123")


@pytest.mark.asyncio
async def test_openapi_adapter_polling_body_link(mock_session):
    # Mock 202 with no header, but link in body
    mock_session.get.side_effect = [
        MockResponse(json_data={"info": {"title": "Test"}}),  # Spec
        MockResponse(json_data={"status": "completed"}),  # First poll poll
    ]
    mock_session.request.return_value = MockResponse(
        status=202, json_data={"status_url": "http://api/v1/status/body"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        res = await adapter({}, "http://api/v1")

    assert res["action"] == "final_answer"
    mock_session.get.assert_any_call("http://api/v1/status/body")


@pytest.mark.asyncio
async def test_openapi_adapter_polling_timeout(mock_session):
    # Mock continuous processing until timeout
    mock_session.get.return_value = MockResponse(json_data={"status": "processing"})
    mock_session.request.return_value = MockResponse(
        status=202, headers={"Location": "http://api/v1/status/123"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        # Mock max_attempts to be small for speed
        with patch("eval_runner.adapters.openapi._poll_for_result") as mock_poll:
            mock_poll.return_value = {"action": "error", "content": "timeout"}
            res = await adapter({}, "http://api/v1")

    assert res["action"] == "error"


def test_normalization_hub_terminal_keywords():
    assert DualNormalizationHub.normalize({"status": "rejected"}, 200) == "final_answer"
    assert DualNormalizationHub.normalize({"state": "success"}, 200) == "final_answer"


def test_normalization_hub_error_keywords():
    assert DualNormalizationHub.normalize({"status": "failure"}, 200) == "error"
    assert DualNormalizationHub.normalize({"result": "exception"}, 200) == "error"


def test_normalization_hub_invalid_override(caplog):
    overrides = {"WAITING": "not_an_action"}
    # Should ignore and log warning
    res = DualNormalizationHub.normalize({"status": "WAITING"}, 200, overrides=overrides)
    assert res == "hitl_pause"  # 'waiting' maps to hitl_pause naturally via heuristics
    assert "Invalid override action" in caplog.text


def test_normalization_hub_agnostic_mapping_keys():
    # Test different keys for status discovery
    assert DualNormalizationHub.normalize({"phase": "waiting"}, 200) == "hitl_pause"
    assert DualNormalizationHub.normalize({"outcome": "review"}, 200) == "hitl_pause"
    assert DualNormalizationHub.normalize({"decision": "pending"}, 200) == "hitl_pause"


def test_normalization_hub_agnostic_mapping_heuristic():
    # Test scanning logic for keys containing 'status'
    assert DualNormalizationHub.normalize({"my_status_field": "pause"}, 200) == "hitl_pause"
    assert DualNormalizationHub.normalize({"current_state": "human"}, 200) == "hitl_pause"


@pytest.mark.asyncio
async def test_openapi_adapter_spec_discovery_exception(mock_session):
    # Mock spec discovery throwing an exception (e.g., connection timeout)
    mock_session.get.side_effect = Exception("Connection Failed")
    mock_session.request.return_value = MockResponse(json_data={"status": "completed"})

    res = await adapter({}, "http://api/v1")
    assert res["action"] == "final_answer"


@pytest.mark.asyncio
async def test_openapi_adapter_sync_hitl_pause(mock_session):
    # Mock sync response that maps to hitl_pause with 200 OK
    mock_session.get.return_value = MockResponse(json_data={"info": {"title": "Test"}})
    mock_session.request.return_value = MockResponse(
        status=200, json_data={"status": "processing", "message": "Still busy"}
    )

    res = await adapter({}, "http://api/v1")
    assert res["action"] == "hitl_pause"
    assert "Still busy" in res["content"]


@pytest.mark.asyncio
async def test_openapi_adapter_poll_parse_error(mock_session):
    # Mock poll returning invalid JSON
    mock_session.get.side_effect = [
        MockResponse(json_data={"info": {"title": "Test"}}),  # Spec
        # First poll: return invalid JSON (mock json() to throw)
        MockResponse(json_data={}),
        # Second poll: success
        MockResponse(json_data={"status": "completed"}),
    ]
    # Patch the first poll response to throw on .json()
    # side_effect on the response object's json method
    res1 = MockResponse(json_data={})
    res1.json = AsyncMock(side_effect=Exception("Corrupt JSON"))

    mock_session.get.side_effect = [
        MockResponse(json_data={"info": {"title": "Test"}}),
        res1,
        MockResponse(json_data={"status": "completed"}),
    ]

    mock_session.request.return_value = MockResponse(
        status=202, headers={"Location": "http://api/v1/status/123"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        res = await adapter({}, "http://api/v1")

    assert res["action"] == "final_answer"
    # Verify it polled twice (plus spec)
    assert mock_session.get.call_count == 3
