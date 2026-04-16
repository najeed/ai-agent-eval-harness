import datetime
from unittest.mock import MagicMock

import pytest

from eval_runner.trace_utils import AESJsonEncoder, load_events, reconstruct_results_from_events


def test_aes_json_encoder_extended(tmp_path):
    """Test AESJsonEncoder with Path, datetime, and fallback types."""
    encoder = AESJsonEncoder()

    # Path (Handle Windows vs Unix separators)
    p = tmp_path / "test"
    assert encoder.default(p) == str(p)

    # datetime/date
    dt = datetime.datetime(2026, 4, 15, 12, 0, tzinfo=datetime.UTC)
    assert encoder.default(dt) == dt.isoformat()
    d = datetime.date(2026, 4, 15)
    assert encoder.default(d) == d.isoformat()

    # Mock
    mock_obj = MagicMock(_mock_name="test_mock")
    assert "Mock" in encoder.default(mock_obj)

    # Fallback to str for non-serializable
    class Unserializable:
        def __str__(self):
            return "unserializable_obj"

    assert encoder.default(Unserializable()) == "unserializable_obj"


def test_load_events_errors(tmp_path):
    """Test load_events error paths and edge cases."""
    # 1. File Not Found
    with pytest.raises(FileNotFoundError):
        load_events(tmp_path / "ghost.json")

    # 2. Empty file
    empty = tmp_path / "empty.json"
    empty.write_text("   ", encoding="utf-8")
    assert load_events(empty) == []


def test_load_events_formats(tmp_path):
    """Test load_events with various JSON formats."""
    # 1. Standard JSON Array
    f1 = tmp_path / "f1.json"
    f1.write_text('[{"event": "start"}, {"event": "stop"}]')
    events = load_events(f1)
    assert len(events) == 2

    # 2. Single JSON object (Standard JSON array but just one)
    # This hits lines 41-45
    f2 = tmp_path / "f2.json"
    f2.write_text('{"event": "start"}')
    events = load_events(f2)
    assert len(events) == 1

    # 3. Corrupt starting with '[' but not a list (Fallback to JSONL)
    f3_corrupt = tmp_path / "f3_corrupt.json"
    f3_corrupt.write_text('[{"event": "oops"}\n{"event": "valid"}')
    events = load_events(f3_corrupt)
    assert len(events) == 1
    assert events[0]["event"] == "valid"

    # 3. No valid events
    f3 = tmp_path / "f3.json"
    f3.write_text("invalid data\nmore junk")
    with pytest.raises(ValueError, match="No valid JSON events"):
        load_events(f3)


def test_reconstruct_results_coverage():
    """Test reconstruction with evaluation, agent, and tool events."""
    events = [
        {"task_id": "T1", "event": "evaluation", "metric": "safety", "value": 0.9, "success": True},
        {"task_id": "T1", "event": "agent_response", "content": "I am an agent"},
        {"task_id": "T1", "event": "tool_result", "tool": "search", "status": "success"},
    ]

    results = reconstruct_results_from_events(events)
    assert len(results) == 1
    res = results[0]
    assert res["task_id"] == "T1"
    assert len(res["metrics"]) == 1
    assert res["metrics"][0]["score"] == 0.9
    assert len(res["conversation_history"]) == 2
    assert res["conversation_history"][0]["role"] == "agent"
    assert res["conversation_history"][1]["role"] == "user"
    assert res["conversation_history"][1]["content"]["action"] == "search"
