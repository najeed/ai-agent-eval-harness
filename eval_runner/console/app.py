import json
import os
from pathlib import Path
from urllib.parse import urlparse

import flask
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from eval_runner.plugins import manager

from .. import config
from .auth import auth_bp
from .routes import (
    agent_targets_bp,
    analyze_bp,
    core_bp,
    demo_bp,
    evidence_bp,
    register_core_routes,
    run_bp,
    scenario_bp,
    subscribe_debugger,
    system_bp,
    trust_bp,
)

# Ensure environment variables are loaded before ANY other configuration usage (R6)
load_dotenv()
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

print(
    "--- Flask App Initializing",
    flush=True,
)


UI_BUILD_DIR = None


def _configured_extension_origins() -> list[str]:
    """Return CSP-safe origins for signed remote extension bundles.

    Remote extensions remain disabled unless their origin is explicitly
    declared by the server operator.  The browser CSP must agree with the
    extension contract; SRI alone cannot bypass a restrictive connect-src.
    """
    origins: list[str] = []
    for value in os.getenv("AGENTV_EXTENSION_ORIGINS", "").split(","):
        parsed = urlparse(value.strip())
        if parsed.scheme == "https" and parsed.netloc:
            origins.append(f"https://{parsed.netloc}")
        elif parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            origins.append(f"http://{parsed.netloc}")
    return sorted(set(origins))


def _safe_extension_route_prefix(path: str, reserved_roots: set[str]) -> str | None:
    """Return a static, non-Core route prefix or reject it fail-closed."""
    if not path.startswith("/") or path == "/":
        return None
    segments = path.lstrip("/").split("/")
    if any(
        not segment or segment in {".", ".."} or "<" in segment or ">" in segment
        for segment in segments
    ):
        return None
    if segments[0] in reserved_roots:
        return None
    return "/" + "/".join(segments)


