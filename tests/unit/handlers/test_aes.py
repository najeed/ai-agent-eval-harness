import pytest
import yaml

from eval_runner.handlers.scenarios import handle_aes_validate


class MockArgs:
    def __init__(self, path):
        self.path = path
        self.aes_command = "validate"


@pytest.mark.asyncio
async def test_aes_validation_success(tmp_path, capsys):
    aes_data = {
        "aes_version": 1.4,
        "metadata": {"name": "test", "id": "test_id", "compliance_level": "Standard"},
        "description": "test description",
        "industry": "general",
        "workflow": {"nodes": [{"id": "node_1", "task_description": "hi"}], "edges": []},
    }
    aes_file = tmp_path / "valid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    await handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "✔ valid.aes.yaml: Valid (AES v1.4)" in captured.out


@pytest.mark.asyncio
async def test_aes_validation_failure(tmp_path, capsys):
    aes_data = {
        "aes_version": "invalid",  # Should be number
        "metadata": {},  # Missing 'name'
    }
    aes_file = tmp_path / "invalid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    await handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "✘ invalid.aes.yaml: Invalid - 'workflow' is a required property" in captured.out


@pytest.mark.asyncio
async def test_aes_validation_with_complexity_level(tmp_path, capsys):
    """v1.2: metadata is the primary container for governance."""
    aes_data = {
        "aes_version": 1.4,
        "metadata": {
            "name": "complexity_test",
            "id": "complexity_id",
            "compliance_level": "Regulatory_Audit",
            "standards_registry": ["ISO_20022"],
        },
        "description": "test",
        "industry": "finance",
        "workflow": {"nodes": [{"id": "n1", "task_description": "audit"}], "edges": []},
    }
    aes_file = tmp_path / "complexity.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    await handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "✔ complexity.aes.yaml: Valid (AES v1.4)" in captured.out
