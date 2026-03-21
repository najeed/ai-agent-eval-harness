import asyncio
import aiohttp
from datetime import datetime
from . import engine
from . import reporter


async def run_playground(agent_url: str):
    """Interactive playground loop."""
    print("\n🎮 AI Agent Eval Harness - Playground")
    print(f"Agent: {agent_url}")
    print("Experiment with your agent in real-time. Type 'exit' to quit.\n")

    async with aiohttp.ClientSession() as session:
        while True:
            task = input("Ask Agent > ").strip()
            if not task or task.lower() in ["exit", "quit"]:
                break

            print("\n" + "-" * 30)
            print(f"🚀 USER: {task}")

            # Simple wrapper to use engine logic if possible,
            # but for playground we want direct feedback.
            try:
                # We mock a minimal scenario/task object for the engine logic
                # to stay consistent with how we track metrics if we wanted to.
                # For now, let's keep it direct.
                async with session.post(agent_url, json={"task_description": task}, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Use premium formatting for agent response
                        print(f"🤖 AGENT: {data.get('summary', '...')}")
                        if data.get("action") == "call_tool":
                            print(f"   🛠 Tool: {data.get('tool_name')} ({data.get('tool_params')})")
                            print(f"   📦 Output: {data.get('tool_output')}")
                        elif data.get("action") == "call_multiple_tools":
                            print(f"   🛠 Tools: {', '.join(data.get('tool_names', []))}")
                    else:
                        print(f"❌ Error {response.status}")
            except Exception as e:
                print(f"❌ Connection Error: {e}")
            print("-" * 30 + "\n")


if __name__ == "__main__":
    import os

    url = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")
    asyncio.run(run_playground(url))
