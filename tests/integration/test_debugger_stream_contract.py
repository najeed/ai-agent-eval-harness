"""
B5: Debugger SSE stream contract tests.

Locks the transport contract between the trace vault and the Live Debugger
against six failure-mode fixtures:

  replay    — Last-Event-ID catch-up resumes exactly after the acknowledged id
  reorder   — the server streams file order verbatim; it never reorders payloads
  loss      — sequence gaps are transported as-is (no synthesized fill events)
  retry     — per-attempt execution_graph_node events surface in emission order
  partial   — an unterminated trailing write is never broadcast mid-write
  recovered — master-log fallback filters by run_id and cleans its temp file

Every fixture terminates with a run_end line so generators exit deterministically.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner.console.app import create_app
from eval_runner.console.routes.runs import resolve_trace_path, tail_file_generator

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def ev_line(seq: int, name: str, **extra) -> str:
    payload = {"event": name, "_seq": seq, **extra}
    return json.dumps(payload)


def sse_frames(chunks, limit: int = 500):
    """Parses raw SSE chunks (str or bytes) into a list of (frame_id | None, parsed_data)."""
    frames = []
    for chunk in chunks:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        for block in chunk.split("\n\n"):
            block = block.strip()
            if not block or block.startswith(":"):
                continue
            frame_id = None
            data = None
            for ln in block.split("\n"):
                if ln.startswith("id: "):
                    frame_id = int(ln[4:])
                elif ln.startswith("data: "):
                    data = ln[6:]
            if data is None:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                parsed = {"_raw": data}
            frames.append((frame_id, parsed))
        if len(frames) >= limit:
            break
    return frames


@pytest.fixture
def run_log_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "runs"
    d.mkdir(parents=True)
    monkeypatch.setattr("eval_runner.console.routes.config.RUN_LOG_DIR", d)
    monkeypatch.setattr(config_module(), "RUN_LOG_DIR", d)
    return d


def config_module():
    import eval_runner.config as cfg

    return cfg


def write_vault(runs_dir: Path, run_id: str, lines: list[str]) -> Path:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    p = vault / "run.jsonl"
    p.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# replay — catch-up from Last-Event-ID
# ---------------------------------------------------------------------------


def test_contract_replay_resumes_after_last_event_id(run_log_dir):
    lines = [
        ev_line(1, "run_start"),
        ev_line(2, "execution_graph_node", scenario_node_id="node_a", status="running"),
        ev_line(3, "execution_graph_node", scenario_node_id="node_a", status="completed"),
        ev_line(4, "run_end"),
    ]
    write_vault(run_log_dir, "run-replay", lines)

    gen = tail_file_generator(
        run_log_dir / "run-replay" / "run.jsonl", "run-replay", last_event_id=2
    )
    frames = sse_frames(gen)

    # Only frames AFTER the acknowledged cursor are re-delivered.
    assert [f[0] for f in frames] == [3, 4]
    assert frames[0][1]["_seq"] == 3
    assert frames[-1][1]["event"] == "run_end"


# ---------------------------------------------------------------------------
# reorder — transport is verbatim; ordering truth is in _seq payloads
# ---------------------------------------------------------------------------


def test_contract_reorder_preserves_file_order_verbatim(run_log_dir):
    # Payloads written out of _seq order (retransmission artifact upstream).
    lines = [
        ev_line(4, "execution_graph_node", scenario_node_id="b", status="completed"),
        ev_line(2, "execution_graph_node", scenario_node_id="a", status="failed"),
        ev_line(3, "execution_graph_edge"),
        ev_line(1, "run_start"),
        ev_line(5, "run_end"),
    ]
    write_vault(run_log_dir, "run-reorder", lines)

    gen = tail_file_generator(run_log_dir / "run-reorder" / "run.jsonl", "run-reorder")
    frames = sse_frames(gen)

    # The stream NEVER silently reorders or drops: file order == wire order.
    assert [f[1]["_seq"] for f in frames] == [4, 2, 3, 1, 5]
    # Transport ids remain consecutive regardless of payload disorder.
    assert [f[0] for f in frames] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# loss — sequence gaps are transported without synthesis
# ---------------------------------------------------------------------------


def test_contract_loss_gaps_transported_without_synthesis(run_log_dir):
    lines = [
        ev_line(1, "run_start"),
        ev_line(2, "execution_graph_node", scenario_node_id="a", status="completed"),
        # _seq 3-5 lost upstream — must NOT be fabricated by the stream.
        ev_line(6, "execution_graph_node", scenario_node_id="a", status="failed"),
        ev_line(7, "run_end"),
    ]
    write_vault(run_log_dir, "run-loss", lines)

    gen = tail_file_generator(run_log_dir / "run-loss" / "run.jsonl", "run-loss")
    frames = sse_frames(gen)

    assert len(frames) == 4
    assert [f[1]["_seq"] for f in frames] == [1, 2, 6, 7]
    # Every frame originates from the vault; no synthesized filler events.
    assert all(f[1].get("event") != "synthetic_fill" for f in frames)


# ---------------------------------------------------------------------------
# retry — per-attempt canonical events surface in emission order
# ---------------------------------------------------------------------------


def test_contract_retry_attempts_surface_in_emission_order(run_log_dir):
    lines = [
        ev_line(1, "run_start"),
        ev_line(
            2,
            "execution_graph_node",
            scenario_node_id="flaky",
            execution_instance_id="flaky:attempt:1",
            status="failed",
            attempt=1,
            failure_class="TRANSIENT",
        ),
        ev_line(
            3,
            "execution_graph_edge",
            from_scenario_node_id="flaky",
            to_scenario_node_id="flaky",
            edge_type="retry",
        ),
        ev_line(
            4,
            "execution_graph_node",
            scenario_node_id="flaky",
            execution_instance_id="flaky:attempt:2",
            status="completed",
            attempt=2,
        ),
        ev_line(5, "run_end"),
    ]
    write_vault(run_log_dir, "run-retry", lines)

    gen = tail_file_generator(run_log_dir / "run-retry" / "run.jsonl", "run-retry")
    frames = sse_frames(gen)

    node_events = [f[1] for f in frames if f[1].get("event") == "execution_graph_node"]
    assert len(node_events) == 2
    # Failed attempt first, successful retry second — never collapsed.
    assert (node_events[0]["attempt"], node_events[0]["status"]) == (1, "failed")
    assert (node_events[1]["attempt"], node_events[1]["status"]) == (2, "completed")
    assert node_events[0]["failure_class"] == "TRANSIENT"
    assert node_events[0]["execution_instance_id"] != node_events[1]["execution_instance_id"]

    retry_edges = [f[1] for f in frames if f[1].get("edge_type") == "retry"]
    assert len(retry_edges) == 1


# ---------------------------------------------------------------------------
# partial — unterminated trailing writes are never broadcast mid-write
# ---------------------------------------------------------------------------


def test_contract_partial_write_never_broadcast_incomplete_frame(run_log_dir):
    vault = run_log_dir / "run-partial"
    vault.mkdir(parents=True)
    trace = vault / "run.jsonl"
    trace.write_text(
        "\n".join(
            [
                ev_line(1, "run_start"),
                ev_line(2, "execution_graph_node", scenario_node_id="a", status="running"),
                '{"event": "execution_graph_node", "_seq": 3, "scenario_node_i',  # torn write
            ]
        ),
        encoding="utf-8",
    )

    complete_rest = 'd": "a", "status": "completed"}\n' + ev_line(4, "run_end") + "\n"

    def _finish_writes():
        time.sleep(0.8)
        with open(trace, "a", encoding="utf-8") as f:
            f.write(complete_rest)

    finisher = threading.Thread(target=_finish_writes, daemon=True)
    finisher.start()

    gen = tail_file_generator(trace, "run-partial")
    frames = sse_frames(gen, limit=10)
    finisher.join(timeout=5)

    # Catch-up phase delivered ONLY the two complete historical frames.
    assert [f[1].get("_seq") for f in frames[:2]] == [1, 2]
    # The torn frame was completed by the writer and then delivered intact.
    resumed = [f for f in frames if f[1].get("_seq") == 3]
    assert len(resumed) == 1
    assert resumed[0][1]["scenario_node_id"] == "a"
    assert resumed[0][1]["status"] == "completed"
    # Stream terminated on the terminal event.
    assert frames[-1][1]["event"] == "run_end"


# ---------------------------------------------------------------------------
# recovered — master-log fallback filters by run_id and cleans up
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    app = create_app()
    app.config["TESTING"] = True
    api_key = "test-integration-key"
    with (
        patch("eval_runner.console.routes.config.DASHBOARD_API_KEY", api_key),
        patch("eval_runner.console.routes.config.SERVICE_API_KEY", api_key),
    ):
        with app.test_client() as client:
            client.environ_base["HTTP_X_AES_API_KEY"] = api_key
            yield client


def test_contract_recovered_master_log_fallback_filters_and_cleans(run_log_dir, api_client):
    other_run = [
        ev_line(1, "run_start", run_id="someone-else"),
        ev_line(2, "run_end", run_id="someone-else"),
    ]
    target_run = [
        ev_line(1, "run_start", run_id="run-lost-vault"),
        ev_line(
            2,
            "execution_graph_node",
            run_id="run-lost-vault",
            scenario_node_id="a",
            status="completed",
        ),
        ev_line(9, "run_end", run_id="run-lost-vault"),
    ]
    master = run_log_dir / "run.jsonl"
    master.write_text("".join(f"{ln}\n" for ln in (other_run + target_run)), encoding="utf-8")

    # Vault is gone; resolution falls through to the master log.
    assert resolve_trace_path("run-lost-vault") is None

    resp = api_client.get("/api/v1/runs/run-lost-vault/stream")
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    frames = sse_frames(resp.response)
    payloads = [f[1] for f in frames]

    # Strict run isolation: only the requested run's events cross the wire.
    assert all(p.get("run_id") == "run-lost-vault" for p in payloads)
    assert [p.get("_seq") for p in payloads] == [1, 2, 9]

    # The temporary extraction file must be cleaned up after streaming.
    leftovers = list(run_log_dir.glob("temp_stream_run-lost-vault.jsonl"))
    assert leftovers == []
