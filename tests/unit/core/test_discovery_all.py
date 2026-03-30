import unittest
from unittest.mock import MagicMock, patch, ANY
import importlib
import pkgutil
from pathlib import Path
from collections import namedtuple

# SUT
from eval_runner import discovery

class BaseTest:
    pass

class SubTest(BaseTest):
    pass

class TestDiscovery(unittest.TestCase):

    def setUp(self):
        # Reset modules names for discovery logic
        SubTest.__module__ = "mock_module"
        BaseTest.__module__ = "mock_module"

    def test_discover_classes_in_module_instantiate(self):
        mock_module = MagicMock()
        mock_module.__name__ = "mock_module"
        
        members = [
            ("SubTest", SubTest),
            ("BaseTest", BaseTest)
        ]
        
        with patch("inspect.getmembers", return_value=members):
            found = discovery.discover_classes_in_module(mock_module, BaseTest, instantiate=True)
            self.assertEqual(len(found), 1)
            self.assertIsInstance(found[0], SubTest)

    def test_discover_classes_in_module_no_instantiate(self):
        mock_module = MagicMock()
        mock_module.__name__ = "mock_module"
        
        members = [("SubTest", SubTest)]
        with patch("inspect.getmembers", return_value=members):
            found = discovery.discover_classes_in_module(mock_module, BaseTest, instantiate=False)
            self.assertEqual(found[0], SubTest)

    @patch("eval_runner.discovery.importlib.import_module")
    def test_discover_plugins_in_directory(self, mock_import):
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        
        mock_file = MagicMock(spec=Path)
        mock_file.name = "my_plugin.py"
        mock_file.stem = "my_plugin"
        
        mock_init = MagicMock(spec=Path)
        mock_init.name = "__init__.py"
        
        mock_dir.glob.return_value = [mock_file, mock_init]
        
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        
        with patch.object(discovery, "discover_classes_in_module", return_value=[123]):
            # Test with package_prefix (Line 42)
            plugins = discovery.discover_plugins_in_directory(mock_dir, BaseTest, package_prefix="com.aes")
            self.assertEqual(plugins, [123])
            mock_import.assert_called_with("com.aes.my_plugin")

    def test_discover_plugins_in_directory_not_exists(self):
        # Line 34
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = False
        plugins = discovery.discover_plugins_in_directory(mock_dir, BaseTest)
        self.assertEqual(plugins, [])

    def test_discover_plugins_in_directory_import_fail(self):
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        
        mock_file = MagicMock(spec=Path)
        mock_file.name = "broken.py"
        mock_file.stem = "broken"
        mock_dir.glob.return_value = [mock_file]
        
        with patch("eval_runner.discovery.importlib.import_module", side_effect=Exception("Import fail")):
            plugins = discovery.discover_plugins_in_directory(mock_dir, BaseTest)
            self.assertEqual(plugins, [])

    @patch("eval_runner.discovery.importlib.import_module")
    @patch("eval_runner.discovery.pkgutil.walk_packages")
    def test_discover_classes_in_package_recursive(self, mock_walk, mock_import):
        mock_package = MagicMock()
        mock_package.__path__ = ["/path"]
        mock_package.__name__ = "my_pkg"
        
        ModuleInfo = namedtuple('ModuleInfo', 'module_finder name ispkg')
        mock_info = ModuleInfo(MagicMock(), "my_pkg.sub", False)
        mock_walk.return_value = [mock_info]
        
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        
        with patch.object(discovery, "discover_classes_in_module", return_value=["found_class"]):
            results = discovery.discover_classes_in_package(mock_package, BaseTest, recursive=True)
            self.assertEqual(results, {"sub": "found_class"})

    def test_discover_classes_in_package_fail(self):
        # Line 77-79
        mock_package = MagicMock()
        mock_package.__path__ = ["/path"]
        mock_package.__name__ = "my_pkg"
        
        ModuleInfo = namedtuple('ModuleInfo', 'module_finder name ispkg')
        mock_walk_results = [ModuleInfo(MagicMock(), "my_pkg.broken", False)]
        
        original_import = importlib.import_module
        def side_effect(name, *args, **kwargs):
            if name == "my_pkg.broken":
                raise Exception("Explosion")
            return original_import(name)

        with patch("eval_runner.discovery.pkgutil.walk_packages", return_value=mock_walk_results):
            with patch("eval_runner.discovery.importlib.import_module", side_effect=side_effect):
                with patch("builtins.print") as mock_print:
                    results = discovery.discover_classes_in_package(mock_package, BaseTest)
                    self.assertEqual(results, {})
                    mock_print.assert_called()
                    self.assertIn("Failed to load module 'my_pkg.broken'", mock_print.call_args[0][0])
                    print("DEBUG: Verified print was called through mock")

    @patch("eval_runner.discovery.pkgutil.iter_modules")
    def test_discover_classes_in_package_non_recursive(self, mock_iter):
        mock_package = MagicMock()
        mock_package.__path__ = ["/path"]
        mock_package.__name__ = "my_pkg"
        mock_iter.return_value = []
        
        discovery.discover_classes_in_package(mock_package, BaseTest, recursive=False)
        mock_iter.assert_called()

    @patch("eval_runner.discovery.importlib.import_module")
    @patch("eval_runner.discovery.pkgutil.iter_modules")
    def test_scan_package_for_adapters(self, mock_iter, mock_import):
        mock_package = MagicMock()
        mock_package.__path__ = ["/path"]
        mock_package.__name__ = "adapters"
        
        mock_iter.return_value = [(None, "http", False)]
        
        mock_module = MagicMock()
        mock_module.adapter = lambda x: x
        mock_import.return_value = mock_module
        
        registry_func = MagicMock()
        discovery.scan_package_for_adapters(mock_package, registry_func)
        registry_func.assert_called_with("http", ANY)

    def test_scan_package_for_adapters_fail(self):
        mock_package = MagicMock()
        mock_package.__path__ = ["/path"]
        mock_package.__name__ = "adapters"
        
        with patch("eval_runner.discovery.pkgutil.iter_modules", return_value=[(None, "broken", False)]):
            with patch("eval_runner.discovery.importlib.import_module", side_effect=Exception("Fail")):
                registry_func = MagicMock()
                discovery.scan_package_for_adapters(mock_package, registry_func)
                registry_func.assert_not_called()

if __name__ == '__main__':
    unittest.main()
