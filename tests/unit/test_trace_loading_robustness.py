import pytest
import json
from pathlib import Path
from eval_runner.trace_utils import load_events

def test_load_events_robustness(tmp_path):
    """Verify that load_events correctly handles various trace formats and edge cases."""
    
    # 1. Standard JSONL
    jsonl_path = tmp_path / "standard.jsonl"
    events = [{"event": "start"}, {"event": "end"}]
    jsonl_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert load_events(jsonl_path) == events
    
    # 2. JSON Array Format
    json_path = tmp_path / "array.json"
    json_path.write_text(json.dumps(events), encoding="utf-8")
    assert load_events(json_path) == events

    # 3. Empty Trace
    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")
    assert load_events(empty_path) == []

    # 4. Malformed Lines (Skipping)
    malformed_path = tmp_path / "malformed.jsonl"
    malformed_path.write_text('{"event": "good"}\n{invalid_json}\n{"event": "also_good"}', encoding="utf-8")
    loaded = load_events(malformed_path)
    assert len(loaded) == 2
    assert loaded[0]["event"] == "good"
    assert loaded[1]["event"] == "also_good"

    # 5. Non-UTF-8 Characters (Graceful Resilience)
    # Since we use encoding="utf-8", we'll check if a file with BOM or similar is handled.
    b_path = tmp_path / "bom.jsonl"
    content = b'\xef\xbb\xbf{"event": "utf8_bom"}\n'
    with open(b_path, "wb") as f:
        f.write(content)
    # The 'utf-8' encoding usually handles BOM for files, or we can check with replace errors.
    loaded = load_events(b_path)
    assert loaded[0]["event"] == "utf8_bom"
