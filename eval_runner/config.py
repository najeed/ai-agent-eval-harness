import os
from pathlib import Path

# --- Platform & Roots (v1.2.3-ULTIMATE) ---
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# --- Engine Configuration ---
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")
EVAL_MAX_TURNS = int(os.getenv("EVAL_MAX_TURNS", "5"))
MAX_ENGINE_ATTEMPTS = int(os.getenv("MAX_ENGINE_ATTEMPTS", "50"))
DEFAULT_INDUSTRY = os.getenv("DEFAULT_INDUSTRY", "telecom")

# --- Logging Configuration ---
RUN_LOG_DIR = Path(os.getenv("RUN_LOG_DIR", "runs"))
RUN_LOG_PER_RUN = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
RUN_LOG_MASTER = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
RUN_LOG_ROTATE_COUNT = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))

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
You are an objective judge. Rate the similarity between the 'Expected Outcome' and the 'Agent Summary' on a scale of 0.0 to 1.0.
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")
ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-beta")

# --- Metric Thresholds & Defaults ---
CLARITY_MIN_LENGTH = int(os.getenv("CLARITY_MIN_LENGTH", "10"))
LATENCY_DECAY_PER_HOP = float(os.getenv("LATENCY_DECAY_PER_HOP", "0.2"))
REFUSAL_KEYWORDS = os.getenv("REFUSAL_KEYWORDS", "cannot,unable,refuse,policy,against,not allowed,sorry").split(",")

# --- Reporter Configuration ---
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
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
