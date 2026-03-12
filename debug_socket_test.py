
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.adapters import socket_adapter

async def test_debug():
    payload = {"data": "query"}
    address = "tcp:localhost:9999"
    
    async def mock_readline_coro():
        return (json.dumps({"action": "final_answer", "content": "socket_success"}) + "\n").encode()

    with patch("asyncio.open_connection") as mock_conn:
        mock_reader = MagicMock()
        mock_reader.readline = AsyncMock(side_effect=mock_readline_coro)
        
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        
        mock_conn.return_value = (mock_reader, mock_writer)
        
        try:
            result = await socket_adapter(payload, address)
            print(f"SUCCESS: {result}")
        except Exception as e:
            import traceback
            print("FAILURE:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_debug())
