"""
handlers/evaluation.py

Core execution logic for evaluation commands.
"""

import json
import os
import sys
import traceback
from pathlib import Path

from .. import engine, loader, trace_utils, utils, config


def _ensure_path_safe(path: str | Path, description: str = "Path"):
    """
    Industrial Path-Traversal Protection.
    Ensures that a path is within the PROJECT_ROOT jail.
    """
    if not utils.is_path_safe(path, config.PROJECT_ROOT):
        print(f"❌ Security Error: {description} is outside the project jail: {path}")
        return False
    return True


def prepare_agent_env(args) -> dict:
    """Sets environment variables for agents and returns agent metadata."""
    protocol = getattr(args, "protocol", "http")
    agent = getattr(args, "agent", None)
    agent_name = getattr(args, "agent_name", None)

    if protocol == "local":
        cmd = getattr(args, "agent_cmd", None)
        if cmd and isinstance(cmd, str):
            os.environ["AGENT_LOCAL_CMD"] = cmd
    elif protocol == "socket":
        addr = getattr(args, "agent_socket", None)
        if addr and isinstance(addr, str):
            os.environ["AGENT_SOCKET_ADDR"] = addr

    return {
        "protocol": protocol,
        "agent": agent,
        "agent_name": agent_name,
    }


def load_plugins_from_args(args):
    """Authoritative plugin injection (v1.3.0 Standard)."""
    from .. import plugins

    plugin_list = getattr(args, "plugin", []) or []
    # Environment priority fallback
    env_plugins = os.getenv("AES_PLUGINS", "").split(",")
    for p in plugin_list + [ep for ep in env_plugins if ep.strip()]:
        if p.strip():
            try:
                plugins.manager.load(p.strip())
            except Exception as e:
                print(f"   [CLI] Warning: Failed to load plugin {p}: {e}")


async def handle_evaluate(args):
    """Execution logic for the 'evaluate' command."""
    # [Audit BUG-04] Robust environment overrides
    run_log_dir = getattr(args, "run_log_dir", None)
    if run_log_dir and isinstance(run_log_dir, str):
        os.environ["RUN_LOG_DIR"] = run_log_dir
    
    per_run_logs = getattr(args, "per_run_logs", None)
    if per_run_logs is not None:
        os.environ["RUN_LOG_PER_RUN"] = "true" if per_run_logs else "false"
        
    master_log = getattr(args, "master_log", None)
    if master_log is not None:
        os.environ["RUN_LOG_MASTER"] = "true" if master_log else "false"

    seed = getattr(args, "seed", None)
    if seed is not None and isinstance(seed, (int, str)):
        import random

        random.seed(seed)
        print(f"[CLI] Set random seed to: {seed}")

    # Load plugins early (v1.3.0 Industrial Standards)
    load_plugins_from_args(args)

    agent_metadata = prepare_agent_env(args)

    try:
        path_input = args.path
        if "://" in path_input:
            scenarios = loader.load_dataset(
                path_input, format_type=args.format if args.format != "jsonl" else None
            )
        else:
            path_obj = Path(path_input)
            scenarios = loader.load_dataset(
                path_obj, format_type=args.format if args.format != "jsonl" else None
            )
    except Exception:
        print("❌ Error loading dataset:")
        traceback.print_exc()
        sys.exit(1)
        return

    if args.limit:
        scenarios = scenarios[: args.limit]

    print(f"[CLI] Running {len(scenarios)} scenarios...")

    try:
        for i, scenario in enumerate(scenarios):
            attempts = getattr(args, "attempts", 1)
            if not isinstance(attempts, int):
                attempts = 1
            for attempt in range(attempts):
                print(
                    f"\n[{i + 1}/{len(scenarios)}] Attempt {attempt + 1}/{attempts} - Scenario: {scenario.get('title', 'Untitled')}"  # noqa: E501
                )
                # [Iteration 4: Forensic Metadata]
                try:
                    args_dict = vars(args)
                except TypeError:
                    args_dict = {}
                await engine.run_evaluation(
                    scenario,
                    metadata={"args": args_dict, **agent_metadata},
                )
        
        sys.exit(0)
    except Exception:
        print("❌ Error during evaluation execution:")
        traceback.print_exc()
        sys.exit(1)
        return


