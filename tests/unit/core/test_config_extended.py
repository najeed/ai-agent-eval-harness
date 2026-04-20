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
        if ".tmp" in str(self):
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
