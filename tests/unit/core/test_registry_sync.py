import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import os
import runpy

# SUT
import eval_runner.registry_sync as registry_sync

class TestRegistrySync(unittest.TestCase):

    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()

    def test_load_registry_cases(self):
        mock_reg = MagicMock()
        
        # Line 12-13: File not found
        mock_reg.exists.return_value = False
        with patch.object(registry_sync, "REGISTRY_PATH", mock_reg):
            self.assertEqual(registry_sync.load_registry(), {"industries": {}})

        # Lines 27-32: Subcategories
        mock_reg.exists.return_value = True
        with patch.object(registry_sync, "REGISTRY_PATH", mock_reg):
            mock_data = {
                "categories": {
                    "Parent": {
                        "description": "PDesc",
                        "standards": [{"id": "S1", "name": "N1", "description": "D1"}],
                        "subcategories": [
                            {
                                "name": "Child",
                                "description": "CDesc",
                                "standards": [{"id": "S2", "name": "N2", "description": "D2"}]
                            }
                        ]
                    }
                }
            }
            m = mock_open(read_data=json.dumps(mock_data))
            with patch("builtins.open", m):
                res = registry_sync.load_registry()
                self.assertIn("Parent", res["industries"])
                self.assertIn("Parent - Child", res["industries"])
                self.assertEqual(res["industries"]["Parent - Child"]["standards"]["S2"]["id"], "S2")

    def test_get_registry_ids_cases(self):
        mock_reg = MagicMock()
        
        # Line 38-39: File not found
        mock_reg.exists.return_value = False
        with patch.object(registry_sync, "REGISTRY_PATH", mock_reg):
            self.assertEqual(registry_sync.get_registry_ids(), [])

        # Lines 54-56: Subcategory IDs
        mock_reg.exists.return_value = True
        with patch.object(registry_sync, "REGISTRY_PATH", mock_reg):
            mock_data = {
                "categories": {
                    "Cat": {
                        "standards": [{"id": "S1"}],
                        "subcategories": [{"standards": [{"id": "S2"}]}]
                    }
                }
            }
            m = mock_open(read_data=json.dumps(mock_data))
            with patch("builtins.open", m):
                self.assertEqual(registry_sync.get_registry_ids(), ["S1", "S2"])

    def test_ensure_schema_sync_cases(self):
        reg = MagicMock()
        meta = MagicMock()
        
        # Line 65-66: Missing files
        reg.exists.return_value = False
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch.object(registry_sync, "METADATA_SCHEMA_PATH", meta):
                self.assertIsNone(registry_sync.ensure_schema_sync())

        # Line 72-73: reg <= meta (not newer)
        reg.exists.return_value = True
        meta.exists.return_value = True
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch.object(registry_sync, "METADATA_SCHEMA_PATH", meta):
                with patch("eval_runner.registry_sync.os.path.getmtime", side_effect=[100, 200]):
                    self.assertIsNone(registry_sync.ensure_schema_sync(force=False))

        # Line 77: No IDs
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch.object(registry_sync, "METADATA_SCHEMA_PATH", meta):
                with patch("eval_runner.registry_sync.os.path.getmtime", side_effect=[200, 100]):
                    with patch("eval_runner.registry_sync.get_registry_ids", return_value=[]):
                        self.assertIsNone(registry_sync.ensure_schema_sync())

        # Line 86-91: SUCCESS BLOCK
        mock_schema = {"properties": {"standards_registry": {"items": {"enum": []}}}}
        m = mock_open(read_data=json.dumps(mock_schema))
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch.object(registry_sync, "METADATA_SCHEMA_PATH", meta):
                with patch("eval_runner.registry_sync.os.path.getmtime", side_effect=[200, 100]):
                    with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                        with patch("builtins.open", m):
                            with patch("eval_runner.registry_sync.os.utime") as mock_utime:
                                registry_sync.ensure_schema_sync()
                                mock_utime.assert_called()

        # Line 92-93: KeyError
        mock_schema_broken = {"broken": {}}
        m_broken = mock_open(read_data=json.dumps(mock_schema_broken))
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch.object(registry_sync, "METADATA_SCHEMA_PATH", meta):
                with patch("eval_runner.registry_sync.os.path.getmtime", side_effect=[200, 100]):
                    with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                        with patch("builtins.open", m_broken):
                            registry_sync.ensure_schema_sync()

    def test_add_standard_to_registry_cases(self):
        reg = MagicMock()
        
        # Line 98-99: Registry not found
        reg.exists.return_value = False
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            self.assertFalse(registry_sync.add_standard_to_registry("S1", "N1", "I1", "D1"))
        
        # Line 106-108: Already exists
        reg.exists.return_value = True
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch("eval_runner.registry_sync.get_registry_ids", return_value=["S1"]):
                with patch("builtins.open", mock_open(read_data="{}")):
                    self.assertFalse(registry_sync.add_standard_to_registry("S1", "N1", "I1", "D1"))
        
        # Line 116-121: New category
        with patch.object(registry_sync, "REGISTRY_PATH", reg):
            with patch("eval_runner.registry_sync.get_registry_ids", return_value=[]):
                # mock registry with empty categories
                m = mock_open(read_data=json.dumps({"categories": {}}))
                with patch("builtins.open", m):
                    with patch("eval_runner.registry_sync.ensure_schema_sync"):
                        res = registry_sync.add_standard_to_registry("S_NEW", "Name", "NewInd", "Desc")
                        self.assertTrue(res)

if __name__ == '__main__':
    unittest.main()
