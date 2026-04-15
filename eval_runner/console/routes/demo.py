import logging
import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from eval_runner import config

from ..auth_manager import Permission, require_permission
from ..demo_logic import run_demo_loan_agent

logger = logging.getLogger(__name__)

# [INDUSTRIAL STANDARDIZATION] All demo routes consolidated under /api/demo
demo_bp = Blueprint("demo", __name__, url_prefix="/api/demo")


@demo_bp.route("/reset", methods=["POST"])
@require_permission(Permission.DEMO_EXECUTE)
def reset_demo():
    """Reset demo environment state."""
    return jsonify({"status": "success", "message": "Demo environment reset."})


@demo_bp.route("/loan/context", methods=["GET"])
@require_permission(Permission.DOCS_READ)
def get_loan_demo_context():
    """Retrieve dynamic context files for the Loan Approval Demo."""
    demo_dir = (config.PROJECT_ROOT / "sample_agent" / "loan_agent_demo").resolve()
    prd_path = demo_dir / "loan_prd.md"
    aes_path = demo_dir / "loan_approval.aes.yaml"
    scenario_path = demo_dir / "loan_approval_scenario.json"

    context = {
        "prd": prd_path.open("r", encoding="utf-8").read()
        if prd_path.exists()
        else "# PRD missing",
        "aes": aes_path.open("r", encoding="utf-8").read()
        if aes_path.exists()
        else "# AES missing",
        "scenario": scenario_path.open("r", encoding="utf-8").read()
        if scenario_path.exists()
        else "{}",
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    return jsonify(context)


@demo_bp.route("/agent", methods=["POST"])
def demo_agent_route():
    """In-process demo loan agent. Accepts {prompt, hardened}."""
    data = request.json or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Missing prompt"}), 400
    result = run_demo_loan_agent(prompt, hardened=bool(data.get("hardened", False)))
    return jsonify(result)


@demo_bp.route("/evaluate", methods=["POST"])
def demo_evaluate_route():
    """Runs the in-process demo agent against both scenario tasks."""
    # Logic is handled in demo_logic.py as part of the evaluate handler if we wanted,
    # but for now we'll import if it was there.
    # Actually, let's just keep the original route logic from demo_agent.py here.
    from ..demo_logic import demo_evaluate_route as original_eval_route

    return original_eval_route()


@demo_bp.route("/execute", methods=["POST"])
@require_permission(Permission.DEMO_EXECUTE)
def execute_demo_command():
    """Execute a CLI command for the demo (Vetted Shell)."""
    data = request.json or {}
    cmd = data.get("command")
    if not cmd:
        return jsonify({"error": "Missing command"}), 400

    allowed_prefixes = [
        "agentv spec-to-eval",
        "agentv evaluate",
        "agentv aes validate",
        "agentv triage",
        "copy ",
        "cp ",
        "type ",
        "cat ",
    ]
    from eval_runner.utils import is_path_safe

    demo_dir = Path(config.PROJECT_ROOT) / "sample_agent" / "loan_agent_demo"

    if not any(cmd.lower().startswith(a.lower()) for a in allowed_prefixes):
        return jsonify({"error": f"Command not allowed: {cmd}"}), 403

    if ".." in cmd or "%2e%2e" in cmd.lower():
        return jsonify({"error": "Security: Access outside demo jail denied"}), 403

    import shutil

    cmd_lower = cmd.lower().strip()

    try:
        if cmd_lower.startswith(("type ", "cat ")):
            file_path_str = cmd.split(None, 1)[1].strip().strip('"')
            filename = os.path.basename(file_path_str.replace("\\", "/"))
            resolved_path = (demo_dir / filename).resolve()

            # [SECURITY HYGIENE] Strict Whitelist for Demo Jail
            authorized_files = [
                "loan_prd.md",
                "loan_approval.aes.yaml",
                "loan_approval_scenario.json",
                "loan_agent.py",
            ]
            if filename not in authorized_files:
                return jsonify({"error": "Security: Access outside demo jail denied"}), 403

            if not is_path_safe(resolved_path, demo_dir):
                return jsonify({"error": "Security: Access outside demo jail denied"}), 403

            if resolved_path.exists():
                return jsonify(
                    {
                        "status": "success",
                        "stdout": resolved_path.read_text(encoding="utf-8"),
                        "code": 0,
                    }
                )
            return jsonify({"status": "success", "stdout": "", "code": 0})

        if cmd_lower.startswith(("copy ", "cp ")):
            parts = shlex.split(cmd)[1:]
            if len(parts) >= 2:
                src, dst = (demo_dir / parts[0]).resolve(), (demo_dir / parts[1]).resolve()
                if is_path_safe(src, demo_dir) and is_path_safe(dst, demo_dir):
                    shutil.copy(src, dst)
                    return jsonify(
                        {
                            "status": "success",
                            "stdout": f"Copied {parts[0]} -> {parts[1]}",
                            "code": 0,
                        }
                    )

        cmd_args = shlex.split(cmd)
        if cmd_args[0] == "agentv":
            import sys

            cmd_args = [sys.executable, "-m", "eval_runner.cli"] + cmd_args[1:]

        result = subprocess.run(cmd_args, shell=False, capture_output=True, text=True, timeout=60)
        return jsonify(
            {
                "status": "success" if result.returncode == 0 else "error",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "code": result.returncode,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
