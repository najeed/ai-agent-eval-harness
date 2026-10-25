"""Provider-native debugger SSE transport contract tests.

The console consumes only the RunStorageProvider stream-events contract. Former
file-tail fixtures are represented as already-persisted provider events, so the
same wire guarantees are tested without a vault, master log, or trace path.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from flask import Flask

import eval_runner.console.routes.runs as runs


def event(seq: int, name: str, **extra):
    return {"event": name, "_seq": seq, **extra}


def sse_frames(chunks):
    frames = []
    for chunk in chunks:
        for block in chunk.split("\n\n"):
            block = block.strip()
            if not block or block.startswith(":"):
                continue
            frame_id = None
            data = None
            for line in block.split("\n"):
                if line.startswith("id: "):
                    frame_id = int(line[4:])
                elif line.startswith("data: "):
                    data = line[6:]
            if data is not None:
                frames.append((frame_id, json.loads(data)))
    return frames


class EventProvider:
    def __init__(self, events, *, status="RUNNING", exists=True):
        self.events = list(events)
        self.status = status
        self.exists = exists
        self.requests = []

    def get_run(self, run_id, context=None):
        self.requests.append(("get_run", run_id, context))
        return {"run_id": run_id, "status": self.status} if self.exists else None

    def stream_events(self, run_id, from_seq=0, context=None):
        self.requests.append(("stream_events", run_id, from_seq, context))
        yield from self.events[from_seq:]

    def get_events(self, run_id, offset=0, limit=1000, context=None):
        self.requests.append(("get_events", run_id, offset, limit, context))
        return self.events[offset : offset + limit]

    def get_manifest(self, run_id, context=None):
        return None


@pytest.fixture
def app():
    value = Flask(__name__)
    value.secret_key = "debugger-contract"
    return value


@pytest.fixture
def scope():
    return {"org_id": "acme", "tenant_id": "t1", "workspace_id": "w1"}


def stream(app, provider, run_id, *, query="", headers=None, scope=None):
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        with app.test_request_context("/" + query, headers=headers):
            response = runs.stream_run_logs.__wrapped__(run_id)
            return sse_frames(response.response)


def test_contract_replay_resumes_after_last_event_id(app, scope):
    provider = EventProvider(
        [
            event(1, "run_start"),
            event(2, "execution_graph_node"),
            event(3, "execution_graph_node"),
            event(4, "run_end"),
        ]
    )
    frames = stream(app, provider, "run-replay", headers={"Last-Event-ID": "2"}, scope=scope)
    assert [frame[0] for frame in frames] == [3, 4]
    assert [frame[1]["_seq"] for frame in frames] == [3, 4]


def test_reconnect_uses_transport_cursor_not_forensic_sequence(app, scope):
    provider = EventProvider([event(42, "run_start"), event(108, "run_end")])
    first = stream(app, provider, "opaque", scope=scope)
    assert [frame[0] for frame in first] == [1, 2]
    assert [frame[1]["_seq"] for frame in first] == [42, 108]
    assert stream(app, provider, "opaque", headers={"Last-Event-ID": "2"}, scope=scope) == []


def test_contract_reorder_preserves_provider_order_verbatim(app, scope):
    provider = EventProvider(
        [
            event(4, "execution_graph_node"),
            event(2, "execution_graph_node"),
            event(3, "execution_graph_edge"),
            event(1, "run_start"),
            event(5, "run_end"),
        ]
    )
    frames = stream(app, provider, "reorder", scope=scope)
    assert [frame[1]["_seq"] for frame in frames] == [4, 2, 3, 1, 5]
    assert [frame[0] for frame in frames] == [1, 2, 3, 4, 5]


def test_contract_loss_gaps_are_transported_without_synthesis(app, scope):
    provider = EventProvider(
        [
            event(1, "run_start"),
            event(2, "execution_graph_node"),
            event(6, "execution_graph_node"),
            event(7, "run_end"),
        ]
    )
    frames = stream(app, provider, "loss", scope=scope)
    assert [frame[1]["_seq"] for frame in frames] == [1, 2, 6, 7]
    assert all(frame[1]["event"] != "synthetic_fill" for frame in frames)


def test_contract_retry_attempts_surface_in_provider_emission_order(app, scope):
    provider = EventProvider(
        [
            event(1, "run_start"),
            event(
                2,
                "execution_graph_node",
                execution_instance_id="flaky:1",
                status="failed",
                attempt=1,
                failure_class="TRANSIENT",
            ),
            event(3, "execution_graph_edge", edge_type="retry"),
            event(
                4,
                "execution_graph_node",
                execution_instance_id="flaky:2",
                status="completed",
                attempt=2,
            ),
            event(5, "run_end"),
        ]
    )
    frames = stream(app, provider, "retry", scope=scope)
    nodes = [item for _, item in frames if item["event"] == "execution_graph_node"]
    assert [(item["attempt"], item["status"]) for item in nodes] == [
        (1, "failed"),
        (2, "completed"),
    ]
    assert nodes[0]["failure_class"] == "TRANSIENT"
    assert nodes[0]["execution_instance_id"] != nodes[1]["execution_instance_id"]
    assert len([item for _, item in frames if item.get("edge_type") == "retry"]) == 1


def test_contract_strategy_end_does_not_truncate_multistage_run(app, scope):
    provider = EventProvider(
        [
            event(1, "run_start"),
            event(2, "execution_graph_node"),
            event(3, "strategy_end"),
            event(4, "execution_graph_node"),
            event(5, "execution_graph_edge"),
            event(6, "execution_graph_node"),
            event(7, "run_end"),
        ]
    )
    frames = stream(app, provider, "multi-stage", scope=scope)
    assert [item["_seq"] for _, item in frames] == [1, 2, 3, 4, 5, 6, 7]
    assert frames[-1][1]["event"] == "run_end"


def test_contract_partial_write_is_represented_only_after_provider_commits_event(app, scope):
    provider = EventProvider(
        [
            event(1, "run_start"),
            event(2, "execution_graph_node", status="running"),
            event(3, "execution_graph_node", scenario_node_id="a", status="completed"),
            event(4, "run_end"),
        ]
    )
    frames = stream(app, provider, "partial", scope=scope)
    assert [item["_seq"] for _, item in frames] == [1, 2, 3, 4]
    committed = [item for _, item in frames if item["_seq"] == 3]
    assert committed == [event(3, "execution_graph_node", scenario_node_id="a", status="completed")]


def test_contract_provider_scope_filters_other_run_data(app, scope):
    target = [
        event(1, "run_start", run_id="target"),
        event(2, "execution_graph_node", run_id="target"),
        event(9, "run_end", run_id="target"),
    ]
    provider = EventProvider(target)
    frames = stream(app, provider, "target", scope=scope)
    assert all(item["run_id"] == "target" for _, item in frames)
    assert [item["_seq"] for _, item in frames] == [1, 2, 9]
    assert ("stream_events", "target", 0, scope) in provider.requests


def test_paused_hitl_run_closes_stream_with_explicit_control_frame(app, scope):
    provider = EventProvider([event(1, "hitl_pause")], status="PAUSED_FOR_APPROVAL")
    frames = stream(app, provider, "paused", scope=scope)
    assert frames[0] == (1, event(1, "hitl_pause"))
    assert frames[-1] == (None, {"event": "paused_for_approval", "status": "PAUSED_FOR_APPROVAL"})


def test_dead_registered_run_with_no_events_closes_without_filesystem_recovery(app, scope):
    provider = EventProvider([], status="RUNNING")
    with patch.object(runs, "is_run_alive", return_value=False):
        frames = stream(app, provider, "without-events", scope=scope)
    assert frames == []


def test_dead_provisional_run_reports_stalled_not_launch_time_running(app, scope):
    provider = EventProvider([], status="RUNNING")
    provider.get_run = lambda run_id, context=None: {
        "run_id": run_id,
        "status": "RUNNING",
        "provisional": True,
    }
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
        patch.object(runs, "is_run_alive", return_value=False),
    ):
        with app.test_request_context("/"):
            response = runs.get_run_status.__wrapped__("provisional")
    assert response.get_json()["status"] == "STALLED"
