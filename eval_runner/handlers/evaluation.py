"""
handlers/evaluation.py

Core execution logic for evaluation commands.
"""

import json
import logging
import os
import traceback
from pathlib import Path

from .. import config, utils
from ..run_lifecycle import RunSuspendedForApproval

logger = logging.getLogger(__name__)


def __getattr__(name: str):
    """Lazy-load submodules on demand for fast CLI startup and mock compatibility."""
    if name in {
        "engine",
        "loader",
        "playground",
        "plugins",
        "quickstart",
        "trace_recorder",
        "trace_utils",
        "verifier",
    }:
        import importlib

        mod = importlib.import_module(f"eval_runner.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


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
    from eval_runner.runtime_services import resolve_plugin_registry

    registry = resolve_plugin_registry()
    plugin_list = getattr(args, "plugin", []) or []
    # Environment priority fallback
    env_plugins = os.getenv("AES_PLUGINS", "").split(",")
    for p in plugin_list + [ep for ep in env_plugins if ep.strip()]:
        if p.strip():
            try:
                registry.load(p.strip())
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

    base_seed = seed if isinstance(seed, int) else None

    # Load plugins early (v1.3.0 Industrial Standards)
    load_plugins_from_args(args)

    agent_metadata = prepare_agent_env(args)

    try:
        # Lazy Import: defer execution components until the batch begins.
        # or loading full execution runtimes until the batch evaluation actually begins.
        from eval_runner.runtime_services import resolve_plugin_registry

        from .. import engine, loader

        plugin_registry = resolve_plugin_registry()

        path_input = args.path
        scenarios = loader.load_dataset(
            path_input, format_type=args.format if args.format != "jsonl" else None
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

                clean_args = {k: v for k, v in args_dict.items() if not callable(v)}
                execution_mode = getattr(args, "execution_mode", None)
                if execution_mode:
                    # The mode is declared before execution and becomes part of
                    # the immutable RUN_START provenance record.
                    scenario = dict(scenario)
                    scenario["execution_mode"] = execution_mode
                await engine.run_evaluation(
                    scenario,
                    run_id=getattr(args, "run_id", None),
                    seed=base_seed,
                    metadata={
                        "args": clean_args,
                        "plugin_provenance": plugin_registry.provenance_map,
                        **agent_metadata,
                    },
                )

        return 0
    except Exception:
        print("❌ Error during evaluation execution:")
        traceback.print_exc()
        return 1
    finally:
        try:
            from ..adapters.common import SessionManager as AdapterSessionManager

            await AdapterSessionManager.close_all()
        except Exception as e:
            print(f"   [CLI] Warning: Failed to close adapter sessions: {e}")


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

    base_seed = seed if isinstance(seed, int) else None

    # Load plugins early (v1.3.0 Industrial Standards)
    load_plugins_from_args(args)

    agent_metadata = prepare_agent_env(args)

    try:
        # Lazy Import: defer execution components until command execution.
        from eval_runner.runtime_services import resolve_plugin_registry

        from .. import engine, loader

        plugin_registry = resolve_plugin_registry()

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

            clean_args = {k: v for k, v in args_dict.items() if not callable(v)}
            execution_mode = getattr(args, "execution_mode", None)
            if execution_mode:
                scenario = dict(scenario)
                scenario["execution_mode"] = execution_mode
            await engine.run_evaluation(
                scenario,
                run_id=getattr(args, "run_id", None),
                attempts=attempts,
                seed=base_seed,
                metadata={
                    "args": clean_args,
                    "plugin_provenance": plugin_registry.provenance_map,
                    **agent_metadata,
                },
            )
            scenario_name = scenario.get("title", scenario.get("id", "Unknown Scenario"))
            print(f"\n   [CLI] Evaluation complete for {scenario_name}")

        return 0

    except RunSuspendedForApproval as susp:
        print(f"\n[HITL PAUSE] Run '{susp.run_id}' PAUSED_FOR_APPROVAL.")
        print(f"    Approval Token: {susp.approval_token}")
        print("    To resume execution, run:")
        print(
            f"    agentv hitl-resume --run-id {susp.run_id} "
            f"--approval-token {susp.approval_token} --decision APPROVED\n"
        )
        return 0
    except Exception:
        print("❌ Error during evaluation:")
        traceback.print_exc()
        return 1
    finally:
        try:
            from ..adapters.common import SessionManager as AdapterSessionManager

            await AdapterSessionManager.close_all()
        except Exception as e:
            print(f"   [CLI] Warning: Failed to close adapter sessions: {e}")


async def handle_record(args):
    """Handler for 'record' command."""
    try:
        # Lazy Import: Defer 'trace_recorder' until live recording is executed
        from .. import trace_recorder

        prepare_agent_env(args)
        from eval_runner.runtime_services import resolve_run_store

        await trace_recorder.record_interaction(args.agent, run_store=resolve_run_store())
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Recording FAILED: {e}")
        return 1


async def handle_playground(args):
    """Handler for 'playground' command."""
    try:
        # Lazy Import: Defer 'playground' until interactive REPL is started
        from .. import playground

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

    try:
        # Lazy Import: Defer 'trace_utils' until replay is requested
        from ..runtime_services import resolve_run_store

        run_id = args.run_id

        if not run_id:
            print("❌ Error: Run ID is mandatory for replay.")
            return 1

        # Replay is provider-native. There is no vault/master-log recovery
        # path: an owner that cannot return events cannot be replayed.
        events = resolve_run_store().get_events(run_id, offset=0, limit=10_000_000)
        if not events:
            print(
                f"❌ [ERROR] Replay trace not found for Run ID '{run_id}'. "
                "RunStorageProvider returned no events."
            )
            return 1

        print(f"\n[Replay] Reconstructing from Run ID: {run_id}")

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
    except Exception as e:
        print(f"❌ [ERROR] Replay FAILED: {e}")
        return 1


async def handle_verify(args):
    """
    Handles the cryptographic integrity check of a run trace.
    Standard Pillar 1 of the industrial Trust Protocol.
    """

    try:
        # --- [SSOT] Mandatory Run ID Resolution ---
        run_id = args.run_id  # Verified mandatory by CLI parser

        if not run_id:
            print("      [CRITICAL] FAILED: Run ID is mandatory for verification.")
            return 1

        from eval_runner.runtime_services import resolve_run_store

        from .. import verifier

        store = resolve_run_store()
        run = store.get_run(run_id)
        if run is None and store.get_trace_bytes(run_id) is None:
            print(f"      [CRITICAL] FAILED: Trace file for {run_id} missing after vault lookup.")
            return 1

        result = verifier.TraceVerifier.verify_run(run_id, run_store=store)
        is_valid = bool(result["is_valid"])

        if is_valid:
            print("      [OK] VERIFIED: Trace integrity matches manifest.")
            return 0
        else:
            print("      [CRITICAL] FAILED: Trace integrity compromised!")
            return 1
    except Exception as e:
        print(f"❌ [ERROR] Verification FAILED: {e}")
        return 1


async def handle_verify_package(args):
    """
    Handler for 'verify-package' command.
    Independently verifies an .agentv-package.json verification package.
    """
    pkg_path = Path(args.package_path).resolve()
    if not _ensure_path_safe(pkg_path, "Package file"):
        return 1
    if not pkg_path.exists():
        print(f"❌ Error: Verification package file not found: {pkg_path}")
        return 1

    try:
        with open(pkg_path, encoding="utf-8") as f:
            pkg_data = json.load(f)

        raw_trace_bytes = None
        raw_trace_path = getattr(args, "raw_trace_path", None)
        if isinstance(raw_trace_path, (str, Path)):
            trace_path = Path(raw_trace_path).resolve()
            if not _ensure_path_safe(trace_path, "Trace file"):
                return 1
            if not trace_path.exists():
                print(f"❌ Error: Raw trace file not found: {trace_path}")
                return 1
            raw_trace_bytes = trace_path.read_bytes()

        pub_key_pem = getattr(args, "public_key_pem", None)
        if isinstance(pub_key_pem, (str, Path)):
            pub_p = Path(pub_key_pem)
            if pub_p.exists():
                pub_key_pem = pub_p.read_text(encoding="utf-8")
        else:
            pub_key_pem = None

        require_sig = getattr(args, "require_signature", False) is True

        scenario_data = None
        scen_path = getattr(args, "scenario_path", None)
        if isinstance(scen_path, (str, Path)):
            scen_p = Path(scen_path).resolve()
            if _ensure_path_safe(scen_p, "Scenario file") and scen_p.exists():
                with open(scen_p, encoding="utf-8") as sf:
                    scenario_data = json.load(sf)

        require_scen = getattr(args, "require_scenario", False) is True or scenario_data is not None

        from .. import verifier

        res = verifier.VerificationAuthority.verify_package(
            pkg_data,
            scenario_data=scenario_data,
            raw_trace_bytes=raw_trace_bytes,
            public_key_pem=pub_key_pem,
            require_signature=require_sig,
            require_scenario_binding=require_scen,
        )

        if res.get("verified") and res.get("status") not in ("ATTESTED_FAIL", "FAIL", "UNVERIFIED"):
            print(f"✅ VERIFIED: Verification package '{pkg_path.name}' is valid.")
            print(f"    - Package ID: {res.get('package_id')}")
            print(f"    - Scenario ID: {res.get('scenario_id')}")
            print(f"    - Package Hash: {res.get('package_hash')}")
            print(f"    - Status: {res.get('status')}")
            return 0
        else:
            status_desc = res.get("status", "FAILED")
            print(
                f"❌ {status_desc}: Verification package '{pkg_path.name}' "
                "verification failed or attested negative outcome."
            )
            for failure in res.get("failures", []):
                print(f"    - Failure: {failure}")
            return 1
    except Exception as e:
        print(f"❌ Error during package verification: {e}")
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

    try:
        from eval_runner.runtime_services import resolve_run_store

        from .. import verifier

        provider = resolve_run_store()
        result = verifier.TraceVerifier.verify_run(run_id, run_store=provider)
        manifest = provider.get_manifest(run_id) or {}
        is_valid = bool(result["is_valid"])

        if result.get("verification_status") in ("NOT_FOUND", "UNVERIFIED") or not manifest:
            print(f"[GATE] FAILURE: Manifest not found for run: {run_id}")
            return 1

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

        print(
            f"[GATE] SUCCESS: Provider-owned verification manifest "
            f"for '{run_id}' is valid and signed."
        )
        return 0

    except Exception as e:
        print(f"[GATE] FAILURE: Unexpected failure during gating: {e}")
        return 1


async def handle_quickstart(args):
    """Handler for 'quickstart' command."""
    # Lazy Import: Defer 'quickstart' until 60-second demo is run
    from .. import quickstart

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

    try:
        from eval_runner.runtime_services import resolve_run_store

        from ..services.certification import execute_industrial_certification

        identity_id = args.identity if hasattr(args, "identity") and args.identity else "system_id"
        status = args.status if hasattr(args, "status") and args.status else None
        score = float(args.score) if hasattr(args, "score") and args.score is not None else None
        policy_ref = args.policy_ref if hasattr(args, "policy_ref") else None
        ttl_days = int(args.ttl) if hasattr(args, "ttl") and args.ttl is not None else None
        behavioral_fingerprint_id = getattr(args, "fingerprint", None)

        cert_res = execute_industrial_certification(
            run_id=args.run_id,
            identity_id=identity_id,
            status=status,
            score=score,
            policy_ref=policy_ref,
            ttl=ttl_days,
            behavioral_fingerprint_id=behavioral_fingerprint_id,
            run_store=resolve_run_store(),
        )

        print("✅ Success: Verification Certificate generated.")
        print(f"    - Run ID: {args.run_id}")
        print(f"    - SHA3-256: {cert_res.get('manifest', {}).get('trace_hash')}")
        print(f"    - Status: {cert_res.get('status')}")
        print("    - Manifest: published by the authoritative run provider")

        return 0

    except Exception as e:
        print(f"❌ Error during certification: {e}")
        return 1


async def handle_hitl_resume(args):
    """
    Resumes an evaluation run paused for Human-In-The-Loop approval.
    Resolves the durable ApprovalRequest in the ApprovalStore, and if approved,
    restores session execution from the durable checkpoint.
    """
    run_id = getattr(args, "run_id", None)
    approval_token = getattr(args, "approval_token", None)
    decision = getattr(args, "decision", "APPROVED") or "APPROVED"
    reviewer = getattr(args, "reviewer", "cli_reviewer") or "cli_reviewer"
    reason = getattr(args, "reason", None)
    store_override = getattr(args, "store", None)

    if not run_id:
        print("❌ Error: Run ID is mandatory for hitl-resume.")
        return 1
    if not approval_token:
        print("❌ Error: Approval token is mandatory for hitl-resume.")
        return 1

    normalized_decision = decision.upper().strip()
    if normalized_decision not in ("APPROVED", "REJECTED"):
        print(f"❌ Error: Invalid decision '{decision}'. Must be 'APPROVED' or 'REJECTED'.")
        return 1

    try:
        from agentv_runtime.scope import ScopeToken

        from ..runtime_services import (
            resolve_approval_store,
            resolve_execution_backend,
            resolve_run_store,
        )

        store = resolve_approval_store(store_type=store_override)

        request = store.get_request(approval_token)
        if not request:
            print(f"❌ Error: Approval request with token '{approval_token}' not found.")
            return 1

        if request.run_id != run_id:
            print(
                f"❌ Error: Approval token '{approval_token}' belongs to run '{request.run_id}', "
                f"not '{run_id}'."
            )
            return 1

        run_context = dict(request.scope) or None
        run_store = resolve_run_store()
        if run_context and run_store.get_run(run_id) is not None:
            if run_store.get_run(run_id, context=run_context) is None:
                print("❌ Error: Run is not available from the approval request's provider scope.")
                return 1
        approval_scope = ScopeToken.from_tags(run_context) if run_context else None

        already_resolved = request.status in ("APPROVED", "REJECTED")
        if already_resolved:
            print(
                f"⚠️  Notice: Approval request '{approval_token}' "
                f"was already resolved as '{request.status}' "
                f"by '{request.decided_by}'."
            )
            if request.status == "REJECTED":
                return 0

        if not already_resolved:
            # A pending approval must pass the shared Runtime resolution
            # boundary exactly once. Replaying those hooks for a durable
            # APPROVED request can block retry/resume on unrelated plugin or
            # projection work and is not a state transition.
            from eval_runner.runtime_services import resolve_plugin_registry

            from ..session_components.approval_manager import SessionApprovalManager

            SessionApprovalManager(
                run_id=run_id,
                approval_store=store,
                plugin_manager=resolve_plugin_registry(),
                scope=approval_scope,
                run_store=run_store,
            ).resolve_durable_request(
                approval_token=approval_token,
                decision=normalized_decision,
                decided_by=reviewer,
                decision_reason=reason,
            )

        if normalized_decision == "REJECTED":
            print(f"🛑 Approval REJECTED for run '{run_id}'.")
            print(f"    - Approval Token: {approval_token}")
            print(f"    - Reviewer: {reviewer}")
            if reason:
                print(f"    - Reason: {reason}")
            print("   Execution terminated cleanly.")
            return 0

        print(f"✅ Approval APPROVED for run '{run_id}'.")
        print(f"    - Approval Token: {approval_token}")
        print(f"    - Reviewer: {reviewer}")
        print(f"   Resuming evaluation execution for run '{run_id}'...")

        backend = resolve_execution_backend()
        resume_kwargs = {
            "run_id": run_id,
            "resumption_token": approval_token,
            "background": False,
        }
        if run_context:
            resume_kwargs["run_store"] = run_store
            resume_kwargs["context"] = run_context
        backend.resume(**resume_kwargs)
        completed_run = run_store.get_run(run_id, context=run_context or None) or {}
        terminal_status = str(completed_run.get("status") or "").upper()
        if terminal_status in {"FAILED", "ABORTED", "CANCELLED"}:
            print(f"\n   [CLI] Resumed evaluation finished {terminal_status} for run '{run_id}'.")
            return 1

        print(f"\n   [CLI] Resumed evaluation completed for run '{run_id}'.")
        return 0

    except Exception as e:
        print(f"❌ Error during hitl-resume: {e}")
        return 1
