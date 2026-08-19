"""
tests/contracts/test_path_safety_contract.py
Contract Test Suite: Centralized Path-Boundary Security Invariants.
Guarantees that no store (ArtifactStore, RunStore, CatalogStore) allows directory traversal.
"""

import pytest

from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.local_catalog import LocalFileCatalogStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.utils.safe_path import SafeRunPathResolver


def test_safe_run_path_resolver_validation():
    # Valid identifiers
    assert SafeRunPathResolver.validate_identifier("run_001") == "run_001"
    assert (
        SafeRunPathResolver.validate_identifier("sub/item.txt", allow_nested=True) == "sub/item.txt"
    )

    # Empty string
    with pytest.raises(ValueError, match="non-empty string"):
        SafeRunPathResolver.validate_identifier("")

    # Traversal sequence
    with pytest.raises(PermissionError, match="traversal"):
        SafeRunPathResolver.validate_identifier("../escaped")

    with pytest.raises(PermissionError, match="traversal"):
        SafeRunPathResolver.validate_identifier("foo/../../escaped", allow_nested=True)

    # Disallowed nested separator
    with pytest.raises(PermissionError, match="Nested path separators not permitted"):
        SafeRunPathResolver.validate_identifier("nested/dir/id", allow_nested=False)

    # Null byte injection
    with pytest.raises(PermissionError, match="Null byte"):
        SafeRunPathResolver.validate_identifier("run\x00_inject")


def test_artifact_store_path_safety(tmp_path):
    artifact_store = LocalFileArtifactStore(base_dir=tmp_path)

    # Valid store and retrieve
    uri = artifact_store.store_artifact("run_100", "output.txt", "Sample artifact")
    assert tmp_path.name in uri
    assert artifact_store.exists("run_100", "output.txt")
    assert artifact_store.get_artifact("run_100", "output.txt") == b"Sample artifact"

    # Traversal via run_id
    with pytest.raises(PermissionError):
        artifact_store.store_artifact("../escaped_run", "test.txt", "data")

    # Traversal via artifact_name
    with pytest.raises(PermissionError):
        artifact_store.store_artifact("run_100", "../../escaped_file.txt", "data")

    # Write-once overwrite protection
    with pytest.raises(PermissionError, match="already exists and overwrite is disabled"):
        artifact_store.store_artifact("run_100", "output.txt", "New data", overwrite=False)


def test_run_store_path_safety(tmp_path):
    run_store = LocalFileRunStore(log_dir=tmp_path)

    # Valid run
    run_store.save_run_manifest("run_200", {"status": "SUCCESS"})
    run_data = run_store.get_run("run_200")
    assert run_data is not None
    assert run_data["manifest"]["status"] == "SUCCESS"

    # Traversal via run_id on save
    with pytest.raises(PermissionError):
        run_store.save_run_manifest("../escaped_run", {"status": "MALICIOUS"})

    # Traversal via run_id on get_run returns None safely
    assert run_store.get_run("../escaped_run") is None

    # Traversal via run_id on delete returns False safely
    assert run_store.delete_run("../escaped_run") is False


def test_catalog_store_path_safety(tmp_path):
    catalog_store = LocalFileCatalogStore(base_dir=tmp_path)

    # Valid save and get
    catalog_store.save_scenario(
        "scenario_safe_01", {"id": "scenario_safe_01", "name": "Safe Scenario"}
    )
    scen = catalog_store.get_scenario("scenario_safe_01")
    assert scen is not None
    assert scen["name"] == "Safe Scenario"

    # Traversal via scenario_id on save
    with pytest.raises(PermissionError):
        catalog_store.save_scenario("../escaped_scenario", {"id": "evil"})

    # Traversal via scenario_id on delete returns False safely
    assert catalog_store.delete_scenario("../escaped_scenario") is False
