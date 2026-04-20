"""
test_secret_redaction.py

Industrial Verification Suite for the v1.3.0 Secret Redaction Engine.
Ensures that sensitive credentials are masked in traces while preserving forensic hashes.
"""

import hashlib
import json

from eval_runner import config
from eval_runner.tool_sandbox import ToolSandbox


def test_recursive_redaction_logic():
    """Verify that the RegistryManager correctly redacts sensitive keys at any depth."""
    raw_data = {
        "shims": {
            "api": {
                "resources": {
                    "api_key": "S3CR3T_123",
                    "timeout": 30,
                    "tokens": ["tok_a", "tok_b"],
                    "nested": {"db_password": "trust_no_one", "public_id": "pub_999"},
                }
            }
        },
        "global_secret": "top_secret_value",
    }

    redacted = config.RegistryManager._redact_sensitive_data(raw_data)

    # 1. Broad keys
    assert redacted["global_secret"] == "[REDACTED]"

    # 2. Shim resources
    api_res = redacted["shims"]["api"]["resources"]
    assert api_res["api_key"] == "[REDACTED]"
    assert api_res["timeout"] == 30  # Preserved
    assert api_res["tokens"] == "[REDACTED]"  # 'token' substring match

    # 3. Deeply nested
    assert api_res["nested"]["db_password"] == "[REDACTED]"
    assert api_res["nested"]["public_id"] == "pub_999"  # Preserved


def test_provisioning_hash_integrity(tmp_path, monkeypatch):
    """Verify that the forensic hash is based on RAW data, not redacted data."""
    # 1. Setup a .d folder with a secret extension (v1.4.0 structure)
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()
    secret_value = "SUPER_SECRET_KEY"
    content = {"shims": {"api": {"resources": {"api_key": secret_value}}}}
    (d_dir / "99_secrets.json").write_text(json.dumps(content))

    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config._SHIM_REGISTRY_CACHE = None

    # 2. Initialize Sandbox
    sandbox = ToolSandbox(scenario={"id": "test_hash"})

    # 3. Verify SANITIZED snapshot in scenario
    snapshot = sandbox.scenario["environmental_snapshot"]
    assert snapshot["shims"]["api"]["resources"]["api_key"] == "[REDACTED]"

    # 4. Verify HASH is from the RAW data
    # Manually calculate hash of raw merged registry
    full_registry = config.RegistryManager.get_resolved_registry()
    raw_json = json.dumps(full_registry, sort_keys=True)
    expected_hash = hashlib.sha256(raw_json.encode()).hexdigest()

    assert sandbox.scenario["metadata"]["provisioning_hash"] == expected_hash

    # CRITICAL: Confirm the hash is NOT based on redacted data
    redacted_json = json.dumps(snapshot, sort_keys=True)
    redacted_hash = hashlib.sha256(redacted_json.encode()).hexdigest()
    assert sandbox.scenario["metadata"]["provisioning_hash"] != redacted_hash


def test_redaction_keywords_coverage():
    """Verify that all industrial secret keywords are covered."""
    keywords = ["token", "secret", "password", "key", "access_key", "bearer", "private_key"]
    data = {kw: "sensitive" for kw in keywords}
    data["public_url"] = "https://example.com"

    redacted = config.RegistryManager._redact_sensitive_data(data)

    for kw in keywords:
        assert redacted[kw] == "[REDACTED]", f"Keyword '{kw}' was not redacted"

    assert redacted["public_url"] == "https://example.com"


def test_redaction_case_insensitivity():
    """Verify that redaction is case-insensitive for key names."""
    data = {"API_KEY": "secret1", "SecretToken": "secret2", "dbPassword": "secret3"}

    redacted = config.RegistryManager._redact_sensitive_data(data)
    assert redacted["API_KEY"] == "[REDACTED]"
    assert redacted["SecretToken"] == "[REDACTED]"
    assert redacted["dbPassword"] == "[REDACTED]"
