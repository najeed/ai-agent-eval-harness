import sys
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AG2AdapterPlugin
from eval_runner.events import CoreEvents


@pytest.mark.asyncio
async def test_autogen_on_discover_adapters():
    adapter = AG2AdapterPlugin()
    registry = MagicMock()
    adapter.on_discover_adapters(registry)
    # Registry should have ag2 and autogen
    registry.register.assert_any_call("ag2", adapter.execute_autogen_query)
    registry.register.assert_any_call("autogen", adapter.execute_autogen_query)


@pytest.mark.asyncio
async def test_autogen_remote_explicit():
    adapter = AG2AdapterPlugin()
    # Test with explicit URL in payload
    payload = {"agent_id": "test_agent", "message": "hello", "url": "http://remote-api.com"}

    with patch.object(adapter, "_execute_remote_api", new_callable=AsyncMock) as mock_remote:
        mock_remote.return_value = {"status": "success"}
        result = await adapter.execute_autogen_query(payload)
        mock_remote.assert_called_once_with(payload, "http://remote-api.com", None)
        assert result == {"status": "success"}

    # Test with endpoint argument
    payload = {"agent_id": "test_agent", "message": "hello"}
    with patch.object(adapter, "_execute_remote_api", new_callable=AsyncMock) as mock_remote:
        mock_remote.return_value = {"status": "success"}
        result = await adapter.execute_autogen_query(payload, endpoint="http://endpoint.com")
        mock_remote.assert_called_once_with(payload, "http://endpoint.com", None)


@pytest.mark.asyncio
async def test_autogen_sdk_missing_no_fallback():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent", "message": "hello"}

    with (
        patch("eval_runner.adapters.autogen.config", spec=[]),
        patch("eval_runner.adapters.autogen.emit") as mock_emit,
    ):
        # Simulate autogen not installed
        with patch.dict(sys.modules, {"autogen": None}):
            # We need to ensure the code that does 'import autogen' fails
            # In autogen.py:
            # try:
            #     import autogen
            #     is_installed = True

            # Since it's inside the function, we can patch the import
            def mock_import(name, *args, **kwargs):
                if name == "autogen":
                    raise ImportError("SDK not installed")
                return MagicMock()

            with patch("builtins.__import__", side_effect=mock_import):
                result = await adapter.execute_autogen_query(payload)
                assert result["status"] == "error"
                assert "SDK not installed" in result["message"]
                mock_emit.assert_any_call(CoreEvents.ERROR, {"message": ANY})


@pytest.mark.asyncio
async def test_autogen_sdk_missing_with_fallback():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent", "message": "hello"}

    # Mock config to have a fallback URL
    mock_config = MagicMock()
    mock_config.AUTOGEN_API_URL = "http://fallback.com"

    with (
        patch("eval_runner.adapters.autogen.config", mock_config),
        patch("eval_runner.adapters.autogen.emit") as mock_emit,
        patch.object(adapter, "_execute_remote_api", new_callable=AsyncMock) as mock_remote,
    ):
        mock_remote.return_value = {"status": "success", "mode": "remote-fallback"}

        # Simulate autogen not installed
        def mock_import(name, *args, **kwargs):
            if name == "autogen":
                raise ImportError("SDK not installed")
            return MagicMock()

        with patch("builtins.__import__", side_effect=mock_import):
            await adapter.execute_autogen_query(payload)
            mock_remote.assert_called_once_with(payload, "http://fallback.com", None)
            mock_emit.assert_any_call(
                CoreEvents.TURN_START,
                {
                    "adapter": "autogen",
                    "agent_id": "test_agent",
                    "message": "hello",
                    "mode": "remote-fallback",
                },
                span_context=None,
            )


@pytest.mark.asyncio
async def test_autogen_logic_path_execution():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent", "metadata": {"logic_path": "mock_module:mock_handler"}}

    mock_autogen = MagicMock()
    mock_autogen.__version__ = "0.2.0"

    mock_handler = AsyncMock()
    mock_chat_result = MagicMock()
    mock_chat_result.chat_history = [{"content": "Final Answer: 42"}]
    mock_handler.return_value = mock_chat_result

    mock_module = MagicMock()
    mock_module.mock_handler = mock_handler

    with (
        patch.dict(sys.modules, {"autogen": mock_autogen}),
        patch("importlib.import_module", return_value=mock_module),
    ):
        result = await adapter.execute_autogen_query(payload)

        assert result["status"] == "success"
        assert result["output"] == "Final Answer: 42"
        assert result["metadata"]["logic_path"] == "mock_module:mock_handler"
        assert result["metadata"]["version"] == "0.2.0"


