import unittest
from unittest.mock import MagicMock, patch
import pkgutil
from pathlib import Path

# SUT
import eval_runner.discovery as discovery

class BaseTest: pass
class SubTest(BaseTest): pass

class TestDiscovery(unittest.TestCase):

    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()

    def test_discover_classes_in_module(self):
        mock_module = MagicMock()
        mock_module.__name__ = "mock_mod"
        SubTest.__module__ = "mock_mod"
        BaseTest.__module__ = "mock_mod"
        
        members = [("SubTest", SubTest), ("BaseTest", BaseTest), ("Other", 123)]
        
        with patch("eval_runner.discovery.inspect.getmembers", return_value=members):
            with patch("eval_runner.discovery.inspect.isclass", side_effect=lambda x: isinstance(x, type)):
                found = discovery.discover_classes_in_module(mock_module, BaseTest, instantiate=False)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0], SubTest)

    def test_discover_plugins_in_directory_various_cases(self):
        mock_dir = MagicMock(spec=Path)
        
        # Scenario 1: Line 34 - Exists but not a directory
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = False
        self.assertEqual(discovery.discover_plugins_in_directory(mock_dir, BaseTest), [])

        # Scenario 2: Line 38 and 42/44
        mock_dir.is_dir.return_value = True
        init_file = MagicMock(spec=Path)
        init_file.name = "__init__.py"
        
        valid_file = MagicMock(spec=Path)
        valid_file.name = "plugin.py"
        valid_file.stem = "plugin"
        
        broken_file = MagicMock(spec=Path)
        broken_file.name = "broken.py"
        broken_file.stem = "broken"

        mock_dir.glob.return_value = [init_file, valid_file, broken_file]
        
        def import_side(name):
            if "broken" in name: raise Exception("Boom")
            m = MagicMock()
            m.__name__ = name
            return m
            
        with patch.object(discovery, "importlib", MagicMock(import_module=MagicMock(side_effect=import_side))):
            with patch.object(discovery, "discover_classes_in_module", return_value=["Inst"]):
                # Test with prefix (line 42)
                plugins = discovery.discover_plugins_in_directory(mock_dir, BaseTest, package_prefix="prefix")
                self.assertEqual(plugins, ["Inst"])
                
                # Test without prefix (line 44)
                plugins = discovery.discover_plugins_in_directory(mock_dir, BaseTest)
                self.assertEqual(plugins, ["Inst"])

    def test_discover_classes_in_package_resilience(self):
        mock_pkg = MagicMock()
        mock_pkg.__path__ = ["/path"]
        mock_pkg.__name__ = "pkg"
        
        ModuleInfo = pkgutil.ModuleInfo
        mock_pkgutil = MagicMock()
        mock_pkgutil.walk_packages.return_value = [
            ModuleInfo(None, "pkg.sub", False),
            ModuleInfo(None, "pkg.broken", False)
        ]
        
        def import_side(name):
            if "broken" in name: raise Exception("Inner Boom")
            return MagicMock()

        with patch.object(discovery, "pkgutil", mock_pkgutil):
            with patch.object(discovery, "importlib", MagicMock(import_module=MagicMock(side_effect=import_side))):
                with patch.object(discovery, "discover_classes_in_module", return_value=["SomeClass"]):
                    # results set to hit lines 76/77 silent fail
                    res = discovery.discover_classes_in_package(mock_pkg, BaseTest)
                    self.assertIn("sub", res)
                    self.assertEqual(res["sub"], "SomeClass")
                    self.assertNotIn("broken", res)

    def test_scan_package_for_adapters_resilience(self):
        mock_pkg = MagicMock()
        mock_pkg.__path__ = ["/path"]
        mock_pkg.__name__ = "pkg"
        
        ModuleInfo = pkgutil.ModuleInfo
        mock_pkgutil = MagicMock()
        mock_pkgutil.iter_modules.return_value = [
            ModuleInfo(None, "valid", False),
            ModuleInfo(None, "broken", False)
        ]
        
        def import_side(name):
            if "broken" in name: raise Exception("Outer Boom")
            m = MagicMock()
            m.adapter = lambda: "ok"
            return m

        results = {}
        def reg(name, func): results[name] = func
        
        with patch.object(discovery, "pkgutil", mock_pkgutil):
            with patch.object(discovery, "importlib", MagicMock(import_module=MagicMock(side_effect=import_side))):
                # hit lines 94/95 silent fail
                discovery.scan_package_for_adapters(mock_pkg, reg)
                self.assertIn("valid", results)
                self.assertNotIn("broken", results)

if __name__ == '__main__':
    unittest.main()
