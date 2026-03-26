import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.adapters import http_adapter, local_subprocess_adapter, socket_adapter


@pytest.mark.asyncio
async def test_http_adapter_success():
    payload = {"test": "data"}
    endpoint = "http://example.com/api"

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "action": "final_answer",
            "content": "success",
        }
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await http_adapter(payload, endpoint)
        assert result["content"] == "success"
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_local_subprocess_adapter_success():
    payload = {"task_description": "do something"}
    command = "python -c 'print(\"dummy\")'"

    with patch("asyncio.create_subprocess_shell") as mock_sub:
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(
                json.dumps({"action": "final_answer", "content": "local_success"}).encode(),
                b"",
            )
        )
        mock_proc.returncode = 0
        mock_sub.return_value = mock_proc

        result = await local_subprocess_adapter(payload, command)
        assert result["content"] == "local_success"
        mock_sub.assert_called_once()


@pytest.mark.asyncio
async def test_socket_adapter_tcp_success():
    payload = {"data": "query"}
    address = "tcp:localhost:9999"

    with patch("asyncio.open_connection") as mock_conn:
        mock_reader = AsyncMock()
        mock_reader.readline.return_value = (
            json.dumps({"action": "final_answer", "content": "socket_success"}) + "\n"
        ).encode()

        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()  # Crucial fix
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_conn.return_value = (mock_reader, mock_writer)

        result = await socket_adapter(payload, address)
        assert result["content"] == "socket_success"
        mock_conn.assert_called_once()
        mock_writer.write.assert_called()