async def handle_run(args):
    """Loads a single scenario and executes the evaluation."""
    # [Audit BUG-04] Robust environment overrides
    run_log_dir = getattr(args, "run_log_dir", None)
    if run_log_dir and isinstance(run_log_dir, str):
        os.environ["RUN_LOG_DIR"] = run_log_dir
        
    per_run_logs = getattr(args, "per_run_logs", None)
    if per_run_logs is not None:
        os.environ["RUN_LOG_PER_RUN"] = "true" if per_run_logs else "false"
        
    master_log = getattr(args, "master_log", None)
    if master_log is not None:
        os.environ["RUN_LOG_MASTER"] = "true" if master_log else "false"

    seed = getattr(args, "seed", None)
    if seed is not None and isinstance(seed, (int, str)):
        import random

        random.seed(seed)
        print(f"[CLI] Set random seed to: {seed}")

    # Load plugins early (v1.3.0 Industrial Standards)
    load_plugins_from_args(args)

    agent_metadata = prepare_agent_env(args)

    try:
        scenario_path = getattr(args, "scenario", None)
        loaded = loader.load_scenario(scenario_path)
        scenarios = loaded if isinstance(loaded, list) else [loaded]

        for scenario in scenarios:
            # [Iteration 4: Forensic Metadata]
            try:
                args_dict = vars(args)
            except TypeError:
                args_dict = {}
            attempts = getattr(args, "attempts", 1)
            if not isinstance(attempts, int):
                attempts = 1
            await engine.run_evaluation(
                scenario, attempts=attempts, metadata={"args": args_dict, **agent_metadata}
            )
            scenario_name = scenario.get("title", scenario.get("scenario_id", "Unknown Scenario"))
            print(f"\n   [CLI] Evaluation complete for {scenario_name}")
        
        sys.exit(0)

    except Exception:
        print("❌ Error during evaluation:")
        traceback.print_exc()
        sys.exit(1)
        return


async def handle_record(args):
    """Handler for 'record' command."""
    from .. import trace_recorder

    prepare_agent_env(args)
    await trace_recorder.record_interaction(args.agent)
    sys.exit(0)


async def handle_playground(args):
    """Handler for 'playground' command."""
    from .. import playground

    prepare_agent_env(args)
    await playground.run_playground(args.agent)
    sys.exit(0)


async def handle_replay(args):
    """Handler for 'replay' command."""
    print(f"\n[Replay] Reconstructing from: {args.path}")
    path = Path(args.path)
    if not _ensure_path_safe(path, "Replay file"):
        sys.exit(1)
        return

    if not path.exists():
        print(f"[ERROR] Replay file not found at {path}")
        sys.exit(1)
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
    
    sys.exit(0)


async def handle_verify(args):
    """
    Handles the cryptographic integrity check of a run trace.
    Standard Pillar 1 of the industrial Trust Protocol.
    """
    from eval_runner.verifier import TraceVerifier
    from pathlib import Path

    # --- [SSOT] Artifact Resolution ---
    trace_path = args.path
    manifest_path = None

    if args.run_id:
        # Autonomous resolve from authoritative vault
        run_log_dir = config.RUN_LOG_DIR / args.run_id
        trace_path = str(run_log_dir / "run.jsonl")
        manifest_path = str(run_log_dir / f"{args.run_id}_manifest.json")
        print(f"      [Identity] Resolved trace for {args.run_id} -> {trace_path}")
        print(f"      [Identity] Resolved manifest for {args.run_id} -> {manifest_path}")

    if not trace_path:
        print("Error: Must provide either --run-id or --path for verification.")
        sys.exit(1)

    tp = Path(trace_path)
    if not _ensure_path_safe(tp, "Trace file"):
        sys.exit(1)
        return

    if not tp.exists():
        print(f"      [CRITICAL] FAILED: Trace integrity compromised! (File not found: {trace_path})")
        sys.exit(1)
        return

    # If verifying via --path without --run-id, assume manifest is the default sidecar
    if not manifest_path:
        p = Path(trace_path)
        manifest_path = str(p.parent / f"{p.stem}_manifest.json")

    # Canonical Verification Call (Pillar 1)
    # TraceVerifier.verify_trace is the industrial standard method.
    is_valid = await TraceVerifier.verify_trace_async(str(trace_path), str(manifest_path))

    if is_valid:
        print("      [OK] VERIFIED: Trace integrity matches manifest.")
        sys.exit(0)
    else:
        print("      [CRITICAL] FAILED: Trace integrity compromised!")
        sys.exit(1)


