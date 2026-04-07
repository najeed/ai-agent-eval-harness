import os
import json
import yaml
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Absolute Authoritative Project Root (supports environment override for test isolation)
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(Path(__file__).parent.parent))).resolve()


def _get_project_version() -> str:
    """Authoritative version resolver (Single Source of Truth from pyproject.toml)."""
    try:
        from pathlib import Path
        import tomllib

        target = PROJECT_ROOT / "pyproject.toml"
        if target.exists():
            with open(target, "rb") as f:
                return tomllib.load(f).get("project", {}).get("version", "1.3.0")
    except (FileNotFoundError, AttributeError, KeyError, ImportError):
        pass
    return "1.3.0"


VERSION = _get_project_version()
_TEMP_DIR_CACHE = None


def get_safe_tmp_dir() -> Path:
    """
    Returns a writable temporary directory within the PROJECT_ROOT.
    Ensures environment portability by avoiding system-wide absolute paths.
    """
    global _TEMP_DIR_CACHE
    if _TEMP_DIR_CACHE:
        return _TEMP_DIR_CACHE

    # 1. Primary path: Git-ignored .tmp directory within the project
    primary = PROJECT_ROOT / ".tmp"

    try:
        if not primary.exists():
            primary.mkdir(parents=True, exist_ok=True)

        # Verify write permission
        test_file = primary / ".aes_perm_test"
        test_file.write_text("perm_test", encoding="utf-8")
        test_file.unlink()

        _TEMP_DIR_CACHE = primary
        return primary
    except Exception:
        # 2. Fallback to OS default if project root is read-only (unlikely in dev)
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "aes_eval"
        fallback.mkdir(parents=True, exist_ok=True)
        _TEMP_DIR_CACHE = fallback
        return fallback


LOG_REDIRECT_PATH = get_safe_tmp_dir() / "tool_logs"

# --- Engine Configuration ---
AGENT_API_URLS = [
    url.strip()
    for url in os.getenv(
        "AGENT_API_URLS", os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")
    ).split(",")
]
# Legacy support for single-endpoint modules
AGENT_API_URL = AGENT_API_URLS[0] if AGENT_API_URLS else "http://localhost:5001/execute_task"
EVAL_MAX_TURNS = int(os.getenv("EVAL_MAX_TURNS", "10"))
MAX_ENGINE_ATTEMPTS = int(os.getenv("MAX_ENGINE_ATTEMPTS", "50"))
DEFAULT_INDUSTRY = os.getenv("DEFAULT_INDUSTRY", "telecom")

# --- Logging Configuration ---
RUN_LOG_DIR = (PROJECT_ROOT / os.getenv("RUN_LOG_DIR", "runs")).resolve()
RUN_LOG_PER_RUN = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
RUN_LOG_MASTER = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
RUN_LOG_ROTATE_COUNT = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))
RUN_LOG_MASTER_LIMIT = int(os.getenv("RUN_LOG_MASTER_LIMIT", "300"))

# --- Plugin Configuration ---
PLUGIN_TIMEOUT = float(os.getenv("PLUGIN_TIMEOUT", "5.0"))

# --- Session & Forking ---
MAX_FORK_DEPTH = int(os.getenv("MAX_FORK_DEPTH", "3"))
MAX_FORK_BREADTH = int(os.getenv("MAX_FORK_BREADTH", "5"))

# --- LLM Judge Layer ---
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "ollama").lower()
JUDGE_MODEL = os.getenv("JUDGE_MODEL")  # Specific model for the judge

LUNA_JUDGE_PROMPT = os.getenv(
    "LUNA_JUDGE_PROMPT",
    """
You are an objective judge. Rate the similarity between the 'Expected Outcome' and the 'Agent Summary' on a scale of 0.0 to 1.0.  # noqa: E501
1.0 means they are semantically equivalent.
0.0 means they are completely different.

Expected Outcome: {expected_outcome}
Agent Summary: {agent_summary}

Return ONLY a single float between 0.0 and 1.0.
""",
)
LUNA_JUDGE_TEMPERATURE = float(os.getenv("LUNA_JUDGE_TEMPERATURE", "0.0"))

