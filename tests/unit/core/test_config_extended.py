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


def test_registry_manager_empty_missing_and_resolve_detailed_branches(tmp_path, monkeypatch):
    import json

    missing_internal = tmp_path / "missing_internal.json"
    missing_cfg_dir = tmp_path / "missing_cfg"
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", missing_internal)
    monkeypatch.setattr(config, "AES_CONFIG_DIR", missing_cfg_dir)
    monkeypatch.delenv("AES_SHIM_RESOURCES_JSON", raising=False)
    config._SHIM_REGISTRY_CACHE = None

    # 1. Missing internal & config dir in both get_resolved_registry and resolve_detailed
    reg = config.RegistryManager.get_resolved_registry()
    assert reg == {"shims": {}, "forensics": {}}
    report_missing = config.RegistryManager.resolve_detailed()
    assert report_missing.errors == []

    # 2. Empty dict internal & empty config file in get_resolved_registry
    empty_internal = tmp_path / "empty_internal.json"
    empty_internal.write_text("{}", encoding="utf-8")
    cfg_dir = tmp_path / "cfg"
    (cfg_dir / "shims.d").mkdir(parents=True)
    (cfg_dir / "shims.d" / "empty.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", empty_internal)
    monkeypatch.setattr(config, "AES_CONFIG_DIR", cfg_dir)
    config._SHIM_REGISTRY_CACHE = None
    reg2 = config.RegistryManager.get_resolved_registry()
    assert reg2 == {"shims": {}, "forensics": {}}

    # 3. resolve_detailed: non-dict internal, corrupt internal, YAML routing without mappings,
    #    non-dict discovery file, and non-dict AES_SHIM_RESOURCES_JSON
    bad_internal = tmp_path / "list_internal.json"
    bad_internal.write_text("[]", encoding="utf-8")
    (cfg_dir / "routing").mkdir(parents=True)
    (cfg_dir / "routing" / "routes.yaml").write_text("api: /v1\n", encoding="utf-8")
    (cfg_dir / "shims.d" / "list.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", bad_internal)
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", "[]")
    report_err = config.RegistryManager.resolve_detailed()
    assert any(e.error_type == "malformed_file" for e in report_err.errors)
    assert any(e.error_type == "invalid_env_override" for e in report_err.errors)
    assert report_err.entries["routing.mappings.api"].effective_value == "/v1"

    corrupt_internal = tmp_path / "corrupt_internal.json"
    corrupt_internal.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", corrupt_internal)
    report_parse = config.RegistryManager.resolve_detailed()
    assert any(e.error_type == "parse_error" for e in report_parse.errors)

    null_internal = tmp_path / "null_internal.json"
    null_internal.write_text("null", encoding="utf-8")
    (cfg_dir / "shims.d" / "null.json").write_text("null", encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", null_internal)
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", json.dumps({"routing": {"mappings": "scalar"}}))
    report_null = config.RegistryManager.resolve_detailed()
    assert report_null.entries["routing.mappings.api"].effective_value == "/v1"

    valid_internal = tmp_path / "valid_internal.json"
    valid_internal.write_text(json.dumps({"shims": {"api": {"timeout": 5}}}), encoding="utf-8")
    monkeypatch.setattr(config, "SHIM_RESOURCES_INTERNAL_PATH", valid_internal)
    monkeypatch.setattr(config, "AES_CONFIG_DIR", missing_cfg_dir)
    monkeypatch.delenv("AES_SHIM_RESOURCES_JSON", raising=False)
    report_ok = config.RegistryManager.resolve_detailed()
    assert report_ok.entries["shims.api.timeout"].effective_value == 5
