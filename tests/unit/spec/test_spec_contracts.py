"""
[Spec contracts] Validate REAL produced artifacts against their /spec schemas:

  - samples/packs/sample-pack/pack.yaml        -> spec/scenario-pack
  - .aes/agent_targets.json (via AgentTargetStore) -> spec/agent-targets
  - a signed-capable RuntimeExtension manifest -> spec/extensions

These are the enforcement half of the spec definitions: if a producer drifts
from its schema, these tests fail before an auditor ever notices.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

SPEC_DIR = Path(__file__).resolve().parents[3] / "spec"
SAMPLE_PACK_DIR = Path(__file__).resolve().parents[3] / "samples" / "packs" / "sample-pack"


def _schema(name: str) -> dict:
    return json.loads((SPEC_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Scenario pack manifest
# ---------------------------------------------------------------------------


def test_sample_pack_yaml_matches_schema():
    doc = yaml.safe_load((SAMPLE_PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=_schema("scenario-pack/scenario-pack.schema.json"))
    assert doc["name"] == "sample"
    assert len(doc["files"]) == 1


def test_pack_schema_rejects_bad_name_and_hash():
    schema = _schema("scenario-pack/scenario-pack.schema.json")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"name": "Bad Name!"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"name": "ok", "files": {"a.json": "not-a-hash"}}, schema)


# ---------------------------------------------------------------------------
# Agent Targets registry
# ---------------------------------------------------------------------------


def test_agent_targets_registry_matches_schema(tmp_path):
    from eval_runner.console.routes.agent_targets import (
        AgentTargetStore,
        _validate_target_payload,
    )

    registry = tmp_path / "agent_targets.json"
    store = AgentTargetStore(registry)
    store.upsert(
        _validate_target_payload(
            {
                "name": "Primary Agent",
                "protocol": "custom_http",
                "endpoint": "https://agents.example.com/v1",
                "model": "orchestrator-x",
                "max_turns": 12,
                "timeout_seconds": 45,
            }
        ),
        target_id="primary-agent",
    )

    doc = json.loads(registry.read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=_schema("agent-targets/agent-targets.schema.json"))
    assert doc["schema_version"] == "1.0.0"
    target = doc["targets"]["primary-agent"]
    assert target["endpoint"].startswith("https://")


def test_agent_targets_schema_rejects_secrets_and_bad_protocol(tmp_path):
    schema = _schema("agent-targets/agent-targets.schema.json")
    bad = {
        "schema_version": "1.0.0",
        "targets": {
            "x": {
                "id": "x",
                "name": "X",
                "protocol": "carrier_pigeon",
                "endpoint": "https://a.example.com",
                "created_at": "2026-08-25T00:00:00",
                "updated_at": "2026-08-25T00:00:00",
            }
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    bad["targets"]["x"]["protocol"] = "custom_http"
    bad["targets"]["x"]["api_key"] = "sk-leak"  # additionalProperties=false
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


# ---------------------------------------------------------------------------
# RuntimeExtension manifest
# ---------------------------------------------------------------------------


def _manifest_dict() -> dict:
    from agentv_runtime.extension_contract import EXTENSION_CONTRACT_VERSION

    return {
        "extension_id": "control-plane",
        "display_name": "Control Plane",
        "version": "1.0.0",
        "api_version": EXTENSION_CONTRACT_VERSION,
        "capabilities": ["routes", "navigation", "runs:read"],
        "required_permissions": [],
        "routes": [{"path": "/cp/fleet", "label": "Fleet"}],
        "nav_group": "extensions",
        "remote_entry": "https://cp.example.com/remote.js",
        "sri_hash": "ab" * 32,
        "publisher": "acme-platform",
        "signature": "cd" * 64,
        "lifecycle": {"on_mount": "onMount", "on_error": "onError"},
    }


def test_extension_manifest_matches_schema_and_semantics():
    from agentv_runtime.extension_contract import RuntimeExtension

    doc = _manifest_dict()
    jsonschema.validate(instance=doc, schema=_schema("extensions/extension-manifest.schema.json"))
    # Semantic layer: capability whitelist + api_version compatibility +
    # signature/publisher presence for signed manifests.
    ext = RuntimeExtension.from_dict(doc)
    violations = ext.validate(require_signature=True)
    assert violations == []


def test_extension_manifest_rejects_unknown_capability():
    schema = _schema("extensions/extension-manifest.schema.json")
    doc = _manifest_dict()
    doc["capabilities"] = ["fleet:write"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)
