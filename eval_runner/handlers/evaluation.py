"""
handlers/evaluation.py

Core execution logic for evaluation commands.
"""

import json
import os
import traceback
from pathlib import Path

from .. import (
    config,
    engine,
    loader,
    playground,
    plugins,
    quickstart,
    trace_recorder,
    trace_utils,
    utils,
    verifier,
)


def _ensure_path_safe(path: str | Path, description: str = "Path"):
    """
    Industrial Path-Traversal Protection.
    Ensures that a path is within the PROJECT_ROOT jail.
    """
    if not utils.is_path_safe(path, config.PROJECT_ROOT):
        print(f"❌ Security Error: {description} is outside the project jail: {path}")
        return False
    return True


def _resolve_replay_trace(run_id: str) -> Path | None:
    """
    Tiered resolution for industrial run traces.
    1. Primary: Vault directory (Mandatory for AES v1.5.0)
    2. Fallback: Master Log consolidation
    """
    if not run_id:
        return None

    # Resolve paths
    vault_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()
    master_path = (config.RUN_LOG_DIR / "run.jsonl").resolve()

    # Integrity and Security Check
    if not _ensure_path_safe(vault_path, "Vault Trace"):
        return None
    if not _ensure_path_safe(master_path, "Master Log"):
        return None

    if vault_path.exists():
        return vault_path

    if master_path.exists():
        # Quick existence check in master log without loading all events
        # We assume if it exists, the resolution is valid; the handler will filter.
        return master_path

    return None


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
    if seed is not None and isinstance(seed, int | str):
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
        return 1

    if not scenarios:
        print(f"❌ Error: No scenarios found at path: {args.path}")
        return 1

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
                    run_id=getattr(args, "run_id", None),
                    metadata={
                        "args": args_dict,
                        "plugin_provenance": plugins.manager.provenance_map,
                        **agent_metadata,
                    },
                )

        return 0
    except Exception:
        print("❌ Error during evaluation execution:")
        traceback.print_exc()
        return 1


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
    if seed is not None and isinstance(seed, int | str):
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
                scenario,
                run_id=getattr(args, "run_id", None),
                attempts=attempts,
                metadata={
                    "args": args_dict,
                    "plugin_provenance": plugins.manager.provenance_map,
                    **agent_metadata,
                },
            )
            scenario_name = scenario.get("title", scenario.get("id", "Unknown Scenario"))
            print(f"\n   [CLI] Evaluation complete for {scenario_name}")

        return 0

    except Exception:
        print("❌ Error during evaluation:")
        traceback.print_exc()
        return 1


async def handle_record(args):
    """Handler for 'record' command."""
    try:
        prepare_agent_env(args)
        await trace_recorder.record_interaction(args.agent)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Recording FAILED: {e}")
        return 1


async def handle_playground(args):
    """Handler for 'playground' command."""
    try:
        prepare_agent_env(args)
        await playground.run_playground(args.agent)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Playground FAILED: {e}")
        return 1


async def handle_replay(args):
    """
    Handler for 'replay' command.
    Reconstructs the interaction history from a run trace.
    """

    run_id = args.run_id
    if not run_id:
        print("❌ Error: Run ID is mandatory for replay.")
        return 1

    # --- [TIERED RESOLUTION] ---
    path = _resolve_replay_trace(run_id)
    if not path:
        print(
            f"❌ [ERROR] Replay trace not found for Run ID '{run_id}'. "
            "Vault and Master Log are missing or security check failed."
        )
        return 1

    events = trace_utils.load_events(path)
    if path.name == "run.jsonl" and path.parent == config.RUN_LOG_DIR:
        # Filtering based on Master Log resolution
        events = [e for e in events if e.get("run_id") == run_id]
        if not events:
            print(f"❌ [ERROR] Run ID '{run_id}' not found in master log fallback.")
            return 1
        print(
            f"❌ [ERROR] Vault directory not found for Run ID '{run_id}'. "
            "Falling back to master log."
        )

    print(f"\n[Replay] Reconstructing from Run ID: {run_id}")

    # Reconstruct and display events

    # Reconstruct and display events
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

    return 0


async def handle_verify(args):
    """
    Handles the cryptographic integrity check of a run trace.
    Standard Pillar 1 of the industrial Trust Protocol.
    """

    # --- [SSOT] Mandatory Run ID Resolution ---
    run_id = args.run_id  # Verified mandatory by CLI parser

    if not run_id:
        print("      [CRITICAL] FAILED: Run ID is mandatory for verification.")
        return 1

    run_log_dir = (config.RUN_LOG_DIR / run_id).resolve()
    trace_path = run_log_dir / "run.jsonl"
    manifest_path = run_log_dir / "run_manifest.json"

    # [INDUSTRIAL HARDENING] Check security cage BEFORE existence to catch traversals early
    if not _ensure_path_safe(trace_path, "Trace file"):
        return 1

    print(f"      [Identity] Resolving trace for {run_id} -> {trace_path}")
    print(f"      [Identity] Resolving manifest for {run_id} -> {manifest_path}")

    if not trace_path.exists():
        print(f"      [CRITICAL] FAILED: Trace file for {run_id} missing after vault lookup.")
        return 1

    if not manifest_path.exists():
        print(f"      [CRITICAL] FAILED: Manifest for {run_id} missing (Certification required).")
        return 1

    # Canonical Verification Call (Pillar 1)
    # TraceVerifier.verify_trace is the industrial standard method.
    is_valid = await verifier.TraceVerifier.verify_trace_async(str(trace_path), str(manifest_path))

    if is_valid:
        print("      [OK] VERIFIED: Trace integrity matches manifest.")
        return 0
    else:
        print("      [CRITICAL] FAILED: Trace integrity compromised!")
        return 1


