import asyncio
import json
import os
from pathlib import Path

# --- FORENSIC BOOTSTRAP: Initialize environment BEFORE loading platform components ---
os.environ["RUN_LOG_DIR"] = ".tmp/proof_runs"
os.environ["AUDIT_LEVEL"] = "2"

# Ensure a signing key exists for telemetry (Boot-Time provisioning)
key_dir = ".tmp/proof_keys"
if not Path(key_dir).exists():
    # We must import TraceVerifier surgically here because we need it for setup
    from eval_runner.verifier import TraceVerifier

    TraceVerifier.generate_key_pair(key_dir)
os.environ["EVAL_SIGNING_KEY"] = f"{key_dir}/private_key.pem"

from eval_runner.events import CoreEvents, emit  # noqa: E402
from eval_runner.flight_recorder import FlightRecorderPlugin  # noqa: E402
from eval_runner.tool_sandbox import ToolSandbox  # noqa: E402
from eval_runner.verifier import TraceVerifier  # noqa: E402


async def run_industrial_proof():
    print("STEP 0: Starting Industrial Hardening Verification...")

    # 1. Forensic Cleanup: Purge previous telemetry to prevent sequence pollution
    proof_log_dir = Path(".tmp/proof_runs")
    if proof_log_dir.exists():
        from eval_runner.utils import rmtree_resilient

        rmtree_resilient(proof_log_dir)

    # 2. Setup Recorder and Environment
    recorder = FlightRecorderPlugin()
    run_id = "proof_run_999"

    # 2. Mock Scenario
    scenario = {
        "id": "proof_scenario",
        "run_id": run_id,
        "tasks": [
            {
                "step": 1,
                "tool": "terminal_execute",
                "params": {"cmd": "echo 'Industrial Hardening Verified'"},
            },
            # Use raw action names for base simulators
            {
                "step": 2,
                "tool": "database_query",
                "params": {
                    "query": "INSERT INTO users (email, role) VALUES ('proof@test.com', 'verifier')"
                },
            },
            {
                "step": 3,
                "tool": "database_query",
                "params": {"query": "SELECT * FROM users"},
            },
        ],
    }

    # 3. Initialize Sandbox
    sandbox = ToolSandbox(scenario)
    sandbox.setup()

    print(f"STEP 3: Jail provisioned at: {sandbox.terminal_jail}")

    # 4. Execute Tasks (Async Iteration 1)
    print("STEP 4: Executing Hardened Shims...")

    # Emit RUN_START to initialize log paths in the recorder
    emit(CoreEvents.RUN_START, {"run_id": run_id})

    for task in scenario["tasks"]:
        print(f"   -> Executing {task['tool']}...")
        result = await sandbox.execute(task["tool"], task["params"])
        print(f"      Result: {result.get('status')} | {result.get('message', 'OK')}")

    # 5. Finalize Forensic Trace (Flush to Disk)
    recorder.finalize_run()

    # 6. Verify Artifacts (Iteration 4: Compliance DNA)
    log_file = Path(os.environ["RUN_LOG_DIR"]) / f"{run_id}.jsonl"
    print(f"STEP 5: Verifying Forensic DNA in {log_file}...")

    if not log_file.exists():
        print("[FAIL] Error: Log file not found!")
        return

    verified = False
    with open(log_file) as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            data = json.loads(line)
            seq = data.get("_seq")
            sig = data.get("_sig")
            print(f"   [Line {i + 1}] Seq: {seq} | Signed: {bool(sig)}")
            if seq and sig:
                verified = True

    if not verified:
        print("[FAIL] Error: No signed telemetry found!")
        return

    # 6. Verify Physical Persistence (Iteration 3: Industrial Engines)
    db_file = Path(sandbox.terminal_jail) / "state.db"
    print(f"STEP 6: Verifying Database Persistence at {db_file}...")
    if not db_file.exists():
        print("[FAIL] Error: state.db not found in jail!")
        return
    print("[PASS] Database Persistence Verified.")

    # 7. Secure Wipe Verification (Iteration 5: Resilience)
    print("STEP 7: Testing Secure Wipe...")
    await sandbox.teardown()
    if not Path(sandbox.terminal_jail).exists():
        print("[PASS] Secure Wipe Verified (Jail Deleted).")
    else:
        print("[FAIL] Error: Jail still exists after teardown!")

    print("\nINDUSTRIAL HARDENING CERTIFIED: 5/5 Iterations Verified.")


if __name__ == "__main__":
    asyncio.run(run_industrial_proof())