# --- Provider Defaults ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", f"{OLLAMA_HOST}/api/chat")
AUTOGEN_API_URL = os.getenv("AUTOGEN_API_URL", "http://localhost:5002/execute_task")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-pro")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-4-6-sonnet")
ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1/models"
)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.20-beta-0309")

# --- Metric Thresholds & Defaults ---
CLARITY_MIN_LENGTH = int(os.getenv("CLARITY_MIN_LENGTH", "10"))
LATENCY_DECAY_PER_HOP = float(os.getenv("LATENCY_DECAY_PER_HOP", "0.2"))
REFUSAL_KEYWORDS = os.getenv(
    "REFUSAL_KEYWORDS", "cannot,unable,refuse,policy,against,not allowed,sorry"
).split(",")

# --- Reporter Configuration ---
REPORTS_DIR = (PROJECT_ROOT / os.getenv("REPORTS_DIR", "reports")).resolve()
TRAJECTORIES_DIR = REPORTS_DIR / "trajectories"
HTML_REPORTS_DIR = REPORTS_DIR / "html"

MERMAID_CDN = os.getenv("MERMAID_CDN", "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js")
MERMAID_THEME = os.getenv("MERMAID_THEME", "dark")

# HTML Report Styling
HTML_BG_COLOR = os.getenv("HTML_BG_COLOR", "#0f172a")
HTML_CARD_COLOR = os.getenv("HTML_CARD_COLOR", "#1e293b")
HTML_ACCENT_COLOR = os.getenv("HTML_ACCENT_COLOR", "#38bdf8")
HTML_SUCCESS_COLOR = os.getenv("HTML_SUCCESS_COLOR", "#10b981")
HTML_FAILURE_COLOR = os.getenv("HTML_FAILURE_COLOR", "#ef4444")
HTML_TEXT_COLOR = os.getenv("HTML_TEXT_COLOR", "#f1f5f9")
HTML_SUB_TEXT_COLOR = os.getenv("HTML_SUB_TEXT_COLOR", "#94a3b8")

# --- Sandbox Security ---
SANDBOX_VFS_PREFIX = os.getenv("SANDBOX_VFS_PREFIX", "vfs:/")
SHELL_METABLOCKS = os.getenv("SHELL_METABLOCKS", ";,|,&&,`,$,(,),>,<,&").split(",")
GLOBAL_ENABLED_SHIMS = os.getenv("GLOBAL_ENABLED_SHIMS", "*").split(",")

# --- Timeouts ---
DEFAULT_ADAPTER_TIMEOUT = int(os.getenv("DEFAULT_ADAPTER_TIMEOUT", "30"))
DEFAULT_LLM_TIMEOUT = int(os.getenv("DEFAULT_LLM_TIMEOUT", "10"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))

# --- UI & Demo Persistence ---
ENABLE_DEMO = os.getenv("ENABLE_DEMO", "true").lower() == "true"

# --- Security R3 Best Practices ---
# Dashboard API Key for sensitive execution.
# REQUIRED for production. If not set, protected routes will return 501.
# See: docs/guides/07_SECURITY_AND_AUTHENTICATION.md for setup instructions.
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

# Industrial Feature Toggles (v1.2.4)
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"

# --- Shim Registry Manager (v1.3.0 Cumulative Mode) ---
SHIM_RESOURCES_INTERNAL_PATH = Path(__file__).parent / "resources" / "shim_resources.json"
SHIM_RESOURCES_D_DIR = PROJECT_ROOT / "shim_resources.d"
_SHIM_REGISTRY_CACHE = None


