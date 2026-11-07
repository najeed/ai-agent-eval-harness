"""Credential and secret sanitization for traces, manifests, and certificate APIs."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "auth",
        "token",
        "bearer_token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "private_key",
        "client_secret",
        "password",
        "passwd",
    }
)

SENSITIVE_KEY_SUFFIXES = ("_token", "_secret", "_password", "_private_key", "_api_key", "_apikey")


def redact_credential_string(s: str) -> str:
    """Redacts standard secret patterns (JWT, OpenAI, AWS, GitHub, Bearer tokens)."""
    s = re.sub(r"ey[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]", s)
    s = re.sub(r"sk-[a-zA-Z0-9]{32,}", "[REDACTED_KEY]", s)
    s = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", s)
    s = re.sub(r"gh[po]_[a-zA-Z0-9]{36,}", "[REDACTED_GITHUB_TOKEN]", s)
    s = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", s)
    return s


def sanitize_credentials(obj: Any) -> Any:
    """Recursively redacts credentials, secrets, tokens, and authority headers."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            k_str = str(k)
            k_lower = k_str.lower()
            if k_lower == "headers" and isinstance(v, dict):
                sanitized[k] = {hk: "[REDACTED]" for hk in v}
            elif k_lower in SENSITIVE_CREDENTIAL_KEYS or any(
                k_lower.endswith(sfx) for sfx in SENSITIVE_KEY_SUFFIXES
            ):
                if isinstance(v, dict):
                    sanitized[k] = {sk: "[REDACTED]" for sk in v}
                else:
                    sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_credentials(v)
        return sanitized
    elif isinstance(obj, list):
        return [sanitize_credentials(v) for v in obj]
    elif isinstance(obj, str):
        return redact_credential_string(obj)
    return obj
