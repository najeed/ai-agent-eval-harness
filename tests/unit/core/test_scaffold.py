import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import unittest
from unittest.mock import mock_open, patch

# SUT
import eval_runner.scaffold as scaffold


class TestScaffold(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    @patch("builtins.input", side_effect=["finance", "loan_approval", "3"])
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", return_value=True)  # Ensure schema check is attempted
    @patch("builtins.open", new_callable=mock_open, read_data="{}")
    def test_generate_interactive_success(self, mock_file, mock_exists, mock_mkdir, mock_input):
        scaffold.generate_interactive()

        # 3 * 2 = 6 calls
        self.assertEqual(mock_file.call_count, 6)

    @patch("builtins.input", side_effect=["test", "test", "invalid"])
    @patch("pathlib.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    def test_generate_interactive_invalid_count(self, mock_file, mock_mkdir, mock_input):
        """Verify fallback to count=1 when input is invalid."""
        scaffold.generate_interactive()
        # 1 scenario * 1 open call (skipping schema check for simplicity here)
        self.assertGreaterEqual(mock_file.call_count, 1)

    @patch("builtins.input", side_effect=["test", "test", "1"])
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", return_value=True)
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data='{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}',
    )
    @patch("eval_runner.scaffold.validate")
    def test_generate_interactive_validation_error(
        self, mock_validate, mock_file, mock_exists, mock_mkdir, mock_input
    ):
        """Verify error handling when schema validation fails."""
        from jsonschema.exceptions import ValidationError

        mock_validate.side_effect = ValidationError("Custom Error")

        scaffold.generate_interactive()
        mock_validate.assert_called()

    @patch("eval_runner.registry_sync.load_registry")
    @patch("pathlib.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    def test_init_standard_success(self, mock_file, mock_mkdir, mock_load_registry):
        mock_load_registry.return_value = {
            "industries": {
                "finance": {
                    "standards": {
                        "ISO20022": {
                            "id": "ISO20022",
                            "name": "ISO 20022",
                            "industry": "finance",
                            "description": "Standard for financial messaging.",
                        }
                    }
                }
            }
        }

        scaffold.init_standard("ISO20022")

        # Verify mkdir calls
        self.assertGreaterEqual(mock_mkdir.call_count, 3)

        # Verify README.md write. We check if any call had the specified partial name.
        has_readme = any("README.md" in str(args[0]) for args, _ in mock_file.call_args_list)
        self.assertTrue(has_readme, "Should have attempted to write README.md")

    def test_init_standard_not_found(self):
        with patch("eval_runner.registry_sync.load_registry", return_value={"industries": {}}):
            with self.assertRaises(ValueError):
                scaffold.init_standard("UNKNOWN")

    @patch("pathlib.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    def test_scaffold_benchmark_success(self, mock_file, mock_mkdir):
        scaffold.scaffold_benchmark("test_env", "telecom", "http://test")

        # Base dir created
        mock_mkdir.assert_called()

        # At least 2 files: eval_config.json and starter_scenario.json
        has_config = any("eval_config.json" in str(args[0]) for args, _ in mock_file.call_args_list)
        has_starter = any(
            "starter_scenario.json" in str(args[0]) for args, _ in mock_file.call_args_list
        )

        self.assertTrue(has_config)
        self.assertTrue(has_starter)

    @patch("pathlib.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    def test_generate_github_action_success(self, mock_file, mock_mkdir):
        scaffold.generate_github_action()
        # Verify it tries to write to .github/workflows/eval_harness_ci.yml
        has_ci = any("eval_harness_ci.yml" in str(args[0]) for args, _ in mock_file.call_args_list)
        self.assertTrue(has_ci)


def test_scaffold_registry_and_interactive_edge_branches(tmp_path, monkeypatch):
    import builtins
    import importlib
    import json
    import sys

    schema_dir = tmp_path / "spec" / "aes"
    schema_dir.mkdir(parents=True)
    schema_path = schema_dir / "aes.schema.json"
    schema_dict = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}
    schema_path.write_text(json.dumps(schema_dict), encoding="utf-8")

    # 1. Without definitions dir -> returns registry
    reg = scaffold._get_aes_registry(schema_path, schema_dict)
    assert reg is not None

    # 2. With corrupt JSON inside definitions/ -> logs and skips
    defs_dir = schema_dir / "definitions"
    defs_dir.mkdir()
    (defs_dir / "broken.json").write_text("{invalid", encoding="utf-8")
    reg2 = scaffold._get_aes_registry(schema_path, schema_dict)
    assert reg2 is not None

    # 3. Missing referencing module + missing reconfigure on stdout/stderr
    with (
        patch.object(sys, "stdout", object()),
        patch.object(sys, "stderr", object()),
        patch.dict(sys.modules, {"referencing": None}),
    ):
        reloaded = importlib.reload(scaffold)
        assert reloaded._get_aes_registry(schema_path, schema_dict) is None

    # Restore module cleanly
    importlib.reload(scaffold)

    # 4. generate_interactive when schema_path does not exist
    monkeypatch.chdir(tmp_path)
    inputs = iter(["fin", "audit", "1"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(inputs))
    with patch("pathlib.Path.exists", return_value=False):
        scaffold.generate_interactive()
    assert (tmp_path / "scenarios" / "fin" / "gen_fin_audit_1.json").is_file()

    # 5. init_standard iterating past a non-matching category
    fake_reg = {
        "industries": {
            "other": {"standards": {}},
            "fin": {
                "standards": {
                    "STD1": {"name": "Std One", "industry": "finance", "description": "d"}
                }
            },
        }
    }
    with patch("eval_runner.registry_sync.load_registry", return_value=fake_reg):
        scaffold.init_standard("STD1")
    assert (tmp_path / "eval_std1").is_dir()


if __name__ == "__main__":
    unittest.main()