def _published_extension_spa_prefixes(
    *, reserved_roots: set[str], verified_manifests: list | None = None
) -> list[str]:
    """Discover only currently verified signed extension route prefixes.

    The artifact store is not itself authoritative: each sidecar must pass
    Runtime contract, publisher, and artifact verification before its declared
    SPA paths may resolve to the Console shell.
    """
    from agentv_runtime.extension_contract import RuntimeExtension

    from .extension_publisher import verify_extension
    from .routes.trust import _public_key_pem_bytes

    root = Path(config.EXTENSION_ARTIFACT_DIR)
    if not root.is_dir():
        return []
    enabled_raw = os.getenv("AGENTV_ENABLED_EXTENSION_IDS", "").strip()
    enabled_ids = {item.strip() for item in enabled_raw.split(",") if item.strip()}
    prefixes: set[str] = set()
    active_dir = root / ".active-releases"
    has_active_registry = active_dir.is_dir() and any(active_dir.glob("*/*.json"))

    candidates: list[tuple[Path, str | None]] = []
    if has_active_registry:
        for active_rec_file in sorted(active_dir.glob("*/*.json")):
            try:
                active_data = json.loads(active_rec_file.read_text(encoding="utf-8"))
                ext_id = active_data.get("extension_id")
                ver = active_data.get("version")
                pub = active_data.get("publisher")
                if ext_id and ver:
                    manifest_path = root / ext_id / ver / "entry.manifest.json"
                    candidates.append((manifest_path, pub))
            except (OSError, json.JSONDecodeError):
                continue
    else:
        candidates = [(p, None) for p in root.glob("*/*/entry.manifest.json")]

    seen_extension_ids: set[str] = set()
    for manifest_file, expected_publisher in candidates:
        if not manifest_file.is_file():
            continue
        try:
            raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = RuntimeExtension.from_dict(raw_manifest)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"   [Console] Ignoring invalid extension sidecar {manifest_file}: {exc}")
            continue
        if (
            manifest.extension_id != manifest_file.parent.parent.name
            or manifest.version != manifest_file.parent.name
            or manifest.validate()
        ):
            print(f"   [Console] Ignoring contract-invalid extension sidecar {manifest_file}")
            continue
        if expected_publisher and manifest.publisher != expected_publisher:
            print(f"   [Console] Ignoring publisher mismatch on {manifest_file}")
            continue
        if manifest.extension_id in seen_extension_ids:
            print(f"   [Console] Duplicate extension ID {manifest.extension_id!r} ignored")
            continue
        if enabled_raw and manifest.extension_id not in enabled_ids:
            print(f"   [Console] Extension {manifest.extension_id!r} is not enabled")
            continue
        verification = verify_extension(
            extension_id=manifest.extension_id,
            version=manifest.version,
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
        if not verification["valid"]:
            print(f"   [Console] Ignoring unverified extension sidecar {manifest_file}")
            continue
        seen_extension_ids.add(manifest.extension_id)
        if verified_manifests is not None:
            verified_manifests.append(manifest)
        for route in manifest.routes:
            prefix = _safe_extension_route_prefix(route.path, reserved_roots)
            if prefix is None:
                print(f"   [Console] Ignoring unsafe extension route {route.path!r}")
                continue
            prefixes.add(prefix)
    return sorted(prefixes)


def create_app():
    # Eager Hydration: Ensure scenarios are loaded before the first request
    from eval_runner.catalog import ScenarioCatalog

    # [STARTUP ACCELERATION]: Bypass heavy indexing for Trust Portal Stability
    if not config.ENABLE_DEMO:
        ScenarioCatalog.get_instance().load_index()
    else:
        print("   [Industrial Start] Lazy Catalog active for Demo Stability.", flush=True)

    # visual-console/dist is the ONLY supported UI. The legacy
    # CDN-loaded prototype (ui/visual-debugger) was removed — silently
    # degrading to it broke air-gapped deployments and hid the missing build.
    ui_target = (
        UI_BUILD_DIR
        or getattr(config, "UI_BUILD_DIR", None)
        or (config.PROJECT_ROOT / "ui" / "visual-console" / "dist")
    )
    v2_ui_dist = os.path.abspath(ui_target)
    is_prod = config.is_production()
    ui_exists = os.path.isdir(v2_ui_dist) and os.path.exists(os.path.join(v2_ui_dist, "index.html"))
    if not ui_exists:
        if is_prod:
            raise RuntimeError(
                "[Console][CRITICAL] Production environment (AGENTV_ENV=production) "
                "requires built visual-console artifact at ui/visual-console/dist. "
                "Visual Console frontend bundle missing. "
                "Failing closed because GUI assets are missing."
            )
        ui_path = v2_ui_dist  # Flask tolerates an absent static dir at boot.
        print(
            "   [Console][WARN] ui/visual-console/dist is NOT BUILT. The "
            "console API will serve without the Visual Suite UI. Build it "
            "with: cd ui/visual-console && npm ci && npm run build",
            flush=True,
        )
    else:
        ui_path = v2_ui_dist
    app = Flask(__name__, static_folder=ui_path, static_url_path="/static")

    # Bootstrap key initialization for zero-config non-production environments
    has_api_key = bool(
        getattr(config, "SERVICE_API_KEY", None)
        or getattr(config, "DASHBOARD_API_KEY", None)
        or os.getenv("SERVICE_API_KEY")
        or os.getenv("DASHBOARD_API_KEY")
    )
    if not has_api_key:
        if config.is_production():
            raise RuntimeError(
                "[Console][CRITICAL] AGENTV_ENV=production requires "
                "DASHBOARD_API_KEY or SERVICE_API_KEY."
            )
        import secrets
        from pathlib import Path

        keys_dir = Path(config.PROJECT_ROOT) / ".aes" / "keys"
        keys_dir.mkdir(parents=True, exist_ok=True)
        boot_file = keys_dir / "bootstrap.key"
        if boot_file.exists():
            bootstrap_key = boot_file.read_text(encoding="utf-8").strip()
        else:
            bootstrap_key = secrets.token_urlsafe(32)
            try:
                boot_file.write_text(bootstrap_key, encoding="utf-8")
                try:
                    os.chmod(boot_file, 0o600)
                except (OSError, NotImplementedError) as chmod_err:
                    print(
                        "   [Console][DEBUG] Could not set 0600 permissions on "
                        f"bootstrap.key: {chmod_err}",
                        flush=True,
                    )
            except Exception as e:
                print(f"   [Console][WARN] Could not write bootstrap.key: {e}", flush=True)

        config.SERVICE_API_KEY = bootstrap_key
        if not getattr(config, "DASHBOARD_API_KEY", None):
            config.DASHBOARD_API_KEY = bootstrap_key

        print(
            "\n"
            "================================================================================\n"
            "   [AgentV Security] ZERO-CONFIG BOOTSTRAP ADMIN KEY GENERATED\n"
            "   No DASHBOARD_API_KEY or SERVICE_API_KEY was found in environment or .env.\n"
            f"   Bootstrap Key: {bootstrap_key}\n"
            "   (Saved to .aes/keys/bootstrap.key for local development and initial "
            "console access)\n"
            "================================================================================\n",
            flush=True,
        )
    else:
        if not getattr(config, "DASHBOARD_API_KEY", None):
            config.DASHBOARD_API_KEY = (
                os.getenv("DASHBOARD_API_KEY")
                or getattr(config, "SERVICE_API_KEY", None)
                or os.getenv("SERVICE_API_KEY")
            )

    # Ensure session persistence via strict zero-config bootstrap or explicit secret
    api_key = (
        getattr(config, "DASHBOARD_API_KEY", None)
        or os.getenv("DASHBOARD_API_KEY")
        or getattr(config, "SERVICE_API_KEY", None)
        or os.getenv("SERVICE_API_KEY")
    )
    secret_key_env = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET")
    if not (api_key or secret_key_env):
        raise RuntimeError(
            "[Console][CRITICAL] Missing API key or secret key for console session derivation. "
            "In production, configure DASHBOARD_API_KEY, SERVICE_API_KEY, "
            "SECRET_KEY, or JWT_SECRET. "
            "In development, ensure zero-config bootstrap key is generated."
        )

    # Resolve the configured backend while the Console is starting so an
    # invalid declarative factory prevents serving requests without its
    # intended authorization policy.
    from .auth_manager import get_auth_provider

    get_auth_provider()

    from ..utils import crypto

    app.secret_key = crypto.checksum(api_key or secret_key_env)

    # Explicit Session Cookie Hardening (T2 DevSecOps)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    is_prod = config.is_production()
    app.config["SESSION_COOKIE_SECURE"] = (
        is_prod or os.getenv("AGENTV_SECURE_COOKIES", "false").lower() == "true"
    )

    # CORS is opt-in only. With no explicit allow-list the console is
    # same-origin and emits no CORS headers — never reflect arbitrary origins
    # on credentialed requests.
    if getattr(config, "ALLOWED_ORIGINS", None):
        CORS(
            app,
            origins=config.ALLOWED_ORIGINS,
            supports_credentials=True,
        )
    app.register_blueprint(auth_bp)
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")
    app.register_blueprint(run_bp, url_prefix="/api")
    app.register_blueprint(analyze_bp, url_prefix="/api")
    # Extension-owned server routes are supplied through the signed extension
    # contract; Core mounts no product-specific endpoints here.
    app.register_blueprint(evidence_bp, url_prefix="/api")
    app.register_blueprint(agent_targets_bp)

    app.register_blueprint(trust_bp)

    # Demo blueprint is physically absent in production mode (ENABLE_DEMO=false).
    # This prevents demo routes from appearing in the route map at all.
    if config.ENABLE_DEMO:
        app.register_blueprint(demo_bp)
        print("   [Console] Demo mode active: demo_bp registered.", flush=True)
    else:
        print("   [Console] Production mode: demo_bp NOT registered.", flush=True)
    app.register_blueprint(core_bp)
    # Mount critical diagnostic shims directly into the Root /v1 namespace
    # to align with documentation.

    # Filter high-frequency telemetry loopback unless debug mode is enabled
    is_debug_mode = bool(
        app.debug
        or os.getenv("AGENTV_DEBUG", "0").lower() in ("1", "true", "yes")
        or os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")
    )
    if not is_debug_mode:
        import logging

        class TelemetryLoopbackFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                msg = record.getMessage()
                if "/api/debugger/state" in msg and " 200 " in msg:
                    return False
                return True

        logging.getLogger("werkzeug").addFilter(TelemetryLoopbackFilter())

    @app.before_request
    def trace_request():
        import sys

        is_debug = (
            app.debug
            or os.getenv("AGENTV_DEBUG", "0").lower() in ("1", "true", "yes")
            or os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")
        )
        if not is_debug and flask.request.path.startswith("/api/debugger/state"):
            flask.g._skip_trace = True
            return

        sys.stderr.write(
            f"   [Trace] {flask.request.method} {flask.request.path} "
            f"(Endpoint: {flask.request.endpoint})\n"
        )
        sys.stderr.flush()

    @app.after_request
    def trace_response(response):
        import sys

        if not getattr(flask.g, "_skip_trace", False):
            sys.stderr.write(f"   [Trace] Status: {response.status_code}\n")
            sys.stderr.flush()
        elif response.status_code >= 400:
            # Preserve error visibility: never swallow non-200 responses even for telemetry paths
            sys.stderr.write(
                f"   [Trace] {flask.request.method} {flask.request.path} "
                f"(Endpoint: {flask.request.endpoint})\n"
                f"   [Trace] Status: {response.status_code}\n"
            )
            sys.stderr.flush()
        # Surface the current operational mode to all clients
        mode = "demo" if config.ENABLE_DEMO else "production"
        response.headers["X-AgentV-Mode"] = mode
        return response

    # [Extension isolation — feasible slice] Document-level CSP for the
    # console shell. The allowlist is exact:
    #   - cdn.jsdelivr.net: Monaco editor assets (@monaco-editor/loader CDN).
    #   - blob: in script-src/worker-src: the extension host mounts SRI-verified
    #     remote modules through ephemeral Blob URLs; this is a deliberate,
    #     documented seam (SRI proves bytes, signed manifests prove trust).
    # Everything else is locked to self. This does NOT authorize arbitrary
    # third-party script origins.
    extension_origins = _configured_extension_origins()
    extension_connect_sources = " ".join(extension_origins)

    def _build_console_csp() -> str:
        # Air-gapped isolation & operator CSP configuration (SOC 2 DF-05)
        script_sources = ["'self'", "blob:"]
        connect_sources = ["'self'"]

        if not config.is_airgapped():
            script_sources.insert(1, "https://cdn.jsdelivr.net")
            connect_sources.append("https://cdn.jsdelivr.net")

        custom_script_src = getattr(config, "CONSOLE_CSP_SCRIPT_SRC", "") or os.getenv(
            "CONSOLE_CSP_SCRIPT_SRC", ""
        )
        if custom_script_src:
            for src in custom_script_src.split():
                if src and src not in script_sources:
                    script_sources.append(src)

        custom_connect_src = getattr(config, "CONSOLE_CSP_CONNECT_SRC", "") or os.getenv(
            "CONSOLE_CSP_CONNECT_SRC", ""
        )
        if custom_connect_src:
            for src in custom_connect_src.split():
                if src and src not in connect_sources:
                    connect_sources.append(src)

        if extension_connect_sources:
            connect_sources.append(extension_connect_sources)

        return "; ".join(
            [
                "default-src 'self'",
                f"script-src {' '.join(script_sources)}",
                "worker-src 'self' blob:",
                f"connect-src {' '.join(connect_sources)}",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: blob:",
                "font-src 'self' data:",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
                "object-src 'none'",
            ]
        )

    _build_console_csp()

    @app.after_request
    def security_headers(response):
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", _build_console_csp())
            response.headers.setdefault("X-Frame-Options", "DENY")
            if extension_origins:
                response.headers.setdefault(
                    "X-AgentV-Extension-Origins", ",".join(extension_origins)
                )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    # Hardened API Error Handlers (Prevents "Unexpected token <" regressions)
    @app.errorhandler(405)
    def handle_405(e):
        import sys

        sys.stderr.write(
            f"   [API] 405 Method Not Allowed - URL: {flask.request.url}, "
            f"Method: {flask.request.method}\n"
        )
        sys.stderr.write(
            f"   [API] 405 DEBUG - Rule: {flask.request.url_rule}, "
            f"Args: {flask.request.view_args}\n"
        )
        sys.stderr.flush()
        return flask.jsonify(
            {
                "error": "Method Not Allowed: This endpoint does not accept the requested HTTP method.",  # noqa: E501
                "status": 405,
            }
        ), 405

    # Hardened Route Precedence (AgentV v1.6.0 Sync)
    # Industrial Standard: Use blueprint-first registration only.

    # External plugin entry points may import distributed runtimes.  Console startup
    # stays on the core/local path unless an operator explicitly enables external
    # console extensions for this server process.
    enable_external_console_plugins = os.getenv(
        "AGENTV_ENABLE_EXTERNAL_CONSOLE_PLUGINS", ""
    ).lower() in {"1", "true", "yes"}
    manager.load_plugins(load_external=enable_external_console_plugins)

    # Core navigation registry
    nav_registry = []

    # Register core routes
    register_core_routes(app, nav_registry)

    # Safely initialize debugger event subscription

    subscribe_debugger()

    # Trigger plugin hook to register additional routes and nav items
    plugin_errors: list[dict[str, str]] = []
    for plugin in manager.plugins:
        method = getattr(plugin, "on_register_console_routes", None)
        if method and callable(method):
            try:
                method(app, nav_registry)
            except Exception as e:
                err_msg = str(e)
                print(
                    f"   [Console] Warning: Route registration failed for "
                    f"{plugin.__class__.__name__}: {err_msg}"
                )
                plugin_errors.append(
                    {
                        "plugin": plugin.__class__.__name__,
                        "error": err_msg,
                    }
                )

    app.config["PLUGIN_REGISTRATION_ERRORS"] = plugin_errors

    # Re-assert core paths and industrial components to prevent plugin overrides
    core_overrides = {
        "community": {"path": "https://github.com/najeed/ai-agent-eval-harness"},
        "demo": {"path": "/demo"},
        "loan_demo": {"path": "/demo/loan"},
    }
    for item in nav_registry:
        if item.get("id") in core_overrides:
            item.update(core_overrides[item.get("id")])

    # Endpoint to serve the unified navigation menu (API Priority)
    app.config["NAV_REGISTRY"] = nav_registry

    # Industrial Diagnostic: Audit the physical route map (v1.6.0 Hardening)
    print("\n--- Industrial Route Map Audit ---", flush=True)
    for rule in app.url_map.iter_rules():
        print(f"   [Route] {rule.rule} ({rule.endpoint})", flush=True)
    print("--- Audit Complete ---\n", flush=True)

    # Assets route for visual-console
    @app.route("/assets/<path:path>")
    def serve_assets(path):
        assets_dir = os.path.join(ui_path, "assets")
        if os.path.exists(assets_dir):
            return send_from_directory(assets_dir, path)
        return jsonify({"error": "Asset Not Found"}), 404

    @app.route("/extensions/<path:path>")
    def serve_signed_extension(path):
        """Serve only Runtime-published extension artifacts at stable relative URLs."""
        extension_dir = str(config.EXTENSION_ARTIFACT_DIR)
        if os.path.exists(extension_dir):
            return send_from_directory(extension_dir, path)
        return jsonify({"error": "Extension Not Found"}), 404

    @app.route("/v2/assets/<path:path>")
    def serve_v2_assets(path):
        assets_dir = os.path.join(v2_ui_dist, "assets")
        if os.path.exists(assets_dir):
            return send_from_directory(assets_dir, path)
        return jsonify({"error": "Asset Not Found"}), 404

    # Direct static asset files from root
    @app.route("/favicon.png")
    @app.route("/logo-premium.png")
    @app.route("/favicon.svg")
    @app.route("/icons.svg")
    def serve_root_icons():
        filename = flask.request.path.lstrip("/")
        if os.path.exists(os.path.join(ui_path, filename)):
            return send_from_directory(ui_path, filename)
        return jsonify({"error": "Icon Not Found"}), 404

    # Compatibility Route: /v2 serves the new console
    @app.route("/v2", defaults={"path": ""}, strict_slashes=False)
    @app.route("/v2/<path:path>", strict_slashes=False)
    def serve_v2(path=""):
        if path:
            full_path = os.path.join(v2_ui_dist, path)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                return send_from_directory(v2_ui_dist, path)
        return send_from_directory(v2_ui_dist, "index.html")

    # Canonical Primary Console Entrypoints & SPA Navigation
    # OSS SPA Navigation — only OSS routes are declared here.
    # Verified extension prefixes are registered below.
    @app.route("/", defaults={"path": ""}, strict_slashes=False)
    @app.route("/scenarios", strict_slashes=False)
    @app.route("/reports", strict_slashes=False)
    @app.route("/editor", strict_slashes=False)
    @app.route("/debugger", strict_slashes=False)
    @app.route("/runner", strict_slashes=False)
    @app.route("/trust", strict_slashes=False)
    @app.route("/settings", strict_slashes=False)
    @app.route("/spec-import", strict_slashes=False)
    @app.route("/mutator", strict_slashes=False)
    @app.route("/failures", strict_slashes=False)
    @app.route("/triage", strict_slashes=False)
    @app.route("/docs", strict_slashes=False)
    @app.route("/docs/api", strict_slashes=False)
    def index(path=""):
        return serve_console_shell()

    def serve_console_shell(**_unused):
        if not os.path.exists(os.path.join(ui_path, "index.html")):
            return jsonify({"error": "Visual Console not built"}), 404
        return send_from_directory(ui_path, "index.html")

    # A signed extension can contribute SPA route prefixes through its
    # published RuntimeExtension manifest. This is intentionally a startup
    # registry: unknown, uninstalled, disabled, or unverified paths remain
    # ordinary 404s and extensions never add Flask routes themselves.
    reserved_roots = {
        rule.rule.lstrip("/").split("/", 1)[0]
        for rule in app.url_map.iter_rules()
        if rule.rule != "/" and "<" not in rule.rule
    }
    reserved_roots.update({"api", "auth", "assets", "extensions", "v2"})
    verified_extension_manifests: list = []
    extension_spa_prefixes = _published_extension_spa_prefixes(
        reserved_roots=reserved_roots, verified_manifests=verified_extension_manifests
    )
    app.config["EXTENSION_SPA_PREFIXES"] = extension_spa_prefixes
    # Navigation is derived only from server-verified signed manifest values;
    # route permissions remain the sole visibility/access gate.
    for manifest in verified_extension_manifests:
        routes_by_path = {route.path: route for route in manifest.routes}
        for navigation in manifest.navigation:
            route = routes_by_path[navigation.path]
            nav_registry.append(
                {
                    "id": navigation.id or f"{manifest.extension_id}:{navigation.path}",
                    "name": navigation.title or route.label or navigation.path,
                    "path": navigation.path,
                    "group": navigation.group or manifest.nav_group,
                    "badge": navigation.badge,
                    "provenance": navigation.provenance,
                    "remoteEntry": manifest.remote_entry,
                    "sriHash": manifest.sri_hash,
                    "required_permissions": route.required_permissions,
                    **({"icon": navigation.icon} if navigation.icon is not None else {}),
                }
            )
    for number, prefix in enumerate(extension_spa_prefixes):
        endpoint = f"extension_spa_{number}"
        app.add_url_rule(
            prefix,
            endpoint=endpoint,
            view_func=serve_console_shell,
            methods=["GET"],
            strict_slashes=False,
        )
        app.add_url_rule(
            f"{prefix}/<path:extension_path>",
            endpoint=f"{endpoint}_deep_link",
            view_func=serve_console_shell,
            methods=["GET"],
            strict_slashes=False,
        )

    # Demo routes are only registered when ENABLE_DEMO=true
    if config.ENABLE_DEMO:

        @app.route("/demo", strict_slashes=False)
        @app.route("/demo/loan", strict_slashes=False)
        def index_demo(path=""):
            return send_from_directory(ui_path, "index.html")

    return app


def manage_pid_file():
    """
    Singleton Process Guard (Leak Prevention).
    Ensures only one instance of the Console API is running.
    """
    import os
    import sys

    import psutil

    # [Industrial Hardening]: Skip guard logic if we are the child process of the reloader.
    # Otherwise, we kill the parent process that just spawned us.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return

    pid_path = config.PROJECT_ROOT / ".aes" / "server.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if pid_path.exists():
        try:
            with open(pid_path) as f:
                old_pid_str = f.read().strip()
                if old_pid_str:
                    old_pid = int(old_pid_str)
                    if old_pid != os.getpid() and psutil.pid_exists(old_pid):
                        proc = psutil.Process(old_pid)
                        # Only kill if it's actually similar to us (python/app)
                        if "python" in proc.name().lower():
                            sys.stderr.write(
                                f"   [Guard] Found stale instance (PID: {old_pid}). "
                                "Terminating...\n"
                            )
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                proc.kill()
        except Exception as e:
            sys.stderr.write(f"   [Guard] PID cleanup warning: {e}\n")

    # Register current PID
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))

    # Cleanup on exit
    import atexit

    def cleanup_pid():
        if pid_path.exists():
            try:
                # Only remove if it's OUR pid
                should_unlink = False
                with open(pid_path) as check_f:
                    if check_f.read().strip() == str(os.getpid()):
                        should_unlink = True

                if should_unlink:
                    pid_path.unlink()
            except Exception as e:
                import sys

                sys.stderr.write(f"   [Guard] PID cleanup failed: {e}\n")
                sys.stderr.flush()

    atexit.register(cleanup_pid)


def run_server(host="127.0.0.1", port=5000, debug=False):
    """Entry point for the AES Console Server."""
    manage_pid_file()

    app = create_app()

    # [STABILITY HARDENING]: Exclude log and report directories from reloader
    # to prevent write-triggered feedback loops during evaluations.
    extra_files = []

    # Increase interval to 2s to avoid over-eager site-packages reloads
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        reloader_interval=2,
        threaded=True,
        extra_files=extra_files if debug else None,
    )


if __name__ == "__main__":
    run_server()
