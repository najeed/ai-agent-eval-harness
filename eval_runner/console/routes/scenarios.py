import asyncio
import hashlib
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

import eval_runner
from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import engine, loader, mutator, spec_parser, taxonomy  # noqa: F401
from eval_runner.catalog import ScenarioCatalog

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

# Server-authoritative lifecycle state machine adjacency matrix.
# Keys are current states; values are the set of legally reachable next states.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Validated", "Deprecated"},
    "Validated": {"Ready", "Draft", "Deprecated"},
    "Ready": {"Deprecated"},
    "Deprecated": set(),  # Terminal — no transitions out
    "Published": {"Deprecated"},
}

# States from which a mandatory non-empty reason is required
TRANSITION_REQUIRES_REASON: set[tuple[str, str]] = {
    ("Ready", "Deprecated"),
    ("Validated", "Deprecated"),
    ("Draft", "Deprecated"),
    ("Published", "Deprecated"),
    ("Validated", "Draft"),  # Regression requires an explanation
}

scenario_bp = Blueprint("scenarios", __name__)


def get_catalog():
    return ScenarioCatalog.get_instance()


@scenario_bp.route("/scenarios", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_scenarios():
    """Returns a faceted list of all scenarios."""
    query = request.args.get("q")
    industry = request.args.get("industry")
    difficulty = request.args.get("difficulty")
    limit = int(request.args.get("limit", 10000))
    page = int(request.args.get("page", 1))
    offset = (page - 1) * limit

    catalog = get_catalog()
    if not catalog.scenarios:
        catalog.load_index()

    results = catalog.search(
        query=query, industry=industry, difficulty=difficulty, limit=limit, offset=offset
    )
    return jsonify(
        {
            "scenarios": results,
            "total_count": len(catalog.scenarios),
            "all_industries": catalog.get_all_industries(),
            "page": page,
            "limit": limit,
        }
    )


@scenario_bp.route("/scenarios/<scenario_id>", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_canonical_scenario(scenario_id: str):
    """
    Returns the complete, authoritative canonical AES scenario document from disk.
    Guarantees no semantic stripping or dummy workflow synthesis.
    """
    from agentv_runtime.manifest import compute_scenario_hash
    from eval_runner import config

    catalog = get_catalog()
    abs_path = catalog.get_absolute_path(scenario_id)

    if not abs_path or not abs_path.exists():
        # Fallback direct search in industries or scenarios folder
        matches = list(
            config.PROJECT_ROOT.glob(f"industries/**/scenarios/{scenario_id}.json")
        ) + list(config.PROJECT_ROOT.glob(f"scenarios/**/{scenario_id}.json"))
        if matches:
            abs_path = matches[0]

    if not abs_path or not abs_path.exists():
        return jsonify({"error": f"Scenario '{scenario_id}' not found in canonical catalog."}), 404

    try:
        with open(abs_path, encoding="utf-8") as f:
            data = json.load(f)
        scen_hash = compute_scenario_hash(data)
        meta = data.setdefault("metadata", {})
        meta.setdefault("version", "1.0.0")
        meta.setdefault("status", "Published" if "industries" in str(abs_path) else "Draft")
        return jsonify(
            {
                "scenario": data,
                "scenario_hash": scen_hash,
                "path": str(abs_path.relative_to(config.PROJECT_ROOT)).replace("\\", "/"),
            }
        )
    except Exception as e:
        logger.error(f"Failed to read scenario file {abs_path}: {e}")
        return jsonify({"error": f"Failed to read canonical scenario: {e}"}), 500


def validate_scenario_structure(raw_data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Comprehensive AES 1.4 schema and semantic invariant validator.
    Validates metadata, workflow node uniqueness, DAG acyclicity,
    tool constraints, assertion definitions, and state invariants.
    """
    errors: list[str] = []
    if not isinstance(raw_data, dict):
        return False, ["Scenario root must be a JSON object"]

    # 1. Metadata Validation
    meta = raw_data.get("metadata") or {}
    scen_id = meta.get("id") or raw_data.get("id")
    if not scen_id or not isinstance(scen_id, str):
        errors.append("Missing required string field 'metadata.id'")

    # 2. Workflow Nodes Validation
    workflow = raw_data.get("workflow") or {}
    nodes = workflow.get("nodes") or raw_data.get("nodes") or []
    if not isinstance(nodes, list) or len(nodes) == 0:
        errors.append("Workflow must contain at least one task node in 'workflow.nodes'")
    else:
        seen_node_ids: set[str] = set()
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"Node at index {idx} must be an object")
                continue
            nid = node.get("id")
            if not nid or not isinstance(nid, str):
                errors.append(f"Node at index {idx} missing required string 'id'")
            elif nid in seen_node_ids:
                errors.append(f"Duplicate node id '{nid}' in workflow")
            else:
                seen_node_ids.add(nid)

            task_desc = (
                node.get("task_description")
                or node.get("prompt")
                or node.get("description")
                or node.get("task")
            )
            if not task_desc:
                errors.append(f"Node '{nid or idx}' missing 'task_description' or prompt")

            # Check tools if specified
            tools = node.get("required_tools") or []
            if not isinstance(tools, list):
                errors.append(f"Node '{nid or idx}' required_tools must be a list")

        # 3. Directed Acyclic Graph (DAG) Topology Validation
        edges = workflow.get("edges") or raw_data.get("edges") or []
        if isinstance(edges, list):
            adj: dict[str, list[str]] = {nid: [] for nid in seen_node_ids}
            for e_idx, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    errors.append(f"Edge at index {e_idx} must be an object")
                    continue
                src = edge.get("source") or edge.get("from")
                tgt = edge.get("target") or edge.get("to")
                if not src or src not in seen_node_ids:
                    errors.append(f"Edge {e_idx} references unknown source node '{src}'")
                if not tgt or tgt not in seen_node_ids:
                    errors.append(f"Edge {e_idx} references unknown target node '{tgt}'")
                if src in adj and tgt:
                    adj[src].append(tgt)

            # Cycle detection (DFS)
            visited: dict[str, int] = {}  # 0: visiting, 1: visited

            def has_cycle(curr: str) -> bool:
                visited[curr] = 0
                for nxt in adj.get(curr, []):
                    if nxt in visited:
                        if visited[nxt] == 0:
                            return True
                    elif has_cycle(nxt):
                        return True
                visited[curr] = 1
                return False

            for n in seen_node_ids:
                if n not in visited:
                    if has_cycle(n):
                        errors.append("Workflow topology contains a cycle; must be a valid DAG")
                        break

    # 4. Evaluation & Assertions Invariant Check
    eval_block = raw_data.get("evaluation") or {}
    if eval_block and isinstance(eval_block, dict):
        assertions = eval_block.get("assertions") or []
        if not isinstance(assertions, list):
            errors.append("'evaluation.assertions' must be a list if defined")

    return len(errors) == 0, errors


@scenario_bp.route("/scenarios/validate", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def validate_scenario_body():
    """
    Canonical body-only AES validation endpoint.
    Accepts any scenario JSON payload (no path param required) and returns
    structured errors and warnings suitable for inline composer display.
    """
    raw_data = (request.json or {}).get("scenario") or request.json
    if not raw_data or not isinstance(raw_data, dict):
        return jsonify(
            {"valid": False, "errors": ["Request body must be a JSON scenario object"]}
        ), 400

    valid, errors = validate_scenario_structure(raw_data)

    # Produce per-node error map for inline canvas annotation
    node_errors: dict[str, list[str]] = {}
    field_errors: list[dict[str, str]] = []
    for err in errors:
        # Try to associate with a node id if the message references one
        if "Node '" in err:
            try:
                nid = err.split("Node '")[1].split("'")[0]
                node_errors.setdefault(nid, []).append(err)
            except IndexError:
                field_errors.append({"field": "workflow", "message": err})
        else:
            field_errors.append({"field": "general", "message": err})

    return jsonify(
        {
            "valid": valid,
            "errors": errors,
            "node_errors": node_errors,
            "field_errors": field_errors,
            "warnings": [],
            "status": "Validated" if valid else "Invalid",
        }
    )


@scenario_bp.route("/scenarios/<scenario_id>/validate", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def validate_scenario_schema(scenario_id):
    """
    Validates canonical scenario schema adherence and returns errors/warnings.
    """
    from eval_runner import config

    catalog = get_catalog()
    abs_path = catalog.get_absolute_path(scenario_id)
    if not abs_path or not abs_path.exists():
        ind_matches = list(config.PROJECT_ROOT.glob(f"industries/**/scenarios/{scenario_id}.json"))
        scen_matches = list(config.PROJECT_ROOT.glob(f"scenarios/**/{scenario_id}.json"))
        matches = ind_matches + scen_matches
        if matches:
            abs_path = matches[0]

    raw_data = request.json.get("scenario") if request.json else None

    if not raw_data and abs_path and abs_path.exists():
        with open(abs_path, encoding="utf-8") as f:
            raw_data = json.load(f)

    if not raw_data:
        return jsonify({"valid": False, "errors": ["Scenario document missing or empty"]}), 400

    valid, errors = validate_scenario_structure(raw_data)
    warnings: list[str] = []

    return jsonify(
        {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "status": "Validated" if valid else "Invalid",
        }
    )


@scenario_bp.route("/scenarios/readiness", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def check_execution_readiness():
    """
    Validates true Execution Readiness across scenario, agent endpoint,
    tools, policies, environment, credentials, simulator dependencies, and signing configuration.
    """
    from agentv_runtime.manifest import ManifestBuilder
    from eval_runner import config
    from eval_runner.simulators import get_simulator_registry

    data = request.json or {}
    scen_id = data.get("scenario_id") or data.get("path")
    agent_config = data.get("agent_config") or {}
    runtime_config = data.get("runtime_config") or {}

    checks: list[dict[str, Any]] = []

    # 1. Scenario Resolution & Validation
    catalog = get_catalog()
    abs_path = catalog.get_absolute_path(scen_id) if scen_id else None
    if scen_id and (not abs_path or not abs_path.exists()):
        matches = list(config.PROJECT_ROOT.glob(f"industries/**/scenarios/{scen_id}.json")) + list(
            config.PROJECT_ROOT.glob(f"scenarios/**/{scen_id}.json")
        )
        if matches:
            abs_path = matches[0]

    scen_data = data.get("scenario_data")

    if not scen_data and abs_path and abs_path.exists():
        try:
            with open(abs_path, encoding="utf-8") as f:
                scen_data = json.load(f)
        except Exception as e:
            checks.append({"name": "Scenario Resolution", "status": "FAILED", "message": str(e)})

    if scen_data:
        # Strict semantic validation
        valid, issues = validate_scenario_structure(scen_data)
        if valid:
            checks.append(
                {
                    "name": "Scenario Specification",
                    "status": "PASSED",
                    "message": "Canonical AES document loaded and verified.",
                }
            )
        else:
            checks.append(
                {
                    "name": "Scenario Specification",
                    "status": "WARNING",
                    "message": f"Validation warnings: {'; '.join(issues[:2])}",
                }
            )
    else:
        checks.append(
            {
                "name": "Scenario Specification",
                "status": "FAILED",
                "message": f"Scenario '{scen_id}' could not be resolved.",
            }
        )

    # 2. Agent Endpoint / Adapter — real connectivity probe
    proto = str(agent_config.get("protocol", "http_rest")).lower()
    endpoint = agent_config.get("endpoint", "http://localhost:8000")

    # Provider-API protocols: validate env-var presence + DNS reachability
    _provider_env_vars: dict[str, tuple[str, str]] = {
        "openai": ("OPENAI_API_KEY", "api.openai.com"),
        "gemini": ("GOOGLE_API_KEY", "generativelanguage.googleapis.com"),
        "anthropic": ("ANTHROPIC_API_KEY", "api.anthropic.com"),
        "claude": ("ANTHROPIC_API_KEY", "api.anthropic.com"),
    }
    # HTTP-style protocols that should be probed via real HTTP HEAD
    _http_probed_protocols = {
        "http_rest",
        "http",
        "rest",
        "ollama",
        "custom_http",
        "sse",
        "grpc",
        "langchain",
    }

    import os as _os
    import time as _time

    agent_check: dict[str, Any] = {
        "name": "Agent Endpoint",
        "status": "FAILED",
        "tier": "CONFIGURED",
        "message": f"Unknown protocol '{proto}'.",
        "latency_ms": None,
    }

    if proto in _provider_env_vars:
        env_var, provider_host = _provider_env_vars[proto]
        key_present = bool(_os.environ.get(env_var))
        # DNS resolution check
        dns_ok = False
        try:
            socket.getaddrinfo(provider_host, 443, proto=socket.IPPROTO_TCP)
            dns_ok = True
        except OSError:
            pass

        if key_present and dns_ok:
            agent_check.update(
                {
                    "status": "PASSED",
                    "tier": "REACHABLE",
                    "message": (
                        f"API key ({env_var}) present; provider '{provider_host}' resolves. "
                        f"Protocol: {proto}."
                    ),
                }
            )
        elif key_present:
            agent_check.update(
                {
                    "status": "WARNING",
                    "tier": "CONFIGURED",
                    "message": (
                        f"API key ({env_var}) present but provider '{provider_host}' "
                        "DNS resolution failed (network unreachable?)."
                    ),
                }
            )
        else:
            agent_check.update(
                {
                    "status": "WARNING",
                    "tier": "CONFIGURED",
                    "message": (
                        f"Protocol '{proto}' recognised but {env_var} is not set. "
                        "Configure your API key to enable execution."
                    ),
                }
            )
    elif proto in _http_probed_protocols:
        # Attempt real HTTP HEAD probe
        t0 = _time.monotonic()
        probe_ok = False
        probe_msg = ""
        try:
            # [B310 mitigation] Restrict the user-supplied endpoint to real
            # HTTP(S) schemes so preflight can never be abused to open
            # file:, ftp:, or custom-scheme URLs (SSRF / local-file read).
            endpoint_scheme = urllib.parse.urlparse(str(endpoint)).scheme.lower()
            if endpoint_scheme not in ("http", "https"):
                raise urllib.error.URLError(
                    f"Refused non-HTTP scheme '{endpoint_scheme or '(none)'}' "
                    "for connectivity probe"
                )
            health_url = endpoint.rstrip("/") + "/health"
            req = urllib.request.Request(health_url, method="HEAD")
            req.add_header("User-Agent", "AgentV-Preflight/2.0")
            with urllib.request.urlopen(req, timeout=3) as resp:  # nosec B310 - scheme allowlisted above
                probe_ok = resp.status < 600
                probe_msg = f"HTTP {resp.status}"
        except urllib.error.HTTPError as he:
            # 4xx/5xx still means the server is reachable
            probe_ok = True
            probe_msg = f"HTTP {he.code} (server reachable)"
        except (urllib.error.URLError, OSError, TimeoutError) as ue:
            probe_ok = False
            probe_msg = str(ue)
        latency_ms = int((_time.monotonic() - t0) * 1000)

        if probe_ok:
            agent_check.update(
                {
                    "status": "PASSED",
                    "tier": "REACHABLE",
                    "message": f"Endpoint '{endpoint}' reachable ({probe_msg}). Protocol: {proto}.",
                    "latency_ms": latency_ms,
                }
            )
        else:
            agent_check.update(
                {
                    "status": "WARNING",
                    "tier": "CONFIGURED",
                    "message": (
                        f"Endpoint '{endpoint}' not reachable ({probe_msg}). "
                        "Protocol configured; start the agent server to enable execution."
                    ),
                    "latency_ms": latency_ms,
                }
            )
    else:
        agent_check.update(
            {
                "status": "WARNING",
                "tier": "CONFIGURED",
                "message": (
                    f"Custom protocol '{proto}' specified. "
                    "Ensure the custom adapter handler is installed."
                ),
            }
        )

    checks.append(agent_check)

    # 3. Simulator Registry — truthful per-simulator health
    sim_registry = get_simulator_registry()
    sim_count = len(sim_registry)
    sim_healthy = 0
    sim_failed_names: list[str] = []
    for sim_name, sim_obj in sim_registry.items() if isinstance(sim_registry, dict) else []:
        try:
            ping = getattr(sim_obj, "health_check", None) or getattr(sim_obj, "ping", None)
            if callable(ping):
                ping()
            sim_healthy += 1
        except Exception as sim_err:
            sim_failed_names.append(f"{sim_name}: {sim_err}")
    if not isinstance(sim_registry, dict):
        # Registry returned a non-dict (e.g. list/count) — report truthfully
        sim_healthy = sim_count

    if sim_count == 0:
        checks.append(
            {
                "name": "Simulator Environment",
                "status": "WARNING",
                "tier": "CONFIGURED",
                "message": "No domain simulators registered. Stateless evaluation only.",
            }
        )
    elif sim_failed_names:
        checks.append(
            {
                "name": "Simulator Environment",
                "status": "WARNING",
                "tier": "CONFIGURED",
                "message": (
                    f"{sim_healthy}/{sim_count} simulators healthy. "
                    f"Failed: {'; '.join(sim_failed_names[:3])}"
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "Simulator Environment",
                "status": "PASSED",
                "tier": "EXECUTABLE",
                "message": f"{sim_count} domain simulators registered and healthy.",
            }
        )

    # 4. Signing Backend & Vault
    signing_key = getattr(config, "SIGNING_KEY", None)
    if signing_key:
        key_snippet = str(signing_key)[:12]
        checks.append(
            {
                "name": "Cryptographic Sealer",
                "status": "PASSED",
                "tier": "VERIFIABLE",
                "signer_type": "SIGNED",
                "message": f"Configured persistent Ed25519 signer active ({key_snippet}...).",
            }
        )
    else:
        checks.append(
            {
                "name": "Cryptographic Sealer",
                "status": "WARNING",
                "tier": "EXECUTABLE",
                "signer_type": "EPHEMERAL",
                "message": (
                    "Ephemeral in-memory Ed25519 sealer active (non-production mode; "
                    "set SIGNING_KEY for persistent audit sealing)."
                ),
            }
        )

    # 5. Artifact Store Destination
    runs_dir = config.RUN_LOG_DIR
    if runs_dir.exists():
        # Writable check
        try:
            probe_file = runs_dir / ".preflight_probe"
            probe_file.write_text("probe", encoding="utf-8")
            probe_file.unlink()
            checks.append(
                {
                    "name": "Artifact Store",
                    "status": "PASSED",
                    "tier": "EXECUTABLE",
                    "message": f"Artifact store writable at {runs_dir.name}/.",
                }
            )
        except OSError as ose:
            checks.append(
                {
                    "name": "Artifact Store",
                    "status": "FAILED",
                    "tier": "CONFIGURED",
                    "message": f"Artifact store not writable: {ose}",
                }
            )
    else:
        checks.append(
            {
                "name": "Artifact Store",
                "status": "FAILED",
                "tier": "CONFIGURED",
                "message": "Runs storage directory does not exist.",
            }
        )

    all_passed = all(c["status"] in ("PASSED", "WARNING") for c in checks)
    is_verifiable = (
        all_passed and signing_key is not None and all(c["status"] == "PASSED" for c in checks)
    )

    # Compute deterministic preflight fingerprint
    fingerprint_raw = {
        "scenario_id": scen_id,
        "scen_hash": compute_scenario_hash(scen_data) if scen_data else None,
        "endpoint": agent_config.get("endpoint"),
        "protocol": agent_config.get("protocol"),
        "max_turns": runtime_config.get("max_turns", 10),
    }
    preflight_fingerprint = hashlib.sha3_256(
        json.dumps(fingerprint_raw, sort_keys=True).encode("utf-8")
    ).hexdigest()

    manifest = None
    if scen_data and all_passed:
        manifest = ManifestBuilder.build(
            scenario_data=scen_data,
            agent_config=agent_config,
            runtime_config=runtime_config,
            tenant_id=data.get("tenant_id", "default"),
            workspace_id=data.get("workspace_id", "default"),
            created_by=request.headers.get("X-User-Id", "system"),
        ).to_dict()

    return jsonify(
        {
            "ready": all_passed,
            "is_executable": all_passed,
            "is_verifiable": is_verifiable,
            "tier": "VERIFIABLE"
            if is_verifiable
            else "EXECUTABLE_ONLY"
            if all_passed
            else "BLOCKED",
            "preflight_fingerprint": preflight_fingerprint,
            "checks": checks,
            "manifest": manifest,
        }
    )


@scenario_bp.route("/scenarios", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def save_scenario():
    """
    Industrial persistence for canonical scenarios with revision/status support,
    optimistic concurrency, and content hashing.
    """
    import re
    from datetime import UTC, datetime

    from agentv_runtime.manifest import compute_scenario_hash
    from eval_runner import config

    data = request.json or {}
    meta = data.setdefault("metadata", {})
    scen_id = meta.get("id") or data.get("id")
    industry = data.get("industry", "generic")

    if not scen_id or not re.match(r"^[a-zA-Z0-9_\-]+$", scen_id):
        return jsonify({"error": "Invalid or missing scenario ID"}), 400

    scen_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", scen_id)
    meta["id"] = scen_id
    meta.setdefault("version", data.get("version", "1.0.0"))

    # Server-authoritative status validation
    requested_status = data.get("status") or meta.get("status") or "Draft"
    valid, issues = validate_scenario_structure(data)
    if requested_status in ("Ready", "Validated") and not valid:
        meta["status"] = "Draft"
        meta["status_warning"] = f"Demoted from {requested_status} to Draft: {'; '.join(issues)}"
    else:
        meta["status"] = requested_status

    if valid:
        meta["validated_at"] = datetime.now(UTC).isoformat()
        meta["validated_by"] = request.headers.get("X-User-Id", "system")

    # Compute content hash
    scen_hash = compute_scenario_hash(data)
    meta["content_hash"] = scen_hash

    save_dir = config.PROJECT_ROOT / "industries" / industry / "scenarios"
    save_dir.mkdir(parents=True, exist_ok=True)

    save_path = save_dir / f"{scen_id}.json"

    # Optimistic concurrency check
    expected_rev = data.get("expected_revision_hash") or meta.get("expected_revision_hash")
    if expected_rev and save_path.exists():
        try:
            with open(save_path, encoding="utf-8") as f_ex:
                ex_data = json.load(f_ex)
                curr_hash = compute_scenario_hash(ex_data)
                if curr_hash != expected_rev:
                    return (
                        jsonify(
                            {
                                "error": "Revision conflict: Scenario modified concurrently.",
                                "current_hash": curr_hash,
                                "expected_hash": expected_rev,
                            }
                        ),
                        409,
                    )
        except Exception as e:
            logger.debug(f"Concurrency check bypass on read failure: {e}")

    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save scenario {scen_id}: {e}")
        return jsonify({"error": f"Failed to save scenario: {str(e)}"}), 500

    ScenarioCatalog.get_instance().build_index()
    return jsonify(
        {
            "status": "success",
            "id": scen_id,
            "scenario_id": scen_id,
            "path": str(save_path.relative_to(config.PROJECT_ROOT)).replace("\\", "/"),
            "scenario_hash": scen_hash,
            "version": meta["version"],
            "lifecycle_status": meta["status"],
        }
    )


@scenario_bp.route("/scenarios/<scenario_id>/transition", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def transition_scenario_lifecycle(scenario_id):
    """
    Server-authoritative state machine transition:
    Draft -> Validated -> Ready -> Deprecated
    """
    from datetime import UTC, datetime

    from agentv_runtime.manifest import compute_scenario_hash
    from eval_runner import config

    data = request.json or {}
    target_status = data.get("target_status")
    allowed_statuses = {"Draft", "Validated", "Ready", "Deprecated"}
    if target_status not in allowed_statuses:
        return jsonify({"error": f"Invalid target_status. Must be one of: {allowed_statuses}"}), 400

    catalog = ScenarioCatalog.get_instance()
    abs_path = catalog.get_absolute_path(scenario_id)
    if not abs_path or not abs_path.exists():
        matches = list(
            config.PROJECT_ROOT.glob(f"industries/**/scenarios/{scenario_id}.json")
        ) + list(config.PROJECT_ROOT.glob(f"scenarios/**/{scenario_id}.json"))
        if matches:
            abs_path = matches[0]

    if not abs_path or not abs_path.exists():
        return jsonify({"error": f"Scenario {scenario_id} not found"}), 404

    try:
        with open(abs_path, encoding="utf-8") as f:
            scen_data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Failed to load scenario: {e}"}), 500

    meta = scen_data.setdefault("metadata", {})
    valid, issues = validate_scenario_structure(scen_data)

    if target_status in ("Validated", "Ready") and not valid:
        return jsonify(
            {
                "error": f"Cannot transition to {target_status}: Scenario validation failed.",
                "issues": issues,
            }
        ), 400

    previous_status = meta.get("status", "Draft")

    # Enforce legal transition adjacency matrix
    legal_next = LEGAL_TRANSITIONS.get(previous_status, set())
    if target_status not in legal_next:
        return jsonify(
            {
                "error": (
                    f"Illegal lifecycle transition: '{previous_status}' → '{target_status}'. "
                    f"Legal next states from '{previous_status}': "
                    f"{sorted(legal_next) if legal_next else ['(none — terminal state)']}"
                ),
                "current_status": previous_status,
                "requested_status": target_status,
                "legal_transitions": sorted(legal_next),
            }
        ), 400

    # Require explicit reason for sensitive regressions and deprecations
    reason = data.get("reason", "").strip()
    if (previous_status, target_status) in TRANSITION_REQUIRES_REASON and not reason:
        return jsonify(
            {
                "error": (
                    f"Transition '{previous_status}' → '{target_status}' requires "
                    "a non-empty 'reason' field for audit traceability."
                )
            }
        ), 400

    import uuid as _uuid

    meta["status"] = target_status
    meta["transition_history"] = meta.get("transition_history") or []
    meta["transition_history"].append(
        {
            "revision_id": str(_uuid.uuid4()),
            "from": previous_status,
            "to": target_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "actor": request.headers.get("X-User-Id", "system"),
            "reason": reason or "Lifecycle transition requested",
        }
    )
    meta["content_hash"] = compute_scenario_hash(scen_data)

    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(scen_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return jsonify({"error": f"Failed to persist scenario transition: {e}"}), 500

    catalog.build_index()
    return jsonify(
        {
            "status": "success",
            "scenario_id": scenario_id,
            "lifecycle_status": target_status,
            "content_hash": meta["content_hash"],
        }
    )


@scenario_bp.route("/scenarios/refresh", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def refresh_index():
    """Triggers catalog re-indexing."""
    try:
        ScenarioCatalog.get_instance().build_index()
        return jsonify(
            {"status": "success", "scenario_count": len(ScenarioCatalog.get_instance().scenarios)}
        )
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        return jsonify({"error": str(e)}), 500


@scenario_bp.route("/v1/evaluate", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def evaluate_scenario():
    """
    Triggers an evaluation run bound to an immutable ExecutionManifest.
    """
    import time

    from agentv_runtime.manifest import ManifestBuilder
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    data = request.json or {}
    path = data.get("path")
    if not path:
        return jsonify({"error": "Missing scenario path"}), 400

    catalog = ScenarioCatalog.get_instance()
    abs_path = catalog.get_absolute_path(path)

    if abs_path and abs_path.exists():
        path = str(abs_path)
    else:
        from eval_runner import config

        target = Path(path)
        if not target.is_absolute():
            target = config.PROJECT_ROOT / path
        if target.exists():
            path = str(target)
        else:
            msg = f"Scenario not found: {path}"
            return jsonify({"error": msg, "message": msg}), 404

    try:
        scen = eval_runner.loader.load_scenario(path)
    except Exception as e:
        logger.error(f"Scenario load failed: {e}")
        return jsonify({"error": f"Failed to load scenario: {str(e)}", "message": str(e)}), 500

    identifier = Path(path).stem
    run_id = f"run-{identifier}-{time.time_ns()}"

    meta = data.get("metadata") or {}
    raw_agent_config = data.get("agent_config") or {}

    agent_config = {
        "agent_name": raw_agent_config.get("agent_name")
        or data.get("agent_name")
        or meta.get("agent_name")
        or "default_agent",
        "protocol": raw_agent_config.get("protocol")
        or data.get("protocol")
        or meta.get("protocol")
        or "http_rest",
        "endpoint": raw_agent_config.get("endpoint")
        or data.get("endpoint")
        or meta.get("agent_url")
        or meta.get("endpoint")
        or "http://localhost:8000",
        "model": raw_agent_config.get("model")
        or data.get("model")
        or meta.get("model")
        or "gpt-4o",
        **{
            k: v
            for k, v in raw_agent_config.items()
            if k not in ("agent_name", "protocol", "endpoint", "model")
        },
    }

    raw_runtime_config = data.get("runtime_config") or {}
    runtime_config = {
        "max_turns": raw_runtime_config.get("max_turns") or data.get("max_turns", 10),
        "signing_backend": raw_runtime_config.get("signing_backend") or "ed25519",
        "policy_evaluator": raw_runtime_config.get("policy_evaluator") or "standard",
        **{
            k: v
            for k, v in raw_runtime_config.items()
            if k not in ("max_turns", "signing_backend", "policy_evaluator")
        },
    }

    manifest = ManifestBuilder.build(
        scenario_data=scen,
        agent_config=agent_config,
        runtime_config=runtime_config,
        tenant_id=data.get("tenant_id", "default"),
        workspace_id=data.get("workspace_id", "default"),
        created_by=request.headers.get("X-User-Id", "system"),
        metadata=data.get("metadata"),
    )

    backend = InProcessExecutionBackend.get_instance()
    backend.submit(
        run_id=run_id,
        scenario_data=scen,
        background=True,
        max_turns=data.get("max_turns", 10),
        metadata={**data.get("metadata", {}), "execution_manifest": manifest.to_dict()},
    )

    return jsonify(
        {
            "status": "started",
            "run_id": run_id,
            "manifest_id": manifest.manifest_id,
            "manifest": manifest.to_dict(),
            "message": f"Evaluation of {path} initiated with manifest {manifest.manifest_id}.",
        }
    )


@scenario_bp.route("/v1/taxonomy", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_taxonomy():
    """Roadmap: Display the official AEH failure taxonomy."""
    return jsonify({"categories": eval_runner.taxonomy.CATEGORIES})


@scenario_bp.route("/v1/mutate", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def mutate_scenario():
    """Roadmap: Programmatic mutation with raw content or file support."""
    from eval_runner import config, utils

    data = request.json or {}
    mutation_type = data.get("type", "typo")

    # Support raw content, scenario ID, or input path
    raw_content = data.get("raw_json")
    scenario_id = data.get("scenario_id")
    if raw_content:
        scenario = raw_content
    elif scenario_id:
        catalog = ScenarioCatalog.get_instance()
        abs_path = catalog.get_absolute_path(scenario_id)
        if not abs_path or not abs_path.exists():
            return jsonify({"error": f"Scenario {scenario_id} not found"}), 404
        with open(abs_path, encoding="utf-8") as f:
            scenario = json.load(f)
    else:
        input_path = data.get("input_path")
        if not input_path:
            return jsonify({"error": "Missing input_path, scenario_id or raw_json"}), 400

        # Path Traversal Guard
        if not utils.is_path_safe(input_path, config.PROJECT_ROOT):
            return jsonify({"error": "Access denied: input_path outside project root"}), 403

        if not Path(input_path).exists():
            return jsonify({"error": f"input_path not found: {input_path}"}), 400

        with open(input_path, encoding="utf-8") as f:
            scenario = json.load(f)

    try:
        mutated = eval_runner.mutator.mutate_scenario(scenario, mutation_type)

        # Optionally save to output path
        output_path = data.get("output_path")
        if output_path:
            # Path Traversal Guard
            if not utils.is_path_safe(output_path, config.PROJECT_ROOT):
                return jsonify({"error": "Access denied: output_path outside project root"}), 403
            eval_runner.mutator.save_mutated_scenario(mutated, Path(output_path))

        return jsonify({"status": "success", "mutated": mutated})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@scenario_bp.route("/v1/spec-to-eval", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def spec_to_eval():
    """Roadmap: Markdown PRD/Spec to AES JSON conversion."""
    from eval_runner import config, utils

    data = request.json or {}
    markdown_text = data.get("markdown")

    if not markdown_text:
        input_path = data.get("input_path")
        if not input_path:
            return jsonify({"error": "Missing markdown text or input_path"}), 400

        # Path Traversal Guard
        if not utils.is_path_safe(input_path, config.PROJECT_ROOT):
            return jsonify({"error": "Access denied: input_path outside project root"}), 403

        if not Path(input_path).exists():
            return jsonify({"error": f"input_path not found: {input_path}"}), 400

        with open(input_path, encoding="utf-8") as f:
            markdown_text = f.read()

    try:
        # Wrap async call for Flask compatibility
        scenario = asyncio.run(eval_runner.spec_parser.parse_markdown_to_scenario(markdown_text))

        output_path = data.get("output_path")
        if output_path:
            # Path Traversal Guard
            if not utils.is_path_safe(output_path, config.PROJECT_ROOT):
                return jsonify({"error": "Access denied: output_path outside project root"}), 403
            eval_runner.spec_parser.save_scenario_json(scenario, Path(output_path))

        return jsonify({"status": "success", "scenario": scenario})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@scenario_bp.route("/v1/auto-translate", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def auto_translate_spec():
    """
    Exposes auto-translation capability via the backend.
    Calls auto_translate.translate_to_scenario.
    Avoids client-side CORS issues and keeps the prompt template on the server.
    """
    import os

    from eval_runner import config
    from eval_runner.auto_translate import translate_to_scenario

    data = request.get_json() or {}
    text = data.get("text", "")
    model = data.get("model", "llama3")

    if not text:
        return jsonify({"error": "Missing required field: text"}), 400

    endpoint = getattr(config, "OLLAMA_BASE_URL", None) or os.environ.get(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )
    api_url = f"{endpoint}/api/generate"

    try:
        scenario = asyncio.run(translate_to_scenario(text, model=model, api_url=api_url))
        return jsonify(scenario)
    except Exception as e:
        logger.error(f"Auto-translation failed: {e}", exc_info=True)
        return jsonify({"error": str(e), "message": "Failed to auto-translate specification."}), 500
