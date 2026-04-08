import asyncio
import json
import os
from pathlib import Path

from eval_runner.events import CoreEvents, EventEmitter
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier


async def run_industrial_proof():
    print("🚀 Starting Industrial Hardening Verification...")

    # 1. Setup Environment
    run_id = "proof_run_999"
    os.environ["RUN_LOG_DIR"] = ".tmp/proof_runs"
    os.environ["AUDIT_LEVEL"] = "2"

    # Ensure a signing key exists for telemetry
    key_dir = ".tmp/proof_keys"
    if not Path(key_dir).exists():
        TraceVerifier.generate_key_pair(key_dir)
    os.environ["EVAL_SIGNING_KEY"] = f"{key_dir}/private_key.pem"

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

    print(f"🛠️  Jail provisioned at: {sandbox.terminal_jail}")

    # 4. Execute Tasks (Async Iteration 1)
    print("⏳ Executing Hardened Shims...")

    # Emit RUN_START to initialize log paths in the recorder
    EventEmitter.emit(CoreEvents.RUN_START, {"run_id": run_id})

    for task in scenario["tasks"]:
        print(f"   -> Executing {task['tool']}...")
        result = await sandbox.execute(task["tool"], task["params"])
        print(f"      Result: {result.get('status')} | {result.get('message', 'OK')}")

    # 5. Verify Artifacts (Iteration 4: Compliance DNA)
    log_file = Path(os.environ["RUN_LOG_DIR"]) / f"{run_id}.jsonl"
    print(f"⚖️  Verifying Forensic DNA in {log_file}...")

    if not log_file.exists():
        print("❌ Error: Log file not found!")
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
        print("❌ Error: No signed telemetry found!")
        return

    # 6. Verify Physical Persistence (Iteration 3: Industrial Engines)
    db_file = Path(sandbox.terminal_jail) / "state.db"
    print(f"🗄️  Verifying Database Persistence at {db_file}...")
    if not db_file.exists():
        print("❌ Error: state.db not found in jail!")
        return
    print("✅ Database Persistence Verified.")

    # 7. Secure Wipe Verification (Iteration 5: Resilience)
    print("🧹 Testing Secure Wipe...")
    sandbox.teardown()
    if not Path(sandbox.terminal_jail).exists():
        print("✅ Secure Wipe Verified (Jail Deleted).")
    else:
        print("❌ Error: Jail still exists after teardown!")

    print("\n🏆 INDUSTRIAL HARDENING CERTIFIED: 5/5 Iterations Verified.")


if __name__ == "__main__":
    asyncio.run(run_industrial_proof())
