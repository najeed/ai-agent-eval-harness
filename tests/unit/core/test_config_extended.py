from unittest.mock import MagicMock, patch

from eval_runner import config


def test_get_project_version_failure(tmp_path):
    """Verify version fallback when pyproject.toml is missing or malformed."""
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        # File missing
        assert config._get_project_version() == "1.4.0"

        # File malformed
        toml = tmp_path / "pyproject.toml"
        toml.write_text("invalid = {", encoding="utf-8")
        assert config._get_project_version() == "1.4.0"


def test_get_safe_tmp_dir_fallback(tmp_path, monkeypatch):
    """Verify fallback to system temp dir when project root is read-only."""
    from pathlib import Path as RealPath

    orig_mkdir = RealPath.mkdir

    def mocked_mkdir(self, *args, **kwargs):
        # Fail ONLY for the project-local .tmp directory
        if self.name == ".tmp":
            raise PermissionError("Read only")
        return orig_mkdir(self, *args, **kwargs)

    with patch("pathlib.Path.mkdir", mocked_mkdir):
        config._TEMP_DIR_CACHE = None  # Clear cache
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

        tmp = config.get_safe_tmp_dir()
        # Fallback should succeed (it won't have .tmp in path, it will have aes_eval)
        assert "aes_eval" in str(tmp)


def test_registry_manager_deep_merge_conflict():
    """Verify that deep_merge handles type conflicts by favoring the overlay."""
    base = {"key": {"nested": 1}}
    overlay = {"key": "new_value"}  # Conflict: dict vs str

    result = config.RegistryManager._deep_merge(base, overlay)
    assert result["key"] == "new_value"


def test_registry_manager_load_baseline_failure(monkeypatch, capsys):
    """Verify loading warning when internal baseline is malformed."""
    with patch("eval_runner.config.SHIM_RESOURCES_INTERNAL_PATH") as mock_path:
        mock_path.exists.return_value = True
        # Open returns malformed JSON
        with patch("builtins.open", MagicMock(side_effect=Exception("Disk Error"))):
            config._SHIM_REGISTRY_CACHE = None
            config.RegistryManager.get_resolved_registry()

    captured = capsys.readouterr()
    # Note: stderr/stdout output from print() in get_resolved_registry
    assert "Failed to load internal baseline" in captured.out


