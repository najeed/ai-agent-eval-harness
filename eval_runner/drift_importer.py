"""Strict native-recording importer for AES v1.4 draft scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from .loader import get_scenario_validator

_SUPPORTED_FORMATS = {"json", "jsonl"}
_SUPPORTED_EXECUTION_MODES = {"live", "simulated", "hybrid"}
MAX_BYTES = 2 * 1024 * 1024
MAX_TURNS = 100


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key detected: {key!r}")
        obj[key] = value
    return obj


def _reject_non_finite_constant(token: str) -> Any:
    raise ValueError(f"Invalid non-finite JSON constant: {token!r}")


def _loads_strict_json(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON payload: {exc}") from exc


def _read_regular_file_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise ValueError(f"{label} must be an existing unlinked regular file: {path}")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"{label} exceeds maximum size of {MAX_BYTES} bytes: {path}")
    return data


def local_file(path: Path | str) -> bytes:
    """Read a bounded, unlinked regular local file."""
    return _read_regular_file_bytes(Path(path), "Input file")


def strict_json(payload: bytes) -> Any:
    """Decode UTF-8 bytes and parse strict JSON (rejecting duplicate keys/non-finite numbers)."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSON payload must be valid UTF-8: {exc}") from exc
    return _loads_strict_json(text)


def _extract_turns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    pending_request: dict[str, Any] | None = None

    for idx, event in enumerate(events):
        event_type = event.get("event")
        if event_type == "run_start":
            if event.get("scenario") != "recorded_session":
                raise ValueError(
                    f"run_start at event index {idx} must have scenario 'recorded_session'"
                )
        elif event_type == "agent_request":
            if pending_request is not None:
                raise ValueError(
                    f"Incomplete turn before event index {idx}: missing agent_response"
                )
            task = event.get("task")
            if not isinstance(task, str) or not task.strip():
                raise ValueError(
                    f"agent_request at event index {idx} must include a non-empty task string"
                )
            pending_request = event
        elif event_type == "agent_response":
            if pending_request is None:
                raise ValueError(
                    f"Orphan agent_response at event index {idx} without preceding agent_request"
                )
            if not isinstance(event.get("content"), dict):
                raise ValueError(
                    f"agent_response at event index {idx} must include a content object"
                )
            turns.append(pending_request)
            pending_request = None

    if pending_request is not None:
        raise ValueError("Incomplete turn at end of recording: missing agent_response")
    if not turns:
        raise ValueError(
            "Recording must contain at least one complete agent_request/agent_response turn"
        )

    return turns


def recording_turns(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate non-empty recording event dicts and extract completed turns."""
    if not events or not all(isinstance(item, dict) for item in events):
        raise ValueError("Recording must be a non-empty sequence of event objects")
    turns = _extract_turns(events)
    if len(turns) > MAX_TURNS:
        raise ValueError(f"Recording exceeds maximum turn count of {MAX_TURNS}")
    return events, turns


def parse_recording(payload: bytes, fmt: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse and strictly validate a native recording payload in JSON or JSONL format."""
    if len(payload) > MAX_BYTES:
        raise ValueError(f"Recording payload exceeds maximum size of {MAX_BYTES} bytes")
    if fmt not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported recording format {fmt!r}; expected one of {sorted(_SUPPORTED_FORMATS)}"
        )

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Recording payload must be valid UTF-8: {exc}") from exc

    if fmt == "json":
        parsed = _loads_strict_json(text)
        if not isinstance(parsed, list):
            raise ValueError("JSON recording must be a top-level array of event objects")
        events = parsed
    else:
        events = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            item = _loads_strict_json(stripped)
            if not isinstance(item, dict):
                raise ValueError("Each JSONL recording line must decode to a JSON object")
            events.append(item)

    return recording_turns(events)


def serialize_draft(draft: dict[str, Any]) -> bytes:
    """Serialize a draft scenario deterministically to UTF-8 JSON bytes."""
    return (json.dumps(draft, indent=2) + "\n").encode("utf-8")


