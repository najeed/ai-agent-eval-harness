import json
import os
import pytest
from pathlib import Path
from eval_runner import config

def test_registry_deep_merge():
    base = {"shims": {"api": {"resources": {"a": 1, "b": 2}}}}
    overlay = {"shims": {"api": {"resources": {"b": 3, "c": 4}}}}
    expected = {"shims": {"api": {"resources": {"a": 1, "b": 3, "c": 4}}}}
    
    result = config.RegistryManager._deep_merge(base, overlay)
    assert result == expected

def test_registry_loading_hierarchy(tmp_path):
    # Setup temporary registry files
    base_file = tmp_path / "shim_resources.json"
    local_file = tmp_path / "shim_resources.local.json"
    
    base_file.write_text(json.dumps({"shims": {"api": {"resources": {"timeout": 10}}}}))
    local_file.write_text(json.dumps({"shims": {"api": {"resources": {"timeout": 20, "key": "secret"}}}}))
    
    # Mock config paths
    original_base = config.SHIM_RESOURCES_PATH
    original_local = config.SHIM_RESOURCES_LOCAL_PATH
    
    config.SHIM_RESOURCES_PATH = base_file
    config.SHIM_RESOURCES_LOCAL_PATH = local_file
    
    try:
        config.RegistryManager.reload()
        conf = config.get_shim_config("api")
        assert conf["timeout"] == 20
        assert conf["key"] == "secret"
    finally:
        config.SHIM_RESOURCES_PATH = original_base
        config.SHIM_RESOURCES_LOCAL_PATH = original_local
        config.RegistryManager.reload()

def test_environment_variable_override():
    env_payload = json.dumps({"shims": {"api": {"resources": {"timeout": 99}}}})
    os.environ["AES_SHIM_RESOURCES_JSON"] = env_payload
    
    try:
        config.RegistryManager.reload()
        conf = config.get_shim_config("api")
        assert conf["timeout"] == 99
    finally:
        del os.environ["AES_SHIM_RESOURCES_JSON"]
        config.RegistryManager.reload()

def test_get_shim_config_missing_shim():
    config.RegistryManager.reload()
    conf = config.get_shim_config("non_existent_shim")
    assert conf == {}