class RegistryManager:
    """Manages the lifecycle and hygiene of the authoritative shim configuration manifest."""

    @classmethod
    def _redact_sensitive_data(cls, data):
        """Recursively redact sensitive keys in a dictionary or list."""
        sensitive_keywords = {
            "api_key",
            "token",
            "secret",
            "password",
            "key",
            "access_key",
            "bearer",
            "private_key",
        }

        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                # Check if key is sensitive (case-insensitive substring match)
                if any(kw in k.lower() for kw in sensitive_keywords):
                    new_dict[k] = "[REDACTED]"
                else:
                    new_dict[k] = cls._redact_sensitive_data(v)
            return new_dict
        elif isinstance(data, list):
            return [cls._redact_sensitive_data(item) for item in data]
        return data

    @classmethod
    def get_sanitized_registry(cls):
        """Returns a version of the resolved registry with sensitive data redacted."""
        registry = cls.get_resolved_registry()
        return cls._redact_sensitive_data(registry)

    @staticmethod
    def get_resolved_registry() -> dict:
        """Loads and merges all registry sources (Internal -> Cumulative .d Folder -> Env Overrides)."""
        global _SHIM_REGISTRY_CACHE
        if _SHIM_REGISTRY_CACHE is not None:
            return _SHIM_REGISTRY_CACHE

        registry = {"shims": {}}

        # 1. Internal Package Baseline (Sanctioned Core)
        if SHIM_RESOURCES_INTERNAL_PATH.exists():
            try:
                with open(SHIM_RESOURCES_INTERNAL_PATH) as f:
                    content = json.load(f)
                    if content:
                        registry = RegistryManager._deep_merge(registry, content)
            except Exception as e:
                print(f"      [Config] Warning: Failed to load internal baseline: {e}")

        # 2. Distributed Registry Extensions (shim_resources.d/)
        # This is now the ONLY location for project and environment overrides.
        if SHIM_RESOURCES_D_DIR.exists() and SHIM_RESOURCES_D_DIR.is_dir():
            # Alphabetical sort ensures deterministic override priority (e.g., 99_local > 01_)
            paths = sorted(list(SHIM_RESOURCES_D_DIR.glob("*.json")) + list(SHIM_RESOURCES_D_DIR.glob("*.yaml")))
            for path in paths:
                try:
                    with open(path) as f:
                        ext = yaml.safe_load(f) if path.suffix in [".yaml", ".yml"] else json.load(f)
                        if ext:
                            registry = RegistryManager._deep_merge(registry, ext)
                except Exception as e:
                    print(f"      [Config] Warning: Failed to load extension from {path.name}: {e}")

        # 3. Environment Overrides (Ultimate Authority)
        env_json = os.getenv("AES_SHIM_RESOURCES_JSON")
        if env_json:
            try:
                env_override = json.loads(env_json)
                registry = RegistryManager._deep_merge(registry, env_override)
            except Exception as e:
                print(f"      [Config] Warning: Failed to parse AES_SHIM_RESOURCES_JSON: {e}")

        _SHIM_REGISTRY_CACHE = registry
        return registry

    @staticmethod
    def reload():
        """Clears the internal cache, forcing a re-load of the registry state."""
        global _SHIM_REGISTRY_CACHE
        _SHIM_REGISTRY_CACHE = None
        return RegistryManager.get_resolved_registry()

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        """Performs a nested merge of configuration dictionaries."""
        import copy
        result = copy.deepcopy(base)
        for k, v in overlay.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = RegistryManager._deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(v)
        return result


def get_shim_config(shim_name: str) -> dict:
    """Standard protocol for shims to retrieve their environmental state from the registry."""
    registry = RegistryManager.get_resolved_registry()
    shim_def = registry.get("shims", {}).get(shim_name, {})
    return shim_def.get("resources", {})


# Throttle between agent turns (seconds) to prevent resource exhaustion
# and satisfy rate-limiting requirements in sensitive industrial sectors.
EVAL_TURN_THROTTLE = float(os.getenv("EVAL_TURN_THROTTLE", "0.0"))