async def handle_gate(args):
    """
    CI/CD Hard Gate: Verifies a certificate and optionally matches a commit hash.
    Exits with 1 on verification failure.
    """
    from .. import verifier

    # Industrial Discovery: Resolve manifest via --vc or --run-id
    run_id = getattr(args, "run_id", None)
    vc_path_str = getattr(args, "vc", None)
    
    if not run_id and not vc_path_str:
        print("[GATE] FAILURE: Explicit Run ID (--run-id) or Certificate path (--vc) is required.")
        sys.exit(1)
        return

    # Absolute Identity (SSOT) Resolve Logic
    vc_path = None
    if run_id:
        # Standard Vault lookup (Primary Case)
        vault_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
        # Sidecar lookup (Refactor Fallback)
        sidecar_path = config.RUN_LOG_DIR / run_id / "run_manifest.json"
        
        if vault_path.exists():
            vc_path = vault_path
        elif sidecar_path.exists():
            vc_path = sidecar_path
        else:
            print(f"[GATE] FAILURE: Manifest not found for Run ID '{run_id}' in Vault or Sidecar.")
            sys.exit(1)
            return
    else:
        # Legacy direct path lookup (Deprecated)
        vc_path = Path(vc_path_str)

    if not _ensure_path_safe(vc_path, "Verification Certificate"):
        sys.exit(1)

    if not vc_path.exists():
        print(f"[GATE] FAILURE: Verification Certificate not found: {vc_path}")
        sys.exit(1)

    try:
        with open(vc_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # 1. Base Integrity Resolve
        trace_name = manifest.get("trace_file", "run.jsonl")
        
        # Identity-Aware Trace Resolution
        if run_id:
            # If we have run_id, we look in the deterministic log directory
            trace_path = config.RUN_LOG_DIR / run_id / trace_name
        else:
            # Legacy anchor path
            trace_path = vc_path.parent / trace_name

        if not trace_path.exists():
            print(f"[GATE] FAILURE: Associated trace file missing: {trace_name} at {trace_path}")
            sys.exit(1)
            return

        if not await verifier.TraceVerifier.verify_trace_async(str(trace_path), str(vc_path)):
            print("[GATE] FAILURE: SHA-256 integrity check failed!")
            sys.exit(1)
            return

        # 2. Asymmetric Signature Check (Wait for optional public key)
        if args.public_key:
            pk_path = Path(args.public_key)
            if not pk_path.exists():
                print(f"[GATE] FAILURE: Public key not found: {pk_path}")
                sys.exit(1)

            sig = manifest.get("signature_ed25519") or manifest.get("signature")
            if not sig:
                print("[GATE] FAILURE: Manifest missing asymmetric signature (signature_ed25519)!")
                sys.exit(1)
                return

            # Verify the manifest data itself (excluding the signature field)
            manifest_copy = manifest.copy()
            if "signature_ed25519" in manifest_copy:
                del manifest_copy["signature_ed25519"]
            if "signature" in manifest_copy:
                del manifest_copy["signature"]

            data_to_verify = json.dumps(manifest_copy, sort_keys=True).encode()

            if not verifier.TraceVerifier.verify_asymmetric(data_to_verify, sig, str(pk_path)):
                print("[GATE] FAILURE: ED25519 signature verification failed!")
                sys.exit(1)

        # 3. Commit Hash Check (Audit Alignment)
        if args.hash:
            actual_hash = manifest.get("metadata", {}).get("git_hash")
            if actual_hash != args.hash:
                print(f"[GATE] FAILURE: Commit mismatch! Expected {args.hash}, found {actual_hash}")
                sys.exit(1)

        print(f"[GATE] SUCCESS: Verification Certificate '{vc_path.name}' is valid and signed.")
        sys.exit(0)

    except Exception as e:
        print(f"[GATE] ERROR: Unexpected failure during gating: {e}")
        sys.exit(1)


async def handle_quickstart(args):
    """Handler for 'quickstart' command."""
    from .. import quickstart

    await quickstart.run_quickstart()


async def handle_certify(args):
    """
    Handler for 'certify' command.
    Generates a Verification Certificate (VC) and sidecar manifest for a trace.
    """
    from .. import verifier

    # Industrial Discovery: Resolve trace via --run-id or --path
    run_id = getattr(args, "run_id", None)
    trace_path_str = getattr(args, "path", None)
    
    if not run_id and not trace_path_str:
        print("❌ Error: Explicit Run ID (--run-id) or trace path (--path) is required.")
        sys.exit(1)
        return

    # Absolute Identity (SSOT) Resolve Logic
    if run_id:
        # Resolve from mandatory industrial run log directory
        trace_path = config.RUN_LOG_DIR / run_id / "run.jsonl"
    else:
        trace_path = Path(trace_path_str)

    if not _ensure_path_safe(trace_path, "Trace file"):
        sys.exit(1)
        return

    try:
        if not trace_path.exists():
            print(f"❌ Error: Trace file not found at {trace_path}")
            sys.exit(1)
            return

        print(f"[*] Certifying trace identity: {run_id or trace_path.name}")
        manifest = verifier.TraceVerifier.sign_trace(
            str(trace_path),
            private_key_path=getattr(args, "private_key", None),
            fingerprint_id=getattr(args, "fingerprint", None)
        )

        manifest_path = trace_path.parent / f"run_manifest.json"
        
        print("✅ Success: Verification Certificate generated.")
        print(f"    - Run ID: {manifest.get('run_id')}")
        print(f"    - SHA-256: {manifest.get('sha256')}")
        if manifest.get("signature_ed25519"):
            print("    - Signed: Yes (ED25519 Authority)")
        else:
            print("    - Signed: No (Integrity-only manifest)")

        print(f"    - Manifest: {manifest_path}")
        
        sys.exit(0)

    except Exception:
        print("❌ Error during certification:")
        traceback.print_exc()
        sys.exit(1)
        return
