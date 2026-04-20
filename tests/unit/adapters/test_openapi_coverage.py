from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from eval_runner.adapters.openapi import DualNormalizationHub, _poll_for_result, adapter

# --- 1. Normalization Hub Logic ---


def test_normalization_hub_invalid_action(caplog):
    """Verify that the hub logs a warning for invalid override actions."""
    overrides = {"STATUS_X": "invalid_action"}
    res = DualNormalizationHub.normalize({"status": "STATUS_X"}, 200, overrides=overrides)

    assert "Invalid override action 'invalid_action'" in caplog.text
    # Should fall through to heuristics
    assert res == "final_answer"


def test_normalization_hub_semantic_match_keys(caplog):
    """Verify semantic matching on 'state' and 'result' keys in overrides."""
    overrides = {"STALLED": "hitl_pause"}
    # Match on 'state'
    res = DualNormalizationHub.normalize({"state": "STALLED"}, 200, overrides=overrides)
    assert res == "hitl_pause"

    # Match on 'result'
    res = DualNormalizationHub.normalize({"result": "stalled"}, 200, overrides=overrides)
    assert res == "hitl_pause"


def test_normalization_hub_key_scanning_fallback():
    """Verify that the hub scans all first-level keys if primary indicators are missing."""
    # Key 'custom_status_field' contains 'status'
    response = {"custom_status_field": "review_required", "data": 123}
    res = DualNormalizationHub.normalize(response, 200)
    assert res == "hitl_pause"  # 'review' is in HITL_KEYWORDS


def test_normalization_hub_error_and_terminal_heuristics():
    """Verify error and terminal state detections via heuristics."""
    assert DualNormalizationHub.normalize({"status": "crash_detected"}, 200) == "error"
    assert DualNormalizationHub.normalize({"status": "approved_final"}, 200) == "final_answer"


# --- 2. Adapter Polling & Spec Discovery ---


@pytest.mark.asyncio
async def test_adapter_spec_discovery_failure():
    """Verify adapter continues if /openapi.json fetch fails."""
    payload = {"input_payload": {"key": "val"}}
    endpoint = "http://api.example.com/run"

    with (
        patch("aiohttp.ClientSession.request") as mock_req,
        patch("aiohttp.ClientSession.get") as mock_get,
    ):
        # Spec fetch fails (404)
        mock_get.return_value.__aenter__.return_value.status = 404

        # Main request succeeds
        mock_req.return_value.__aenter__.return_value.status = 200
        mock_req.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"status": "done"}
        )

        res = await adapter(payload, endpoint)
        assert res["action"] == "final_answer"


@pytest.mark.asyncio
async def test_adapter_rest_fallback_polling():
    """Verify that the adapter constructs a best-guess status URL when no spec is available."""
    payload = {"input_payload": {"id": "123"}}
    endpoint = "http://api.example.com/run"

    with (
        patch("aiohttp.ClientSession.request") as mock_req,
        patch("aiohttp.ClientSession.get") as mock_get,
        patch("eval_runner.adapters.openapi._poll_for_result") as mock_poll,
    ):
        # 1. Spec fetch fails (empty spec)
        mock_get.return_value.__aenter__.return_value.status = 404

        # 2. Main request returns wait-state (processing)
        mock_req.return_value.__aenter__.return_value.status = 200
        mock_req.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"status": "processing", "uuid": "job-999"}
        )

        # 3. Execution
        mock_poll.return_value = {"action": "final_answer", "content": "done"}
        await adapter(payload, endpoint)

        # Verify best-guess poll URL format: {origin}/status/{uuid}
        # origin = http://api.example.com
        # uuid = job-999
        actual_poll_url = mock_poll.call_args[0][1]
        assert actual_poll_url == "http://api.example.com/status/job-999"


@pytest.mark.asyncio
async def test_adapter_spec_aware_polling():
    """Verify that the adapter resolves a status path from the OpenAPI spec."""
    payload = {"input_payload": {"id": "123"}}
    endpoint = "http://api.example.com/apply"

    mock_spec = {
        "paths": {
            "/status/{application_id}": {
                "get": {"parameters": [{"name": "application_id", "in": "path"}]}
            }
        }
    }

    with (
        patch("aiohttp.ClientSession.request") as mock_req,
        patch("aiohttp.ClientSession.get") as mock_get,
        patch("eval_runner.adapters.openapi._poll_for_result") as mock_poll,
    ):
        # 1. Provide Spec
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.json = AsyncMock(return_value=mock_spec)

        # 2. Main request returns application_id
        mock_req.return_value.__aenter__.return_value.status = 200
        mock_req.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"status": "processing", "application_id": "app-001"}
        )

        # 3. Execution
        mock_poll.return_value = {"action": "final_answer"}
        await adapter(payload, endpoint)

        # Verify resolved poll URL
        actual_poll_url = mock_poll.call_args[0][1]
        assert actual_poll_url == "http://api.example.com/status/app-001"


# --- 3. Internal Polling Loop Logic ---


@pytest.mark.asyncio
async def test_poll_for_result_error_handling():
    """Verify polling loop resilience against JSON errors and transient HTTP errors."""
    poll_url = "http://api.example.com/poll"

    with patch("aiohttp.ClientSession.get") as mock_get, patch("asyncio.sleep", return_value=None):
        # 1. First attempt: JSON Decode Error
        resp1 = AsyncMock()
        resp1.status = 200
        resp1.json.side_effect = Exception("Malformed JSON")

        # 2. Second attempt: Transient 500
        resp2 = AsyncMock()
        resp2.status = 500

        # 3. Third attempt: Success (Final Answer)
        resp3 = AsyncMock()
        resp3.status = 200
        resp3.json = AsyncMock(return_value={"status": "approved"})

        mock_get.return_value.__aenter__.side_effect = [resp1, resp2, resp3]

        async with aiohttp.ClientSession() as session:
            res = await _poll_for_result(session, poll_url, None)

        assert res["action"] == "final_answer"
        assert res["metadata"]["attempts"] == 3


@pytest.mark.asyncio
async def test_poll_for_result_timeout():
    """Verify polling loop timeout behavior."""
    poll_url = "http://api.example.com/poll"

    with patch("aiohttp.ClientSession.get") as mock_get, patch("asyncio.sleep", return_value=None):
        # Always returns 'processing'
        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"status": "processing"})
        mock_get.return_value.__aenter__.return_value = resp

        async with aiohttp.ClientSession() as session:
            # We patch max_attempts to 3 for speed
            with patch("eval_runner.adapters.openapi.MAX_POLL_ATTEMPTS", 3):
                res = await _poll_for_result(session, poll_url, None)

        assert res["action"] == "error"
        assert "timeout exceeded" in res["content"]
