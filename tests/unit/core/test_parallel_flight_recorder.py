import asyncio
import json

import pytest

from eval_runner.context import EvaluationContext
from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin as FlightRecorder


@pytest.mark.asyncio
async def test_parallel_flight_recorder_forensics(tmp_path, monkeypatch):
    """
    Verify that parallel evaluations produce independent,
    sequentially contiguous logs without handle collisions.
    """
    monkeypatch.setenv("RUN_LOG_DIR", str(tmp_path))
    fr = FlightRecorder()
    fr.per_run = True
    fr.master = True
    fr.master_log_path = tmp_path / "run.jsonl"

    run1_id = "parallel-run-1"
    run2_id = "parallel-run-2"

    async def simulate_run(run_id, event_count):
        # 1. RUN_START
        fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": run_id}))

        # 2. Sequential events
        for i in range(event_count):
            fr.handle_event(Event(name="AGENT_STEP", data={"run_id": run_id, "step": i}))
            await asyncio.sleep(0.01)  # Simulate some work

        # 3. Finalize via hook
        ctx = EvaluationContext(identifier="scen", scenario_data={}, run_id=run_id)
        fr.after_evaluation(ctx, [])

    # Run concurrently
    await asyncio.gather(simulate_run(run1_id, 10), simulate_run(run2_id, 10))

    # Verification: Run 1
    run1_log = tmp_path / run1_id / "run.jsonl"
    assert run1_log.exists()
    run1_events = [json.loads(line) for line in run1_log.read_text().splitlines()]
    assert len(run1_events) == 11  # 1 START + 10 STEPS
    # Check sequence numbers (Should be 1..11)
    seqs = [e["_seq"] for e in run1_events]
    assert seqs == list(range(1, 12))

    # Verification: Run 2
    run2_log = tmp_path / run2_id / "run.jsonl"
    assert run2_log.exists()
    run2_events = [json.loads(line) for line in run2_log.read_text().splitlines()]
    assert len(run2_events) == 11
    seqs2 = [e["_seq"] for e in run2_events]
    assert seqs2 == list(range(1, 12))

    # Verification: Master Log (Should have all 22 events)
    assert fr.master_log_path.exists()
    master_events = [json.loads(line) for line in fr.master_log_path.read_text().splitlines()]
    assert len(master_events) == 22

    # Sequence numbers in master should be 1..22 (globally incremented since they share the lock)
    # Cleanup Verification
    # after_evaluation should have closed the run-specific handles
    # we want to make sure the run-specific handles are gone from fr._handles
    assert str(run1_log) not in fr._handles
    assert str(run2_log) not in fr._handles
    assert str(fr.master_log_path) in fr._handles  # Master remains open
