import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.openapi import OpenAPIAdapterPlugin


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

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")


@pytest.fixture
def mock_session():
    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        yield session_instance


@pytest.mark.asyncio
async def test_openapi_auth_bearer_env(mock_session):
    plugin = OpenAPIAdapterPlugin()
    payload = {"metadata": {"auth": {}}}

    with patch.dict(os.environ, {"OPENAPI_TOKEN": "env-token"}):
        headers = await plugin._get_auth_header(payload)
        assert headers["Authorization"] == "Bearer env-token"


@pytest.mark.asyncio
async def test_openapi_auth_oauth2_success(mock_session):
    plugin = OpenAPIAdapterPlugin()
    payload = {
        "metadata": {
            "auth": {"client_id": "id", "client_secret": "secret", "token_url": "http://auth/token"}
        }
    }

    mock_session.post.return_value = MockResponse(json_data={"access_token": "oauth-token"})

    headers = await plugin._get_auth_header(payload)
    assert headers["Authorization"] == "Bearer oauth-token"
    mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_openapi_auth_oauth2_failure(mock_session):
    plugin = OpenAPIAdapterPlugin()
    payload = {
        "metadata": {
            "auth": {"client_id": "id", "client_secret": "secret", "token_url": "http://auth/token"}
        }
    }

    # Mock failure
    mock_session.post.side_effect = Exception("Auth Failed")

    with patch("eval_runner.adapters.openapi.logger") as mock_logger:
        headers = await plugin._get_auth_header(payload)
        assert "Authorization" not in headers
        assert mock_logger.warning.called


@pytest.mark.asyncio
async def test_openapi_auth_basic(mock_session):
    plugin = OpenAPIAdapterPlugin()
    payload = {"metadata": {"auth": {"username": "user", "password": "pass"}}}

    headers = await plugin._get_auth_header(payload)
    expected = base64.b64encode(b"user:pass").decode()
    assert headers["Authorization"] == f"Basic {expected}"


@pytest.mark.asyncio
async def test_openapi_query_missing_url():
    plugin = OpenAPIAdapterPlugin()
    res = await plugin.execute_openapi_query({})
    assert res["status"] == "error"
    assert "Missing endpoint" in res["message"]


@pytest.mark.asyncio
async def test_openapi_spec_path_discovery(mock_session):
    plugin = OpenAPIAdapterPlugin()
    # Mock spec with a custom path
    mock_session.get.return_value = MockResponse(json_data={"paths": {"/v1/apply": {"post": {}}}})
    mock_session.request.return_value = MockResponse(json_data={"status": "ok"})

    await plugin.execute_openapi_query({}, endpoint="http://api")
    # Verify request was sent to /v1/apply
    called_url = mock_session.request.call_args[0][1]
    assert called_url == "http://api/v1/apply"


@pytest.mark.asyncio
async def test_openapi_polling_processing_id(mock_session):
    plugin = OpenAPIAdapterPlugin()
    # Mock response that is 'processing' and has an application_id
    mock_session.get.side_effect = [
        MockResponse(status=404),  # Spec fail
        MockResponse(json_data={"status": "completed"}),  # Poll success
    ]
    mock_session.request.return_value = MockResponse(
        json_data={"status": "processing", "application_id": "app-123"}
    )

    with patch("asyncio.sleep", AsyncMock()):
        res = await plugin.execute_openapi_query({}, endpoint="http://api")

    assert res["action"] == "final_answer"
    # Verify polling URL was constructed correctly
    assert any("http://api/status/app-123" in str(c) for c in mock_session.get.call_args_list)


@pytest.mark.asyncio
async def test_openapi_poll_terminal_actions(mock_session):
    plugin = OpenAPIAdapterPlugin()

    # hitl_pause
    mock_session.get.return_value = MockResponse(json_data={"status": "waiting"})
    res = await plugin._poll_for_result("http://poll", {}, {})
    assert res["action"] == "hitl_pause"

    # error
    mock_session.get.return_value = MockResponse(json_data={"status": "failed"})
    res = await plugin._poll_for_result("http://poll", {}, {})
    assert res["action"] == "error"


@pytest.mark.asyncio
async def test_openapi_poll_timeout(mock_session):
    plugin = OpenAPIAdapterPlugin()
    plugin.max_poll_attempts = 2

    mock_session.get.return_value = MockResponse(json_data={"status": "processing"})

    with patch("asyncio.sleep", AsyncMock()):
        res = await plugin._poll_for_result("http://poll", {}, {})
        assert res["action"] == "error"
        assert "timeout" in res["content"]


@pytest.mark.asyncio
async def test_openapi_query_exception(mock_session):
    plugin = OpenAPIAdapterPlugin()
    mock_session.request.side_effect = Exception("Fatal Crash")

    res = await plugin.execute_openapi_query({}, endpoint="http://api")
    assert res["status"] == "error"
    assert "Fatal Crash" in res["message"]


@pytest.mark.asyncio
async def test_openapi_on_discover_adapters():
    plugin = OpenAPIAdapterPlugin()
    registry = MagicMock()
    plugin.on_discover_adapters(registry)
    registry.register.assert_called_with("openapi", plugin.execute_openapi_query)


@pytest.mark.asyncio
async def test_openapi_poll_status_400_plus(mock_session):
    plugin = OpenAPIAdapterPlugin()
    plugin.max_poll_attempts = 2

    # Mock 400 then success
    mock_session.get.side_effect = [
        MockResponse(status=400),
        MockResponse(json_data={"status": "completed"}),
    ]

    with patch("asyncio.sleep", AsyncMock()):
        res = await plugin._poll_for_result("http://poll", {}, {})
        assert res["action"] == "final_answer"


@pytest.mark.asyncio
async def test_openapi_poll_exception_recovery(mock_session):
    plugin = OpenAPIAdapterPlugin()
    plugin.max_poll_attempts = 2

    # Mock exception then success
    mock_session.get.side_effect = [
        Exception("Transient Error"),
        MockResponse(json_data={"status": "completed"}),
    ]

    with patch("asyncio.sleep", AsyncMock()):
        res = await plugin._poll_for_result("http://poll", {}, {})
        assert res["action"] == "final_answer"


@pytest.mark.asyncio
async def test_openapi_query_server_error(mock_session):
    plugin = OpenAPIAdapterPlugin()
    # Mock 500 status code
    mock_session.get.return_value = MockResponse(status=404)  # Spec
    mock_session.request.return_value = MockResponse(status=500)

    res = await plugin.execute_openapi_query({}, endpoint="http://api")
    assert res["action"] == "error"
    assert "HTTP 500" in res["message"]