def publish_draft(output_path: str | Path, content: bytes) -> Path:
    """Atomically write a draft artifact without overwriting an existing file."""
    path = Path(output_path)
    if path.is_symlink():
        raise ValueError(f"Output path must not be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(content)
    return path


def _validate_expectations_obj(data: Any, turn_count: int) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise ValueError("Expectations must be a JSON object mapping every turn-N key")

    expected_keys = {f"turn-{idx}" for idx in range(1, turn_count + 1)}
    if set(data.keys()) != expected_keys:
        raise ValueError("Expectations must provide assertions for every turn-N in the recording")

    validated: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(expected_keys, key=lambda k: int(k.split("-", 1)[1])):
        assertions = data[key]
        if (
            not isinstance(assertions, list)
            or not assertions
            or not all(isinstance(item, dict) for item in assertions)
        ):
            raise ValueError(
                f"Expectations for {key} must be a non-empty list of assertion objects"
            )
        validated[key] = assertions
    return validated


def _parse_expectations(payload: bytes, turn_count: int) -> dict[str, list[dict[str, Any]]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Expectations payload must be valid UTF-8: {exc}") from exc

    return _validate_expectations_obj(_loads_strict_json(text), turn_count)


def build_recording_scenario(
    events: list[dict[str, Any]],
    expectations_data: Any,
    *,
    scenario_id: str,
    execution_mode: str,
    industry: str = "general",
    description: str = "Imported strict native recording",
) -> dict[str, Any]:
    """Build and AES-validate a draft scenario from parsed recording events and expectations."""
    if execution_mode not in _SUPPORTED_EXECUTION_MODES:
        supported = sorted(_SUPPORTED_EXECUTION_MODES)
        raise ValueError(
            f"Unsupported execution_mode {execution_mode!r}; expected one of {supported}"
        )
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("scenario_id must be a non-empty string")

    _, turns = recording_turns(events)
    expectations = _validate_expectations_obj(expectations_data, len(turns))

    nodes = [
        {
            "id": f"turn-{idx}",
            "task_description": req["task"],
            "expected_outcome": expectations[f"turn-{idx}"],
        }
        for idx, req in enumerate(turns, start=1)
    ]
    edges = [{"from": f"turn-{idx}", "to": f"turn-{idx + 1}"} for idx in range(1, len(turns))]

    scenario = {
        "aes_version": 1.4,
        "industry": industry,
        "use_case": "production_replay",
        "description": description,
        "metadata": {
            "id": scenario_id,
            "name": f"Imported Drift: {scenario_id}",
            "compliance_level": "Standard",
            "execution_mode": execution_mode,
            "recorded_history": events,
        },
        "workflow": {
            "nodes": nodes,
            "edges": edges,
        },
        "evaluation": {},
    }
    try:
        get_scenario_validator().validate(scenario)
    except ValidationError as exc:
        raise ValueError(f"Generated scenario failed schema validation: {exc.message}") from exc
    return scenario


def import_trace_as_scenario(
    trace_path: Path,
    *,
    format: str,
    expectations_path: Path,
    scenario_id: str,
    execution_mode: str,
    industry: str,
    output_path: Path,
) -> dict[str, Any]:
    """Compile a strict native recording and turn expectations into a draft AES v1.4 scenario."""
    if output_path.is_symlink():
        raise ValueError(f"Output path must not be a symlink: {output_path}")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")

    trace_bytes = _read_regular_file_bytes(trace_path, "Trace file")
    exp_bytes = _read_regular_file_bytes(expectations_path, "Expectations file")

    events, turns = parse_recording(trace_bytes, format)
    scenario = build_recording_scenario(
        events,
        strict_json(exp_bytes),
        scenario_id=scenario_id,
        execution_mode=execution_mode,
        industry=industry,
        description=f"Imported strict native recording from {trace_path.name}",
    )
    publish_draft(output_path, serialize_draft(scenario))

    return {
        "operation": "import",
        "state": "draft",
        "turns": len(turns),
        "scenario_id": scenario_id,
        "execution_mode": execution_mode,
        "industry": industry,
        "output_path": str(output_path),
    }
