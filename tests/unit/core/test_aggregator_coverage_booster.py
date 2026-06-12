import builtins
import importlib
import json
from pathlib import Path
from unittest.mock import patch

from eval_runner.publication_suite import aggregator
from eval_runner.publication_suite.aggregator import Aggregator


def test_aggregator_import_fallback():
    """Verify sys.path fallback when FailureTaxonomy fails to import directly."""
    orig_import = builtins.__import__
    import_calls = 0

    def mock_import(name, *args, **kwargs):
        nonlocal import_calls
        if "eval_runner.taxonomy" in name:
            import_calls += 1
            if import_calls == 1:
                raise ImportError("Mocked import error")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", mock_import):
        importlib.reload(aggregator)
        assert aggregator.FailureTaxonomy is not None


def test_aggregator_duration_edge_cases(tmp_path):
    """Test parse_ts formatting, negative durations, and parsing exceptions."""
    # Write config file
    suite_dir = Path(__file__).parent.parent.parent.parent / "eval_runner" / "publication_suite"
    suite_dir.mkdir(parents=True, exist_ok=True)
    config_yaml = suite_dir / "config.yaml"
    if not config_yaml.exists():
        config_yaml.write_text(
            "confidence_level: 0.95\npricing:\n  test_agent: 1.0\n", encoding="utf-8"
        )

    # Create dummy manifest
    manifest_data = {
        "fingerprint": "test_batch",
        "agent_name": "test_agent",
        "base_dir": str(tmp_path),
        "runs": [
            {
                "success": True,
                "scenario": "scenario_1",
                "log_path": str(tmp_path / "run1.jsonl"),
            }
        ],
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # 1. Test negative duration (clock drift) and empty line stripping
    log_content = (
        '{"event": "run_start", "timestamp": "2026-06-13T02:00:00.000000Z"}\n'
        "\n"  # Empty line to cover line.strip() check
        '{"event": "agent_response", "content": "hello world"}\n'
        '{"event": "run_end", "timestamp": "2026-06-13T01:59:00.000000Z"}\n'  # Negative duration
    )
    run_log = tmp_path / "run1.jsonl"
    run_log.write_text(log_content, encoding="utf-8")

    agg = Aggregator(str(manifest_file))
    agg.process()

    # Verify duration fell back to 2.5
    aggregated_file = tmp_path / "aggregated_results.json"
    assert aggregated_file.exists()
    report = json.loads(aggregated_file.read_text(encoding="utf-8"))
    assert report["scenarios"]["scenario_1"]["avg_latency"] == 2.5

    # 2. Test parsing formats: date-only, time-only, space-separated, invalid format, and exception
    log_content_formats = (
        '{"event": "run_start", "timestamp": "2026-06-13 02:00:00"}\n'
        '{"event": "run_end", "timestamp": "2026-06-13 02:00:10"}\n'
    )
    run_log.write_text(log_content_formats, encoding="utf-8")
    agg = Aggregator(str(manifest_file))
    agg.process()
    report = json.loads(aggregated_file.read_text(encoding="utf-8"))
    assert report["scenarios"]["scenario_1"]["avg_latency"] == 10.0

    # Date-only and Time-only formats
    log_content_date_time = (
        '{"event": "run_start", "timestamp": "2026-06-13"}\n'
        '{"event": "run_end", "timestamp": "2026-06-14"}\n'
    )
    run_log.write_text(log_content_date_time, encoding="utf-8")
    agg = Aggregator(str(manifest_file))
    agg.process()
    report = json.loads(aggregated_file.read_text(encoding="utf-8"))
    assert report["scenarios"]["scenario_1"]["avg_latency"] == 86400.0

    # Invalid timestamp format (returns None)
    log_content_invalid = (
        '{"event": "run_start", "timestamp": "invalid-ts"}\n'
        '{"event": "run_end", "timestamp": "invalid-ts"}\n'
    )
    run_log.write_text(log_content_invalid, encoding="utf-8")
    agg = Aggregator(str(manifest_file))
    agg.process()
    report = json.loads(aggregated_file.read_text(encoding="utf-8"))
    assert report["scenarios"]["scenario_1"]["avg_latency"] == 2.5

    # Exception during parsing (e.g. timestamp is None/list causing TypeError in str operations)
    class BadStr:
        def __str__(self):
            raise TypeError("Forced string conversion failure")

    log_content_err = (
        '{"event": "run_start", "timestamp": "2026-06-13T02:00:00"}\n'
        '{"event": "run_end", "timestamp": "2026-06-13T02:00:10"}\n'
    )
    run_log.write_text(log_content_err, encoding="utf-8")

    orig_next = builtins.next

    def mock_next(iterator, default=None):
        item = orig_next(iterator, default)
        if isinstance(item, dict) and item.get("event") == "run_start":
            return {"event": "run_start", "timestamp": BadStr()}
        return item

    with patch("builtins.next", mock_next):
        agg = Aggregator(str(manifest_file))
        agg.process()
        report = json.loads(aggregated_file.read_text(encoding="utf-8"))
        assert report["scenarios"]["scenario_1"]["avg_latency"] == 2.5
