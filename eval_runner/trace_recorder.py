import json
import os
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path

async def record_interaction(agent_url: str):
    """Simple loop to record interactions with an agent."""
    print("\n⏺ AI Agent Eval Harness - Trace Recorder")
    print(f"Target Agent: {agent_url}\n")
    print("Type 'exit' or 'quit' to stop recording.\n")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("runs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run-{run_id}.jsonl"
    
    events = []
    
    # 1. Emit run_start
    start_event = {
        "event": "run_start",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "scenario": "recorded_session"
    }
    events.append(start_event)

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                task = input("Task > ").strip()
                if not task or task.lower() in ["exit", "quit"]:
                    break
                
                # Record request
                req_event = {
                    "event": "agent_request",
                    "timestamp": datetime.now().isoformat(),
                    "task": task
                }
                events.append(req_event)

                print("  Thinking...")
                
                try:
                    async with session.post(agent_url, json={"task_description": task}, timeout=10) as response:
                        if response.status == 200:
                            data = await response.get_json()
                            print(f"  Agent: {data.get('summary', 'No summary provided')}")
                            
                            # Record response
                            res_event = {
                                "event": "agent_response",
                                "timestamp": datetime.now().isoformat(),
                                "content": data
                            }
                            events.append(res_event)
                        else:
                            print(f"  ❌ Error: Agent returned status {response.status}")
                except Exception as e:
                    print(f"  ❌ Error: Failed to contact agent: {e}")

    finally:
        # Save to file
        with open(log_file, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        
        print(f"\n✅ Recording saved to: {log_file}")
        print(f"Tip: You can replay this with 'eval-harness replay {log_file}'")

if __name__ == "__main__":
    # For testing, we can use a default URL or pass one via CLI
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5001/execute_task"
    asyncio.run(record_interaction(url))
