"""Strict native-recording importer for AES v1.4 draft scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .loader import get_scenario_validator

_SUPPORTED_FORMATS = {"json", "jsonl"}
_SUPPORTED_EXECUTION_MODES = {"live", "simulated", "hybrid"}


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
    return path.read_bytes()


def _extract_turns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    pending_request: dict[str, Any] | None = None

    for idx, event in enumerate(events):
        event_type = event.get("event")
        if event_type == "agent_request":
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
            turns.append(pending_request)
            pending_request = None

    if pending_request is not None:
        raise ValueError("Incomplete turn at end of recording: missing agent_response")
    if not turns:
        raise ValueError(
            "Recording must contain at least one complete agent_request/agent_response turn"
        )

    return turns


def parse_recording(payload: bytes, fmt: str) -> list[dict[str, Any]]:
    """Parse and strictly validate a native recording payload in JSON or JSONL format."""
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

    if not events or not all(isinstance(item, dict) for item in events):
        raise ValueError("Recording must be a non-empty sequence of event objects")

    _extract_turns(events)
    return events


def publish_draft(output_path: Path, content: bytes) -> Path:
    """Atomically write a draft artifact without overwriting an existing file."""
    if output_path.is_symlink():
        raise ValueError(f"Output path must not be a symlink: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "xb") as handle:
        handle.write(content)
    return output_path


def _parse_expectations(payload: bytes, turn_count: int) -> dict[str, list[dict[str, Any]]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Expectations payload must be valid UTF-8: {exc}") from exc

    data = _loads_strict_json(text)
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
    if execution_mode not in _SUPPORTED_EXECUTION_MODES:
        supported = sorted(_SUPPORTED_EXECUTION_MODES)
        raise ValueError(
            f"Unsupported execution_mode {execution_mode!r}; expected one of {supported}"
        )
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("scenario_id must be a non-empty string")
    if output_path.is_symlink():
        raise ValueError(f"Output path must not be a symlink: {output_path}")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")

    trace_bytes = _read_regular_file_bytes(trace_path, "Trace file")
    exp_bytes = _read_regular_file_bytes(expectations_path, "Expectations file")

    events = parse_recording(trace_bytes, format)
    turns = _extract_turns(events)
    expectations = _parse_expectations(exp_bytes, len(turns))

    nodes = []
    for idx, req in enumerate(turns, start=1):
        turn_id = f"turn-{idx}"
        nodes.append(
            {
                "id": turn_id,
                "task_description": req["task"],
                "expected_outcome": expectations[turn_id],
            }
        )

    edges = [{"from": f"turn-{idx}", "to": f"turn-{idx + 1}"} for idx in range(1, len(turns))]

    scenario = {
        "aes_version": 1.4,
        "industry": industry,
        "use_case": "production_replay",
        "description": f"Imported strict native recording from {trace_path.name}",
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

    get_scenario_validator().validate(scenario)
    encoded = (json.dumps(scenario, indent=2) + "\n").encode("utf-8")
    publish_draft(output_path, encoded)

    return {
        "operation": "import",
        "state": "draft",
        "turns": len(turns),
        "scenario_id": scenario_id,
        "execution_mode": execution_mode,
        "industry": industry,
        "output_path": str(output_path),
    }
