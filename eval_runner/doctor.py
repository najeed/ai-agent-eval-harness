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


def check_security_health():
    """Performs an audit of the security posture (PBAC)."""
    print("  --- Security Audit (PBAC/Industrial) ---")
    
    # 1. API Key Check
    api_key = os.getenv("DASHBOARD_API_KEY")
    if not api_key:
        print("  ❌ DASHBOARD_API_KEY is not set. Console will be inaccessible.")
    elif len(api_key) < 16:
        print(f"  ⚠ DASHBOARD_API_KEY is weak ({len(api_key)} chars). Recommend 32+ for production.")
    else:
        print(f"  ✔ DASHBOARD_API_KEY is configured (Length: {len(api_key)})")

    # 2. Auth Provider Integrity
    try:
        from .console.auth_manager import get_auth_provider, Role
        provider = get_auth_provider()
        print(f"  ✔ Auth Provider active: {provider.__class__.__name__}")
        
        # Test PBAC Node manifest
        if Role.SCENARIOS_READ == "scenarios:read":
            print("  ✔ PBAC Permission Nodes are healthy")
        else:
            print("  ❌ PBAC Permission Nodes are misconfigured")
    except Exception as e:
        print(f"  ❌ Auth Provider Error: {str(e)}")

    # 3. Session Security (Secret Key)
    # We check if a secret key can be derived (used in app.py)
    if api_key:
        try:
            import hashlib
            derived = hashlib.sha256(api_key.encode()).hexdigest()
            if derived:
                 print("  ✔ Session SECRET_KEY derivation is functional")
        except Exception:
             print("  ❌ Session Crypto Error")
    else:
        print("  ⚠ Session Security cannot be verified without an API Key")


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

    # 3. Security Audit (New v1.2.4 Section)
    check_security_health()

    # 4. Directories
    dirs = ["industries", "scenarios", "runs", "reports"]
    for d in dirs:
        p = Path(d)
        if p.exists():
            print(f"  ✔ Directory '{d}/' exists")
        else:
            print(f"  ⚠ Directory '{d}/' not found (will be auto-created if needed)")

    # 5. Agent Connectivity
    agent_url = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")
    is_reachable = await check_agent_reachable(agent_url)
    if is_reachable:
        print(f"  ✔ Agent endpoint reachable ({agent_url})")
    else:
        print(f"  ❌ Agent endpoint unreachable ({agent_url})")
        print("     Tip: Start the sample agent with 'python sample_agent/agent_app.py'")

    # 6. AES Schema
    schema_path = Path(__file__).parent.parent / "spec" / "aes" / "aes.schema.json"
    if schema_path.exists():
        print(f"  ✔ AES schema found")
    else:
        print(f"  ❌ AES schema missing at {schema_path}")

    print("\n" + "=" * 40 + "\n")
