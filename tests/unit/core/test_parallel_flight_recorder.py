import asyncio

import pytest

from eval_runner.context import EvaluationContext
from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin as FlightRecorder
from eval_runner.reference.local_run_store import LocalFileRunStore


@pytest.mark.asyncio
async def test_parallel_flight_recorder_forensics(tmp_path, monkeypatch):
    """
    Verify that parallel evaluations produce independent,
    sequentially contiguous logs without handle collisions.
    """
    store = LocalFileRunStore(tmp_path)
    fr = FlightRecorder(run_store=store)

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
    run1_events = store.get_events(run1_id, offset=0, limit=100)
    assert len(run1_events) == 11  # 1 START + 10 STEPS
    # Check sequence numbers (Should be 1..11)
    seqs = [e["_seq"] for e in run1_events]
    assert seqs == list(range(1, 12))

    # Verification: Run 2
    run2_events = store.get_events(run2_id, offset=0, limit=100)
    assert len(run2_events) == 11
    seqs2 = [e["_seq"] for e in run2_events]
    assert seqs2 == list(range(1, 12))

    # No shared master projection exists: each provider stream remains isolated.
    assert {event["run_id"] for event in run1_events} == {run1_id}
    assert {event["run_id"] for event in run2_events} == {run2_id}
