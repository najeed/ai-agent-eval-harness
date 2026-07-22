"""
test_cumulative_registry.py

Industrial Verification Suite for the v1.3.0 Distributed Registry.
Ensures that the Core baseline is preserved and overlays are merged correctly.
"""

import json

import pytest

from eval_runner import config


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    """Ensure RegistryManager cache is cleanly reloaded before and after every test."""
    config.RegistryManager.reload()
    yield
    config.RegistryManager.reload()


def test_internal_baseline_loading():
    """Verify that the internal package baseline is the starting point."""
    registry = config.RegistryManager.get_resolved_registry()
    assert "shims" in registry
    assert "api" in registry["shims"]
    assert "git" in registry["shims"]

    # Check core constants
    assert registry["shims"]["git"]["resources"]["default_branch"] == "main"


def test_deep_merge_preserves_siblings(tmp_path, monkeypatch):
    """Verify that adding a key to a shim doesn't delete existing core keys."""
    # 1. Setup a .d folder in tmp_path (v1.4.0 structure)
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    # 2. Add an extension that modifies 'git'
    ext_file = d_dir / "01_enterprise_git.json"
    ext_content = {"shims": {"git": {"resources": {"enterprise_id": "ent_999"}}}}
    ext_file.write_text(json.dumps(ext_content))

    # 3. Patch config paths to use tmp_path
    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config._SHIM_REGISTRY_CACHE = None

    # 4. Reload and Verify
    config.RegistryManager.reload()
    resolved = config.RegistryManager.get_resolved_registry()

    git_res = resolved["shims"]["git"]["resources"]
    assert git_res["enterprise_id"] == "ent_999"
    # CRITICAL: Core 'default_branch' must still exist (Cumulative Merger)
    assert git_res["default_branch"] == "main"


def test_alphabetical_override_order(tmp_path, monkeypatch):
    """Verify that filenames starting with higher numbers/letters override lower ones."""
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    # File A (Lower Priority)
    file_a = d_dir / "01_first.json"
    file_a.write_text(json.dumps({"shims": {"api": {"resources": {"timeout": 10}}}}))

    # File B (Higher Priority)
    file_b = d_dir / "02_second.json"
    file_b.write_text(json.dumps({"shims": {"api": {"resources": {"timeout": 20}}}}))

    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config.RegistryManager.reload()
    resolved = config.RegistryManager.get_resolved_registry()

    assert resolved["shims"]["api"]["resources"]["timeout"] == 20


def test_project_root_files_are_ignored(tmp_path, monkeypatch):
    """Verify that legacy shim_resources.json in the root is NO LONGER LOADED."""
    # 1. Setup a .d folder (empty)
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    # 2. Setup a legacy file in the root
    root_file = tmp_path / "shim_resources.json"
    root_file.write_text(json.dumps({"shims": {"api": {"resources": {"legacy": True}}}}))

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)

    # 3. Resolve
    try:
        config.RegistryManager.reload()
        registry = config.RegistryManager.get_resolved_registry()

        # 4. Assert root file is NOT in the registry
        shims = registry.get("shims", {})
        assert "api" not in shims or "legacy" not in shims["api"]["resources"]
    finally:
        config.RegistryManager.reload()


def test_local_overlay_precedence(tmp_path, monkeypatch):
    """Verify that a 99_local.json in the .d folder wins over base extensions."""
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    # 01_base.json
    (d_dir / "01_base.json").write_text(
        json.dumps({"shims": {"api": {"resources": {"val": "base"}}}})
    )

    # 99_local.json
    (d_dir / "99_local.json").write_text(
        json.dumps({"shims": {"api": {"resources": {"val": "local"}}}})
    )

    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config._SHIM_REGISTRY_CACHE = None

    registry = config.RegistryManager.get_resolved_registry()
    assert registry["shims"]["api"]["resources"]["val"] == "local"


def test_env_var_final_veto(tmp_path, monkeypatch):
    """Verify that AES_SHIM_RESOURCES_JSON has ultimate precedence."""
    env_payload = json.dumps({"shims": {"api": {"resources": {"env_force": True}}}})
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", env_payload)

    config.RegistryManager.reload()
    resolved = config.RegistryManager.get_resolved_registry()

    assert resolved["shims"]["api"]["resources"]["env_force"] is True


def test_yaml_support_in_d_folder(tmp_path, monkeypatch):
    """Verify that YAML files in the .d folder are also merged."""
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    yaml_file = d_dir / "01_config.yaml"
    yaml_file.write_text("shims:\n  git:\n    resources:\n      yaml_check: true")

    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config.RegistryManager.reload()
    resolved = config.RegistryManager.get_resolved_registry()

    assert resolved["shims"]["git"]["resources"]["yaml_check"] is True


def test_malformed_file_handling(tmp_path, monkeypatch, caplog):
    """Verify that a single broken file in .d doesn't stop the whole registry."""
    d_dir = tmp_path / "shims.d"
    d_dir.mkdir()

    # Broken JSON
    (d_dir / "01_broken.json").write_text("{ broken: json }")
    # Valid JSON
    (d_dir / "02_valid.json").write_text(
        json.dumps({"shims": {"api": {"resources": {"valid": True}}}})
    )

    monkeypatch.setattr(config, "AES_CONFIG_DIR", tmp_path)
    config.RegistryManager.reload()
    resolved = config.RegistryManager.get_resolved_registry()

    # Valid file should still load
    assert resolved["shims"]["api"]["resources"]["valid"] is True

    # Check for warning in caplog
    assert "Failed to load configuration from shims.d/01_broken.json" in caplog.text
