import asyncio
from aiohttp import web
import sys

async def handle_chat(request):
    return web.json_response({
        "summary": "Quickstart Agent Online",
        "action": "final_answer"
    })

async def run_server():
    app = web.Application()
    app.router.add_post("/execute_task", handle_chat)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 5001)
    await site.start()
    print("Agent started on http://localhost:5001")
    # Keep alive for testing
    await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass
