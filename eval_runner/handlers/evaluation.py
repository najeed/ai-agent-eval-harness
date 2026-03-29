"""
handlers/evaluation.py

Core execution logic for evaluation commands.
"""

import os
import json
import asyncio
from pathlib import Path
from .. import engine, loader, trace_utils

def prepare_agent_env(args) -> dict:
    """Sets environment variables for agents and returns agent metadata."""
    protocol = getattr(args, "protocol", "http")
    agent = getattr(args, "agent", None)
    agent_name = getattr(args, "agent_name", None)

    if protocol == "local":
        cmd = getattr(args, "agent_cmd", None)
        if cmd:
            os.environ["AGENT_LOCAL_CMD"] = cmd
    elif protocol == "socket":
        addr = getattr(args, "agent_socket", None)
        if addr:
            os.environ["AGENT_SOCKET_ADDR"] = addr

    return {
        "protocol": protocol,
        "agent": agent,
        "agent_name": agent_name,
    }

async def handle_evaluate(args):
    """Execution logic for the 'evaluate' command."""
    if args.run_log_dir:
        os.environ["RUN_LOG_DIR"] = args.run_log_dir
    if args.per_run_logs is not None:
        os.environ["RUN_LOG_PER_RUN"] = "true" if args.per_run_logs else "false"
    if args.master_log is not None:
        os.environ["RUN_LOG_MASTER"] = "true" if args.master_log else "false"

    if args.seed is not None:
        import random
        random.seed(args.seed)
        print(f"[CLI] Set random seed to: {args.seed}")

    agent_metadata = prepare_agent_env(args)

    try:
        path_input = args.path
        if "://" in path_input:
            scenarios = loader.load_dataset(path_input, format_type=args.format if args.format != "jsonl" else None)
        else:
            path_obj = Path(path_input)
            scenarios = loader.load_dataset(path_obj, format_type=args.format if args.format != "jsonl" else None)
    except Exception as e:
        print(f"[CLI] Error loading dataset: {e}")
        return

    if args.limit:
        scenarios = scenarios[: args.limit]

    print(f"[CLI] Running {len(scenarios)} scenarios...")

    for i, scenario in enumerate(scenarios):
        attempts = getattr(args, "attempts", 1)
        for attempt in range(attempts):
            print(f"\n[{i+1}/{len(scenarios)}] Attempt {attempt+1}/{attempts} - Scenario: {scenario.get('title', 'Untitled')}")
            await engine.run_evaluation(
                scenario,
                metadata={"args": vars(args), **agent_metadata},
            )

async def handle_run(args):
    """Loads a single scenario and executes the evaluation."""
    if getattr(args, "run_log_dir", None):
        os.environ["RUN_LOG_DIR"] = args.run_log_dir
    if getattr(args, "per_run_logs", None) is not None:
        os.environ["RUN_LOG_PER_RUN"] = "true" if args.per_run_logs else "false"
    if getattr(args, "master_log", None) is not None:
        os.environ["RUN_LOG_MASTER"] = "true" if args.master_log else "false"

    if getattr(args, "seed", None) is not None:
        import random
        random.seed(args.seed)
        print(f"[CLI] Set random seed to: {args.seed}")

    agent_metadata = prepare_agent_env(args)

    try:
        scenario_path = getattr(args, "scenario", None)
        loaded = loader.load_scenario(scenario_path)
        scenarios = loaded if isinstance(loaded, list) else [loaded]

        for scenario in scenarios:
            await engine.run_evaluation(
                scenario, 
                attempts=args.attempts, 
                metadata={"args": vars(args), **agent_metadata}
            )
            scenario_name = scenario.get("title", scenario.get("scenario_id", "Unknown Scenario"))
            print(f"\n   [CLI] Evaluation complete for {scenario_name}")

    except Exception as e:
        print(f"Error during evaluation: {e}")

async def handle_record(args):
    """Handler for 'record' command."""
    from .. import trace_recorder
    prepare_agent_env(args)
    await trace_recorder.record_interaction(args.agent)

async def handle_playground(args):
    """Handler for 'playground' command."""
    from .. import playground
    prepare_agent_env(args)
    await playground.run_playground(args.agent)

def handle_replay(args):
    """Handler for 'replay' command."""
    print(f"\n[Replay] Reconstructing from: {args.path}")
    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] Replay file not found at {path}")
        return

    events = trace_utils.load_events(path)
    for event in events:
        ev_type = event.get("event", "unknown")
        if ev_type == "run_start":
            print(f"--- Run Started: {event.get('run_id')} ({event.get('scenario')}) ---")
        elif ev_type == "prompt":
            print(f"[{event.get('role', 'user').upper()}]: {event.get('content', '')}")
        elif ev_type == "agent_response":
            print(f"Agent: {event.get('content', '')}")
        elif ev_type == "run_end":
            print(f"--- Run Finished: {event.get('status')} ---")

def handle_verify(args):
    """Handler for 'verify' command."""
    from .. import verifier
    trace_path = Path(args.path)
    manifest_path = Path(args.manifest) if args.manifest else trace_path.parent / f"{trace_path.stem}_manifest.json"
    
    if verifier.TraceVerifier.verify_trace(str(trace_path), str(manifest_path)):
        print(f"[OK] VERIFIED: Trace integrity matches manifest.")
    else:
        print(f"[CRITICAL] FAILED: Trace integrity compromised!")

async def handle_quickstart(args):
    """Handler for 'quickstart' command."""
    from .. import quickstart
    await quickstart.run_quickstart()
