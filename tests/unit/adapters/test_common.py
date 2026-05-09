from unittest.mock import AsyncMock

import aiohttp
import pytest

from eval_runner.adapters.common import BaseAdapter, SessionManager


@pytest.mark.asyncio
async def test_session_manager_singleton():
    """Verify that SessionManager returns the same session instance."""
    session1 = await SessionManager.get_session()
    session2 = await SessionManager.get_session()

    assert session1 is session2
    assert not session1.closed

    await SessionManager.close_all()
    assert session1.closed
    assert SessionManager._session is None


@pytest.mark.asyncio
async def test_base_adapter_retry_success():
    """Verify that call_with_retry succeeds after transient failures."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock()

    # Simulate: 503 -> 429 -> 200
    func.side_effect = [
        aiohttp.ClientResponseError(None, None, status=503),
        aiohttp.ClientResponseError(None, None, status=429),
        "success_data",
    ]

    # We use a small base_delay for fast testing
    result = await adapter.call_with_retry(func, max_attempts=3, base_delay=0.01)

    assert result == "success_data"
    assert func.call_count == 3


@pytest.mark.asyncio
async def test_base_adapter_retry_exhausted():
    """Verify that call_with_retry raises after max attempts."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock()

    func.side_effect = aiohttp.ClientResponseError(None, None, status=502)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await adapter.call_with_retry(func, max_attempts=2, base_delay=0.01)

    assert exc.value.status == 502
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_no_retry_on_401():
    """Verify that call_with_retry does NOT retry on non-transient errors (e.g. 401)."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock()

    func.side_effect = aiohttp.ClientResponseError(None, None, status=401)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await adapter.call_with_retry(func, max_attempts=3, base_delay=0.01)

    assert exc.value.status == 401
    assert func.call_count == 1
