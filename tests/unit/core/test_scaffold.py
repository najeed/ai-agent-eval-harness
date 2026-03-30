import unittest
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path
import json

# SUT
import eval_runner.scaffold as scaffold

class TestScaffold(unittest.TestCase):

    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()

    @patch("builtins.input", side_effect=["finance", "loan_approval", "3"])
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", return_value=True) # Ensure schema check is attempted
    @patch("builtins.open", new_callable=mock_open, read_data="{}")
    def test_generate_interactive_success(self, mock_file, mock_exists, mock_mkdir, mock_input):
        scaffold.generate_interactive()
        
        # Each of 3 scenarios does: 
        # 1. open schema (read)
        # 2. open output (write)
        # 3 * 2 = 6 calls
        self.assertEqual(mock_file.call_count, 6)

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
                            "description": "Standard for financial messaging."
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
        has_starter = any("starter_scenario.json" in str(args[0]) for args, _ in mock_file.call_args_list)
        
        self.assertTrue(has_config)
        self.assertTrue(has_starter)

    @patch("pathlib.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    def test_generate_github_action_success(self, mock_file, mock_mkdir):
        scaffold.generate_github_action()
        # Verify it tries to write to .github/workflows/eval_harness_ci.yml
        has_ci = any("eval_harness_ci.yml" in str(args[0]) for args, _ in mock_file.call_args_list)
        self.assertTrue(has_ci)

if __name__ == '__main__':
    unittest.main()
