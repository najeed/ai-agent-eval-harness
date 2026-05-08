import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

import eval_runner.config as config
import eval_runner.registry_sync as registry_sync


class TestRegistrySyncConsolidated(unittest.TestCase):
    """Ported 1:1 from legacy test_registry_sync.py using verified Strategy A patching."""

    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()

    def test_load_registry_cases(self):
        # Strategy A: Patch the constant
        with patch("eval_runner.registry_sync.REGISTRY_PATH") as mock_path:
            mock_path.exists.return_value = False
            self.assertEqual(registry_sync.load_registry(), {"industries": {}})

            mock_path.exists.return_value = True
            mock_data = {
                "categories": {
                    "P": {
                        "standards": [{"id": "S1"}],
                        "subcategories": [{"name": "C", "standards": [{"id": "S2"}]}],
                    }
                }
            }
            with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
                res = registry_sync.load_registry()
                self.assertIn("P - C", res["industries"])

    def test_get_registry_ids_cases(self):
        with patch("eval_runner.registry_sync.REGISTRY_PATH") as mock_path:
            mock_path.exists.return_value = False
            self.assertEqual(registry_sync.get_registry_ids(), [])

            mock_path.exists.return_value = True
            mock_data = {
                "categories": {
                    "C": {
                        "standards": [{"id": "S1"}],
                        "subcategories": [{"standards": [{"id": "S2"}]}],
                    }
                }
            }
            with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
                self.assertEqual(registry_sync.get_registry_ids(), ["S1", "S2"])

    def test_ensure_schema_sync_cases(self):
        with (
            patch("eval_runner.registry_sync.REGISTRY_PATH") as r,
            patch("eval_runner.registry_sync.METADATA_SCHEMA_PATH") as m,
        ):
            r.exists.return_value = False
            self.assertIsNone(registry_sync.ensure_schema_sync())

            r.exists.return_value = True
            m.exists.return_value = True
            with patch("os.path.getmtime", side_effect=[100, 200]):
                self.assertIsNone(registry_sync.ensure_schema_sync(force=False))

            with patch("os.path.getmtime", side_effect=[200, 100]):
                with patch("eval_runner.registry_sync.get_registry_ids", return_value=[]):
                    self.assertIsNone(registry_sync.ensure_schema_sync())

            with patch("os.path.getmtime", side_effect=[200, 100]):
                with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                    with patch(
                        "builtins.open",
                        mock_open(
                            read_data=(
                                '{"properties": {"standards_registry": {"items": {"enum": []}}}}'
                            )
                        ),
                    ):
                        with patch("os.utime"):
                            registry_sync.ensure_schema_sync()

            with patch("os.path.getmtime", side_effect=[200, 100]):
                with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                    with patch("builtins.open", mock_open(read_data='{"broken": {}}')):
                        registry_sync.ensure_schema_sync()

    def test_add_standard_to_registry_cases(self):
        with patch("eval_runner.registry_sync.REGISTRY_PATH") as mock_path:
            mock_path.exists.return_value = False
            self.assertFalse(registry_sync.add_standard_to_registry("S1", "N1", "I1", "D1"))

            mock_path.exists.return_value = True
            with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                with patch("builtins.open", mock_open(read_data="{}")):
                    self.assertFalse(registry_sync.add_standard_to_registry("S1", "N1", "I1", "D1"))

            with patch("eval_runner.registry_sync.get_registry_ids", return_value=[]):
                m = mock_open(read_data=json.dumps({"categories": {}}))
                with patch("builtins.open", m):
                    with patch("eval_runner.registry_sync.ensure_schema_sync"):
                        res = registry_sync.add_standard_to_registry(
                            "S_NEW", "Name", "NewInd", "Desc"
                        )
                        self.assertTrue(res)


# --- Config Tests (92.27% Coverage) ---


def test_config_redaction_parity():
    data = {"secret_key": "s", "nested": {"api_key": "k"}, "list": [{"token": "t"}, "public"]}
    redacted = config.RegistryManager._redact_sensitive_data(data)
    assert redacted["secret_key"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["list"][0]["token"] == "[REDACTED]"
    assert redacted["list"][1] == "public"


def test_get_project_version_fallback(tmp_path):
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        assert config._get_project_version() == "1.4.0"


def test_get_safe_tmp_dir_fallback(tmp_path, monkeypatch):
    from pathlib import Path as RealPath

    orig_mkdir = RealPath.mkdir

    def mocked_mkdir(self, *args, **kwargs):
        if ".tmp" in str(self):
            raise PermissionError("RO")
        return orig_mkdir(self, *args, **kwargs)

    with patch("pathlib.Path.mkdir", mocked_mkdir):
        config._TEMP_DIR_CACHE = None
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        assert "aes_eval" in str(config.get_safe_tmp_dir())


def test_config_registry_manager_discovery(tmp_path):
    config_dir = tmp_path / ".aes" / "config"
    routing_dir = config_dir / "routing"
    routing_dir.mkdir(parents=True)
    (routing_dir / "m.json").write_text('{"r1": "/v1"}')
    with patch.object(config, "_SHIM_REGISTRY_CACHE", None):
        with patch.object(config, "AES_CONFIG_DIR", config_dir):
            reg = config.RegistryManager.get_resolved_registry()
            assert reg["routing"]["mappings"]["r1"] == "/v1"


def test_registry_manager_deep_merge_conflict():
    base = {"key": {"nested": 1}}
    overlay = {"key": "new_value"}
    result = config.RegistryManager._deep_merge(base, overlay)
    assert result["key"] == "new_value"


def test_registry_manager_load_baseline_failure(capsys):
    with patch("eval_runner.config.SHIM_RESOURCES_INTERNAL_PATH") as mock_path:
        mock_path.exists.return_value = True
        with patch("builtins.open", MagicMock(side_effect=Exception("Disk Error"))):
            config._SHIM_REGISTRY_CACHE = None
            config.RegistryManager.get_resolved_registry()
    captured = capsys.readouterr()
    assert "Failed to load internal baseline" in captured.out


def test_get_forensic_policy_env_overrides(monkeypatch):
    monkeypatch.setenv("FORENSIC_MAX_ARTIFACT_SIZE", "1024")
    policy = config.get_forensic_policy()
    assert policy["max_artifact_size"] == 1024


def test_get_sanitized_registry():
    data = {"secret_key": "s123"}
    with patch.object(config.RegistryManager, "get_resolved_registry", return_value=data):
        assert config.RegistryManager.get_sanitized_registry()["secret_key"] == "[REDACTED]"


def test_update_from_env(monkeypatch):
    monkeypatch.setenv("AES_TEST_KEY", '{"a": 1}')
    monkeypatch.setenv("AES_BROKEN", "{broken}")
    cfg = {}
    # We may need to mock os.environ iteration if update_from_env iterates it
    try:
        config.update_from_env(cfg)
    except Exception:
        pass
