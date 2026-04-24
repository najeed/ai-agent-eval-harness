import sys
import unittest
from unittest.mock import MagicMock, patch

from eval_runner import cli


class TestCLIExtensions(unittest.TestCase):
    """
    Industrial Verification for the Zero-Touch Extension Architecture.
    Tests that external Entry Points are correctly discovered, registered, and dispatched.
    """

    def setUp(self):
        # Reset parser cache to ensure discovery runs for each test
        cli._parser_cache = None
        cli._parser_argv_hash = None

    @patch("importlib.metadata.entry_points")
    def test_extension_discovery_and_registration(self, mock_entry_points):
        """Verify that an entry point can add a custom command to the parser."""

        # 1. Create a mock EntryPoint
        mock_ep = MagicMock()
        mock_ep.name = "test_ext"

        # This function will be 'loaded' from the entry point
        def mock_register(subparsers):
            p = subparsers.add_parser("ext-cmd", help="Mock extension command")
            p.set_defaults(func=lambda args: 42)  # Should return 42 when executed

        mock_ep.load.return_value = mock_register

        # Mock entry_points() return value (supporting 3.10+ group filtering)
        mock_entry_points.return_value = [mock_ep]

        # 2. Get the parser
        with patch.object(sys, "argv", ["agentv", "--help"]):
            parser = cli.get_parser(is_help=True)

        # 3. Verify the command exists in subparsers
        # subparsers are stored in parser._subparsers._group_actions[0].choices
        subparsers_action = [
            a for a in parser._actions if isinstance(a, cli.argparse._SubParsersAction)
        ][0]
        self.assertIn("ext-cmd", subparsers_action.choices)

    @patch("importlib.metadata.entry_points")
    def test_extension_dispatch(self, mock_entry_points):
        """Verify that the Unified Dispatcher correctly executes an extension command."""

        mock_ep = MagicMock()
        mock_ep.name = "test_ext"

        def mock_register(subparsers):
            p = subparsers.add_parser("ext-dispatch")
            p.set_defaults(func=lambda args: 99)

        mock_ep.load.return_value = mock_register
        mock_entry_points.return_value = [mock_ep]

        # Simulate running 'agentv ext-dispatch'
        with patch.object(sys, "argv", ["agentv", "ext-dispatch"]):
            with self.assertRaises(SystemExit) as cm:
                cli.main()

            # Verify exit code matches the return value of our mock handler
            self.assertEqual(cm.exception.code, 99)

    @patch("importlib.metadata.entry_points")
    def test_extension_load_failure_isolation(self, mock_entry_points):
        """Verify that a failing extension does not crash the entire CLI."""

        mock_ep = MagicMock()
        mock_ep.name = "broken_ext"
        mock_ep.load.side_effect = Exception("Industrial Sabotage")

        mock_entry_points.return_value = [mock_ep]

        # We need to capture stderr to verify the warning
        with patch("sys.stderr.write") as mock_stderr:
            with patch.object(sys, "argv", ["agentv", "--help"]):
                cli.get_parser(is_help=True)

            # Check for the warning message
            warning_called = any("broken_ext" in call[0][0] for call in mock_stderr.call_args_list)
            self.assertTrue(
                warning_called, "Warning message should be printed for failed extension load"
            )


if __name__ == "__main__":
    unittest.main()