def test_registry_manager_env_override_failure(monkeypatch, capsys):
    """Verify warning when AES_SHIM_RESOURCES_JSON is malformed."""
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", "{ malformed")
    config._SHIM_REGISTRY_CACHE = None
    config.RegistryManager.get_resolved_registry()

    captured = capsys.readouterr()
    assert "Failed to parse AES_SHIM_RESOURCES_JSON" in captured.out


def test_get_forensic_policy_env_overrides(monkeypatch):
    """Verify that environment variables take precedence in forensic policy."""
    monkeypatch.setenv("FORENSIC_ALLOWED_EXTS", ".dat,.bin")
    monkeypatch.setenv("FORENSIC_MANDATORY_PATTERNS", "must_have_.*")
    monkeypatch.setenv("FORENSIC_MAX_ARTIFACT_SIZE", "1024")

    policy = config.get_forensic_policy()
    assert policy["extensions"] == ".dat,.bin"
    assert policy["mandatory_patterns"] == "must_have_.*"
    assert policy["max_artifact_size"] == 1024


def test_sys_path_insertion():
    """Verify sys.path insertion logic when PROJECT_ROOT is missing from sys.path."""
    import importlib
    import sys

    orig_path = sys.path.copy()
    # Case-insensitive removal of any reference to project root
    sys.path = [p for p in sys.path if "ai-agent-eval-harness" not in p.lower()]
    try:
        importlib.reload(config)
        assert any(str(config.PROJECT_ROOT).lower() == p.lower() for p in sys.path)
    finally:
        sys.path = orig_path


def test_debug_paths(monkeypatch):
    """Verify stderr debug path output logic."""
    import importlib

    mock_stderr = MagicMock()
    with patch("sys.stderr.write", mock_stderr):
        monkeypatch.setenv("DEBUG_PATHS", "true")
        importlib.reload(config)
        assert mock_stderr.call_count >= 2

    mock_stderr.reset_mock()
    with patch("sys.stderr.write", mock_stderr):
        monkeypatch.setenv("DEBUG_PATHS", "false")
        importlib.reload(config)
        mock_stderr.assert_not_called()


def test_double_checked_locking():
    """Verify double-checked locking behavior in resolved registry caching."""
    # Reset internal state to trigger resolution
    config._SHIM_REGISTRY_CACHE = None

    mock_lock = MagicMock()

    def mock_enter(*args, **kwargs):
        # Populate cache right after lock entry to test cache hit inside the lock
        config._SHIM_REGISTRY_CACHE = {"double": "checked"}
        return MagicMock()

    mock_lock.__enter__ = mock_enter

    with patch("eval_runner.config._REGISTRY_LOCK", mock_lock):
        res = config.RegistryManager.get_resolved_registry()
        assert res == {"double": "checked"}


def test_registry_manager_discovery_scenarios(tmp_path, monkeypatch, caplog):
    """Test various discovery path outcomes (missing files, malformed formats, yaml types)."""
    # 1. Malformed internal baseline
    internal_baseline = tmp_path / "internal.json"
    internal_baseline.write_text("invalid", encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", internal_baseline)
    config._SHIM_REGISTRY_CACHE = None

    # 2. Non-existent AES_CONFIG_DIR
    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path / "nonexistent")
    res = config.RegistryManager.get_resolved_registry()
    assert isinstance(res, dict)

    # 3. Valid directory with mixed formats, malformed inputs, and custom affinities
    aes_dir = tmp_path / "aes_config"
    aes_dir.mkdir()
    monkeypatch.setattr(config, "AES_CONFIG_DIR", aes_dir)

    # Corrupt routing manifest
    routing_dir = aes_dir / "routing"
    routing_dir.mkdir()
    manifest = routing_dir / "manifest.json"
    manifest.write_text("{invalid_json", encoding="utf-8")

    # Corrupt routing extension
    routing_d = aes_dir / "routing.d"
    routing_d.mkdir()
    ext_json = routing_d / "ext.json"
    ext_json.write_text("{invalid_json", encoding="utf-8")

    # Corrupt custom affinity file
    other_dir = aes_dir / "other"
    other_dir.mkdir()
    conf_json = other_dir / "conf.json"
    conf_json.write_text("{invalid_json", encoding="utf-8")

    # Valid YAML file mapping (with shims.d affinity)
    shims_d = aes_dir / "shims.d"
    shims_d.mkdir()
    shim_yaml = shims_d / "shim.yaml"
    shim_yaml.write_text("shims:\n  my_shim: {}\n", encoding="utf-8")

    # Valid YML/YAML file without affinity key in root
    shim_yml = shims_d / "other_shim.yaml"
    shim_yml.write_text("other_shim_details: {}\n", encoding="utf-8")

    # Valid routing config with flat mapping (no mappings key)
    routing_d_ok = routing_d / "ok.json"
    routing_d_ok.write_text('{"some_agent": {"endpoint": "url"}}', encoding="utf-8")

    # Valid env override JSON
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", '{"env_override_key": "env_override_val"}')

    import logging

    with caplog.at_level(logging.WARNING):
        config._SHIM_REGISTRY_CACHE = None
        resolved = config.RegistryManager.get_resolved_registry()

    # Verify error / warning logs are present
    assert any("Failed to load routing manifest" in record.message for record in caplog.records)
    assert any("Failed to load routing extension" in record.message for record in caplog.records)
    assert any("Failed to load configuration" in record.message for record in caplog.records)

    # Verify affinity mappings merged correctly
    assert "shims" in resolved
    assert "my_shim" in resolved["shims"]
    assert "other_shim_details" in resolved["shims"]
    assert "routing" in resolved
    assert "mappings" in resolved["routing"]
    assert resolved["routing"]["mappings"]["some_agent"] == {"endpoint": "url"}
    assert resolved["env_override_key"] == "env_override_val"


def test_get_sanitized_registry():
    """Verify redacting of sensitive keys recursively."""
    config._SHIM_REGISTRY_CACHE = {
        "shims": {
            "test_shim": {
                "api_key": "secret_value_123",
                "non_sensitive": "public_value",
                "nested_list": [{"token": "jwt_token"}, "regular_item"],
            }
        }
    }
    sanitized = config.RegistryManager.get_sanitized_registry()
    assert sanitized["shims"]["test_shim"]["api_key"] == "[REDACTED]"
    assert sanitized["shims"]["test_shim"]["non_sensitive"] == "public_value"
    assert sanitized["shims"]["test_shim"]["nested_list"][0]["token"] == "[REDACTED]"
    assert sanitized["shims"]["test_shim"]["nested_list"][1] == "regular_item"


def test_registry_manager_reload():
    """Verify cache reload logic."""
    config._SHIM_REGISTRY_CACHE = {"temporary": "cache"}
    res = config.RegistryManager.reload()
    assert "temporary" not in res


def test_get_shim_config_nested_resources():
    """Verify fallback get_shim_config works when resources block is double-nested."""
    config._SHIM_REGISTRY_CACHE = {
        "shims": {"test_shim": {"resources": {"resources": {"key": "val"}}}}
    }
    assert config.get_shim_config("test_shim") == {"key": "val"}


def test_get_safe_tmp_dir_caching_and_emergency_fallback(monkeypatch, caplog):
    """Verify local cache hit and critical fallback if primary/secondary mkdir both fail."""
    from pathlib import Path

    config._TEMP_DIR_CACHE = Path("/some/cached/path")
    assert config.get_safe_tmp_dir() == Path("/some/cached/path")

    config._TEMP_DIR_CACHE = None

    def raise_error(*args, **kwargs):
        raise OSError("Permission denied")

    with patch("pathlib.Path.write_text", raise_error):
        with patch("pathlib.Path.mkdir", raise_error):
            import logging

            with caplog.at_level(logging.CRITICAL):
                emergency = config.get_safe_tmp_dir()
                assert emergency == Path(".")
                assert any(
                    "System temp directory unreachable" in record.message
                    for record in caplog.records
                )


def test_get_forensic_policy_empty_lists(monkeypatch):
    """Verify default extension and pattern injection when inputs are completely empty."""
    monkeypatch.delenv("FORENSIC_ALLOWED_EXTS", raising=False)
    monkeypatch.delenv("FORENSIC_MANDATORY_PATTERNS", raising=False)
    config._SHIM_REGISTRY_CACHE = {"forensics": {}}
    policy = config.get_forensic_policy()
    assert ".jsonl" in policy["extensions"]
    assert "audit_.*\\.json" in policy["mandatory_patterns"]


def test_get_routing_strategy_extra(monkeypatch):
    """Verify get_routing_strategy returns correct configured value."""
    monkeypatch.setenv("EVAL_ROUTING_STRATEGY", "Priority_Standard_Custom")
    assert config.get_routing_strategy() == "Priority_Standard_Custom"
