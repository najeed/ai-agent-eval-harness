import sys
import os
import aiohttp
import asyncio
from pathlib import Path


async def check_agent_reachable(url: str):
    """Checks if the agent endpoint is reachable."""
    try:
        # In Python 3.14, aiohttp might be sensitive to the loop state.
        # We explicitly pass the running loop.
        loop = asyncio.get_running_loop()
        async with aiohttp.ClientSession(loop=loop) as session:
            async with session.post(
                url,
                json={"task_description": "health_check"},
                timeout=aiohttp.ClientTimeout(total=2),
            ) as response:
                return response.status == 200 or response.status == 400
    except Exception:
        return False


async def run_doctor():
    """Environment validation logic."""
    print("\n[Doctor] MultiAgentEval - Environment Doctor\n")

    # 1. Python Version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 9):
        print(f"  ✔ Python version OK ({py_ver})")
    else:
        print(f"  ❌ Python version too old ({py_ver}). Need >= 3.9")

    # 2. Dependencies
    deps = ["aiohttp", "flask", "jsonschema", "yaml"]
    missing = []
    for dep in deps:
        try:
            __import__(dep if dep != "yaml" else "yaml")
            print(f"  ✔ Dependency '{dep}' installed")
        except ImportError:
            missing.append(dep)
            print(f"  ❌ Dependency '{dep}' missing")

    # 3. Directories
    dirs = ["industries", "scenarios", "runs", "reports"]
    for d in dirs:
        p = Path(d)
        if p.exists():
            print(f"  ✔ Directory '{d}/' exists")
        else:
            print(f"  ⚠ Directory '{d}/' not found (will be auto-created if needed)")

    # 4. Agent Connectivity
    agent_url = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")
    is_reachable = await check_agent_reachable(agent_url)
    if is_reachable:
        print(f"  ✔ Agent endpoint reachable ({agent_url})")
    else:
        print(f"  ❌ Agent endpoint unreachable ({agent_url})")
        print("     Tip: Start the sample agent with 'python sample_agent/agent_app.py'")

    # 5. AES Schema
    schema_path = Path(__file__).parent.parent / "spec" / "aes" / "aes.schema.json"
    if schema_path.exists():
        print(f"  ✔ AES schema found")
    else:
        print(f"  ❌ AES schema missing at {schema_path}")

    print("\n" + "=" * 40 + "\n")