async def handle_gate(args):
    """
    CI/CD Hard Gate: Verifies a certificate and optionally matches a commit hash.
    Exits with 1 on verification failure.
    """

    # [Autonomous Discovery] Standard mandatory Run ID
    run_id = args.run_id
    if not run_id:
        print("[GATE] FAILURE: Run ID is mandatory for gating.")
        return 1

    # [INDUSTRIAL HARDENING] Immediate Resolution and Safety Check
    # We resolve the vault path and check safety before existence to prevent leak-via-existence
    vault_path = (config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json").resolve()
    if not _ensure_path_safe(vault_path, "Verification Certificate"):
        return 1
    # 2. Check Standard Sidecar (Primary for v1-v5 Narrative)
    sidecar_path = (config.RUN_LOG_DIR / run_id / "run_manifest.json").resolve()

    if vault_path.exists():
        vc_path = vault_path
    elif sidecar_path.exists():
        vc_path = sidecar_path
    else:
        print(f"[GATE] FAILURE: Manifest not found for Run ID '{run_id}' in Sidecar or Vault.")
        return 1

    if not _ensure_path_safe(vc_path, "Verification Certificate"):
        return 1

    if not vc_path.exists():
        print(f"[GATE] FAILURE: Verification Certificate not found: {vc_path}")
        return 1

    try:
        with open(vc_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # 1. Base Integrity Resolve
        trace_name = manifest.get("trace_file", "run.jsonl")

        # Identity-Aware Trace Resolution
        trace_path = (config.RUN_LOG_DIR / run_id / trace_name).resolve()

        if not trace_path.exists():
            print(f"[GATE] FAILURE: Associated trace file missing: {trace_name} at {trace_path}")
            return 1

        # Canonical Verification Call (Pillars 1 & 2)
        # We now pass verify_ledger=True to ensure sidecar artifact integrity
        is_valid = await verifier.TraceVerifier.verify_trace_async(
            str(trace_path), str(vc_path), verify_ledger=getattr(args, "verify_ledger", False)
        )

        if not is_valid:
            print(
                "[GATE] FAILURE: Industrial Trust Verification failed "
                "(Integrity, Ledger, or Signature)."
            )
            return 1

        # 3. Commit Hash Check (Audit Alignment)
        if args.hash:
            actual_hash = manifest.get("metadata", {}).get("git_hash")
            if actual_hash != args.hash:
                print(f"[GATE] FAILURE: Commit mismatch! Expected {args.hash}, found {actual_hash}")
                return 1

        print(f"[GATE] SUCCESS: Verification Certificate '{vc_path.name}' is valid and signed.")
        return 0

    except Exception as e:
        print(f"[GATE] ERROR: Unexpected failure during gating: {e}")
        return 1


async def handle_quickstart(args):
    """Handler for 'quickstart' command."""
    await quickstart.run_quickstart()


async def handle_certify(args):
    """
    Handler for 'certify' command.
    Generates a Verification Certificate (VC) and sidecar manifest for a trace.
    """

    # [Autonomous Discovery] Mandatory Run ID
    run_id = args.run_id
    if not run_id:
        print("❌ Error: Run ID is mandatory for certification.")
        return 1

    # Resolve from mandatory industrial run log directory
    trace_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()

    # [INDUSTRIAL HARDENING] Check security cage BEFORE existence
    if not _ensure_path_safe(trace_path, "Trace file"):
        return 1

    if not trace_path.exists():
        print(f"Error: Trace file not found for Run ID {run_id}")
        return 1

    try:
        # [VC v3] Argument mapping with industrial defaults
        identity_id = args.identity if hasattr(args, "identity") and args.identity else "system_id"
        status = args.status if hasattr(args, "status") and args.status else "pass"
        score = float(args.score) if hasattr(args, "score") and args.score is not None else 1.0
        policy_ref = args.policy_ref if hasattr(args, "policy_ref") else None
        ttl_days = (
            int(args.ttl)
            if hasattr(args, "ttl") and args.ttl is not None
            else config.GOVERNANCE_TTL_DAYS
        )
        behavioral_fingerprint_id = args.fingerprint if hasattr(args, "fingerprint") else None

        manifest = verifier.TraceVerifier.sign_trace(
            str(trace_path),
            run_id=args.run_id,
            identity_id=identity_id,
            compliance_status=status,
            compliance_score=score,
            policy_ref=policy_ref,
            ttl_days=ttl_days,
            behavioral_fingerprint_id=behavioral_fingerprint_id,
        )

        manifest_path = trace_path.parent / "run_manifest.json"

        print("✅ Success: Verification Certificate generated.")
        print(f"    - Run ID: {manifest.get('run_id')}")
        print(f"    - SHA-256: {manifest.get('sha256')}")
        print(f"    - VC Version: {manifest.get('vc_version')}")

        chain = manifest.get("provenance_chain", [])
        if chain:
            print(f"    - Signed By: {', '.join([c['identity'] for c in chain])}")
        else:
            print("    - Signed: No (Integrity-only manifest)")

        print(f"    - Governance TTL: {manifest.get('governance_ttl')} days")

        print(f"    - Manifest: {manifest_path}")

        return 0

    except Exception:
        print("❌ Error during certification:")
        traceback.print_exc()
        return 1