@pytest.mark.asyncio
async def test_autogen_simulation_mode():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent"}

    mock_autogen = MagicMock()

    with (
        patch.dict(sys.modules, {"autogen": mock_autogen}),
        patch("eval_runner.adapters.autogen.emit") as mock_emit,
    ):
        result = await adapter.execute_autogen_query(payload)

        assert result["status"] == "success"
        assert "Simulation" in result["output"]
        assert result["metadata"]["mode"] == "simulated"
        mock_emit.assert_any_call(
            CoreEvents.CHAIN_START,
            {"adapter": "autogen", "agent_id": "test_agent", "protocol": "v1", "mode": "simulated"},
        )


@pytest.mark.asyncio
async def test_autogen_execute_remote_api_success():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "remote_agent"}
    url = "http://remote-api.com"

    mock_response = MagicMock()
    mock_response.status = 200
    # Mock json() to return an awaitable
    mock_response.json = MagicMock(
        return_value=AsyncMock(return_value={"output": "Remote Success"})()
    )
    mock_response.raise_for_status = MagicMock(return_value=None)

    # Mock context manager for post
    mock_post_cm = MagicMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post.return_value = mock_post_cm

    with (
        patch("eval_runner.adapters.common.SessionManager.get_session", return_value=mock_session),
        patch("eval_runner.adapters.autogen.emit"),
    ):
        result = await adapter._execute_remote_api(payload, url)

        assert result["status"] == "success"
        assert result["output"] == "Remote Success"
        assert result["metadata"]["mode"] == "remote"


@pytest.mark.asyncio
async def test_autogen_execute_remote_api_failure():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "remote_agent"}
    url = "http://remote-api.com"

    mock_response = MagicMock()
    mock_response.status = 500
    # Mock raise_for_status to return something awaitable if needed, or just throw
    mock_response.raise_for_status = MagicMock(
        return_value=AsyncMock(side_effect=Exception("HTTP Error"))()
    )

    # Mock context manager for post
    mock_post_cm = MagicMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post.return_value = mock_post_cm

    with (
        patch("eval_runner.adapters.common.SessionManager.get_session", return_value=mock_session),
        patch("eval_runner.adapters.autogen.emit"),
    ):
        result = await adapter._execute_remote_api(payload, url)

        assert result["status"] == "error"
        assert "Remote API failed" in result["message"]


@pytest.mark.asyncio
async def test_autogen_simulation_sdk_missing():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent"}

    # Force ImportError for autogen in simulation
    def mock_import(name, *args, **kwargs):
        if name == "autogen":
            raise ImportError("AG2/AutoGen SDK not installed")
        return MagicMock()

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError, match="AG2/AutoGen SDK not installed"):
            await adapter._execute_simulation(payload)


@pytest.mark.asyncio
async def test_autogen_exception_handling():
    adapter = AG2AdapterPlugin()
    payload = {"agent_id": "test_agent"}

    with patch("eval_runner.adapters.autogen.emit") as mock_emit:
        # Trigger an unexpected exception
        with patch(
            "eval_runner.adapters.autogen.DualNormalizationHub.normalize_text",
            side_effect=Exception("Boom"),
        ):
            # We need to get past the SDK check
            with patch.dict(sys.modules, {"autogen": MagicMock()}):
                # And use a logic path to trigger the crash
                payload["metadata"] = {"logic_path": "m:f"}
                mock_handler = AsyncMock(return_value=MagicMock())
                mock_module = MagicMock()
                mock_module.f = mock_handler
                with patch("importlib.import_module", return_value=mock_module):
                    result = await adapter.execute_autogen_query(payload)
                    assert result["status"] == "error"
                    assert "AG2 execution failed: Boom" in result["message"]
                    mock_emit.assert_any_call(CoreEvents.ERROR, {"message": ANY})
