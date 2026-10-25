import asyncio
from datetime import datetime
from pathlib import Path

import aiohttp


async def record_interaction(agent_url: str, *, run_store=None, context: dict | None = None):
    """Simple loop to record interactions with an agent."""
    print("\n[Trace Recorder] AgentV - Trace Recorder")
    print(f"Target Agent: {agent_url}\n")
    print("Type 'exit' or 'quit' to stop recording.\n")

    runs_root = Path("runs")
    if run_store is None:
        from eval_runner.runtime_services import compose_local_run_store

        run_store = compose_local_run_store(runs_root)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_store.create_run(run_id, scenario_id="recorded_session", context=context)
    events = []

    # 1. Emit run_start
    start_event = {
        "event": "run_start",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "scenario": "recorded_session",
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
                    "task": task,
                }
                events.append(req_event)

                print("  Thinking...")

                try:
                    async with session.post(
                        agent_url, json={"task_description": task}, timeout=10
                    ) as response:
                        if response.status == 200:
                            data = await response.json()

                            # R2.2 Remediation: Simple sensitive data masking
                            def mask_data(val):
                                if isinstance(val, dict):
                                    return {k: mask_data(v) for k, v in val.items()}
                                if isinstance(val, list):
                                    return [mask_data(v) for v in val]
                                if isinstance(val, str) and (
                                    len(val) > 20
                                    and any(x in val.lower() for x in ["key", "secret", "token"])
                                ):
                                    return f"{val[:4]}...[MASKED]"
                                return val

                            data = mask_data(data)
                            print(f"  Agent: {data.get('summary', 'No summary provided')}")

                            # Record response
                            res_event = {
                                "event": "agent_response",
                                "timestamp": datetime.now().isoformat(),
                                "content": data,
                            }
                            events.append(res_event)
                        else:
                            print(f"  ❌ Error: Agent returned status {response.status}")
                except Exception as e:
                    print(f"  ❌ Error: Failed to contact agent: {e}")

    finally:
        # Persist through the authoritative run provider.
        from eval_runner.run_lifecycle import assert_can_write_trace

        assert_can_write_trace(run_id, run_store=run_store, context=context)
        run_store.append_events(run_id, events, context=context)

        # Legacy mirror for older CLI / testing expectations
        legacy_file = runs_root / f"run-{run_id}.jsonl"
        try:
            import json

            from .trace_utils import AESJsonEncoder

            legacy_file.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy_file, "w", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, cls=AESJsonEncoder) + "\n")
        except OSError as exc:
            import logging

            logging.getLogger("eval_runner.trace_recorder").warning(
                "Could not mirror trace to legacy path: %s", exc
            )

        print(f"\nRecording saved for run: {run_id}")


if __name__ == "__main__":
    # For testing, we can use a default URL or pass one via CLI
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5001/execute_task"
    from eval_runner.runtime_services import resolve_run_store

    # This executable is a composition boundary; the recorder itself accepts
    # only explicit ownership and never resolves a provider.
    asyncio.run(record_interaction(url, run_store=resolve_run_store()))
