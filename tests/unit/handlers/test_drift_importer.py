"""Unit tests for strict native-recording import and the Core import-drift CLI."""

from __future__ import annotations

import hashlib
import json

import pytest

from eval_runner import cli
from eval_runner.drift_importer import (
    import_trace_as_scenario,
    parse_recording,
    publish_draft,
)
from eval_runner.handlers.scenarios import handle_import_drift
from eval_runner.loader import get_scenario_validator, load_scenario


def _sample_recording() -> list[dict]:
    return [
        {"event": "run_start", "scenario": "recorded_session", "run_id": "rec-1"},
        {"event": "agent_request", "task": "Look up balance"},
        {"event": "agent_response", "content": {"message": "Balance is $10"}},
        {"event": "agent_request", "task": "Confirm currency"},
        {"event": "agent_response", "content": {"message": "Currency is USD"}},
    ]


def _sample_expectations() -> dict:
    return {
        "turn-1": [{"target": "message", "mode": "regex", "expected": r"\$10"}],
        "turn-2": [{"target": "message", "mode": "regex", "expected": "USD"}],
    }


def test_import_trace_as_scenario_compiles_valid_aes_and_preserves_sources(tmp_path):
    trace_file = tmp_path / "trace.jsonl"
    raw_trace = "\n".join(json.dumps(item) for item in _sample_recording()) + "\n"
    trace_file.write_text(raw_trace, encoding="utf-8")

    exp_file = tmp_path / "expectations.json"
    raw_exp = json.dumps(_sample_expectations())
    exp_file.write_text(raw_exp, encoding="utf-8")

    output_file = tmp_path / "draft.json"
    trace_sha_before = hashlib.sha256(trace_file.read_bytes()).hexdigest()
    exp_sha_before = hashlib.sha256(exp_file.read_bytes()).hexdigest()

    result = import_trace_as_scenario(
        trace_file,
        format="jsonl",
        expectations_path=exp_file,
        scenario_id="reviewed-import-1",
        execution_mode="live",
        industry="telecom",
        output_path=output_file,
    )

    assert result["operation"] == "import"
    assert result["state"] == "draft"
    assert result["turns"] == 2
    assert result["scenario_id"] == "reviewed-import-1"
    assert hashlib.sha256(trace_file.read_bytes()).hexdigest() == trace_sha_before
    assert hashlib.sha256(exp_file.read_bytes()).hexdigest() == exp_sha_before

    draft = json.loads(output_file.read_text(encoding="utf-8"))
    assert draft["aes_version"] == 1.4
    assert draft["industry"] == "telecom"
    assert draft["metadata"]["execution_mode"] == "live"
    assert draft["metadata"]["recorded_history"] == _sample_recording()
    assert [node["id"] for node in draft["workflow"]["nodes"]] == ["turn-1", "turn-2"]
    assert draft["workflow"]["edges"] == [{"from": "turn-1", "to": "turn-2"}]
    assert draft["workflow"]["nodes"][0]["expected_outcome"] == _sample_expectations()["turn-1"]
    assert draft["workflow"]["nodes"][1]["expected_outcome"] == _sample_expectations()["turn-2"]

    get_scenario_validator().validate(draft)
    loaded = load_scenario(output_file)
    assert loaded["metadata"]["recorded_history"] == _sample_recording()


def test_import_rejects_overwrite_and_preserves_existing_output(tmp_path):
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(_sample_recording()), encoding="utf-8")
    exp_file = tmp_path / "expectations.json"
    exp_file.write_text(json.dumps(_sample_expectations()), encoding="utf-8")
    output_file = tmp_path / "existing.json"
    output_file.write_text('{"keep": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        import_trace_as_scenario(
            trace_file,
            format="json",
            expectations_path=exp_file,
            scenario_id="reviewed-import-1",
            execution_mode="simulated",
            industry="finance",
            output_path=output_file,
        )
    assert output_file.read_text(encoding="utf-8") == '{"keep": true}\n'

    fresh = tmp_path / "fresh.json"
    publish_draft(fresh, b'{"ok": true}\n')
    with pytest.raises(FileExistsError):
        publish_draft(fresh, b'{"ok": false}\n')
    assert fresh.read_bytes() == b'{"ok": true}\n'


@pytest.mark.parametrize(
    ("payload", "fmt"),
    [
        (b"not json", "json"),
        (b'{"a": 1}\nnot json\n', "jsonl"),
        (b'[{"a": 1, "a": 2}]', "json"),
        (b'[{"x": NaN}]', "json"),
        (b"[]", "json"),
        (
            json.dumps(
                [
                    {"event": "run_start", "scenario": "recorded_session", "run_id": "r1"},
                    {"event": "agent_request", "task": "Incomplete turn"},
                ]
            ).encode(),
            "json",
        ),
    ],
)
def test_parse_recording_rejects_malformed_and_incomplete_inputs(payload, fmt):
    with pytest.raises(ValueError):
        parse_recording(payload, fmt)


def test_import_rejects_missing_file_and_mismatched_expectations(tmp_path):
    missing = tmp_path / "missing.json"
    exp_file = tmp_path / "expectations.json"
    exp_file.write_text(json.dumps(_sample_expectations()), encoding="utf-8")
    with pytest.raises(ValueError, match="unlinked regular file"):
        import_trace_as_scenario(
            missing,
            format="json",
            expectations_path=exp_file,
            scenario_id="reviewed-import-1",
            execution_mode="live",
            industry="finance",
            output_path=tmp_path / "out.json",
        )

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(_sample_recording()), encoding="utf-8")
    bad_exp = tmp_path / "bad_exp.json"
    bad_exp.write_text(
        json.dumps({"turn-1": _sample_expectations()["turn-1"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="every turn-N"):
        import_trace_as_scenario(
            trace_file,
            format="json",
            expectations_path=bad_exp,
            scenario_id="reviewed-import-1",
            execution_mode="live",
            industry="finance",
            output_path=tmp_path / "out2.json",
        )


@pytest.mark.asyncio
async def test_import_drift_cli_parser_and_handler(tmp_path, capsys):
    parser = cli.get_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import-drift", "--path", "trace.json"])

    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(_sample_recording()), encoding="utf-8")
    exp_file = tmp_path / "expectations.json"
    exp_file.write_text(json.dumps(_sample_expectations()), encoding="utf-8")
    output_file = tmp_path / "cli-draft.json"

    args = parser.parse_args(
        [
            "import-drift",
            "--input",
            str(trace_file),
            "--industry",
            "finance",
            "--format",
            "json",
            "--expectations",
            str(exp_file),
            "--scenario-id",
            "cli-import-1",
            "--execution-mode",
            "hybrid",
            "--output",
            str(output_file),
        ]
    )
    rc = await handle_import_drift(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scenario_id"] == "cli-import-1"
    assert output_file.is_file()

    # Re-running against existing output fails without overwriting
    rc_fail = await handle_import_drift(args)
    assert rc_fail == 1
