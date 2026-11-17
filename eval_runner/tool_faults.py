"""Task-local tool fault execution and acknowledgement at the consumer boundary."""

import asyncio
import copy
import json
import math
import random
import time
import uuid
from contextvars import ContextVar

from eval_runner.mutation_evidence import evidence_hash


class ToolFaultExecutor:
    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.pending = ContextVar(f"tool_delivery_{id(self)}", default=None)
        self.cache = {}
        self.sequences = {}

    @property
    def controller(self):
        return self.sandbox.fault_controller

    def ticket(self, fault, plan, kind, observation):
        identity = self.controller._identity(
            fault, plan.get("node_id"), plan.get("execution_instance_id")
        )
        ref = self.controller._observe(kind, identity, observation)
        ticket = {"identity": identity, "refs": [ref], "observed": observation, "applicable": True}
        self.pending.get()["tickets"].append(ticket)
        return ticket

    async def execute(self, data, operation):
        plan = {}
        if self.sandbox.plugin_manager:
            result = self.sandbox.plugin_manager.trigger_interceptor(
                "on_tool_execution", self.sandbox, data
            )
            if isinstance(result, dict):
                plan = result.get("fault_plan", {})
        selected_flags = {
            "timeout_boundary_ms",
            "injected_latency_ms",
            "replay_previous_event",
            "duplicate_execution",
            "raw_payload_corrupted",
            "tool_response_corrupted",
        }
        if not selected_flags.intersection(plan):
            self.pending.set(None)
            return await operation(
                tool_name=data["tool_name"], params=data["params"], agent_name=data["agent_name"]
            )
        key = evidence_hash({"tool": data["tool_name"], "params": data["params"]})
        context = {"tickets": [], "key": key, "plan": plan, "tool": data["tool_name"]}
        self.pending.set(context)
        sequence_key = (plan.get("node_id"), plan.get("execution_instance_id"), key)
        sequence = self.sequences.get(sequence_key, 0) + 1
        self.sequences[sequence_key] = sequence
        timeout_ms = plan.get("timeout_boundary_ms")
        latency_ms = plan.get("injected_latency_ms", 0)
        if timeout_ms is not None and (
            type(timeout_ms) not in (int, float) or not math.isfinite(timeout_ms) or timeout_ms <= 0
        ):
            raise ValueError("Tool deadline must be a positive duration")
        if type(latency_ms) not in (int, float) or not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("Tool latency must be nonnegative")
        replay = plan.get("replay_previous_event")
        duplicate = plan.get("duplicate_execution")
        execution_tickets = {}
        for fault, selected in (
            ("tool_replay", replay),
            ("tool_duplicate", duplicate),
            ("timeout_boundary", timeout_ms is not None),
            ("latency_jitter", bool(latency_ms) and timeout_ms is None),
        ):
            if not selected:
                continue
            execution_tickets[fault] = self.ticket(
                fault,
                plan,
                "tool_execution_requested",
                {
                    "tool": data["tool_name"],
                    "request_hash": key,
                    "timeout_ms": timeout_ms,
                    "latency_ms": latency_ms,
                },
            )

        def observe(kind, row):
            for ticket in execution_tickets.values():
                ticket["refs"].append(self.controller._observe(kind, ticket["identity"], row))

        completed_invocations = []

        async def invoke():
            invocation = uuid.uuid4().hex
            observe("tool_invocation_started", {"invocation_id": invocation, "request_hash": key})
            value = await operation(
                tool_name=data["tool_name"], params=data["params"], agent_name=data["agent_name"]
            )
            observe(
                "tool_invocation_completed",
                {"invocation_id": invocation, "result_hash": evidence_hash(value)},
            )
            completed_invocations.append(invocation)
            return value

        if replay and key in self.cache:
            source = self.cache[key]
            value = copy.deepcopy(source["payload"])
            observe(
                "tool_response_replayed",
                {
                    "source_ref": source["ref"],
                    "payload_hash": evidence_hash(value),
                    "request_hash": key,
                    "tool_dispatched": False,
                },
            )
            for fault, ticket in execution_tickets.items():
                if fault != "tool_replay":
                    ticket["applicable"] = False
        else:
            if replay:
                execution_tickets["tool_replay"]["applicable"] = False
            delay = latency_ms / 1000
            if latency_ms and timeout_ms is None:
                seed = evidence_hash(
                    {
                        "seed": plan.get("seed", 0),
                        "node": plan.get("node_id"),
                        "request": key,
                        "call": sequence,
                    }
                )
                delay *= random.Random(seed).uniform(0.5, 1.5)

            async def response():
                value = await invoke()
                if duplicate:
                    value = await invoke()
                if delay:
                    start = time.monotonic()
                    await asyncio.sleep(delay)
                    observe(
                        "tool_delay_elapsed",
                        {"requested_seconds": delay, "elapsed_seconds": time.monotonic() - start},
                    )
                return value

            if timeout_ms is not None:
                started = time.monotonic()
                task = asyncio.create_task(response())
                try:
                    value = await asyncio.wait_for(task, timeout_ms / 1000)
                except TimeoutError:
                    elapsed = time.monotonic() - started
                    if not task.cancelled():
                        # An operation's own TimeoutError is not evidence that
                        # the runtime deadline expired or cancelled its task.
                        raise
                    observe(
                        "tool_deadline_expired",
                        {
                            "timeout_ms": timeout_ms,
                            "elapsed_seconds": elapsed,
                            "task_cancelled": task.cancelled(),
                            "response_withheld": True,
                        },
                    )
                    value = {
                        "status": "error",
                        "error": f"DeadlineExceeded: tool response exceeded {timeout_ms}ms",
                        "fault": "timeout_boundary",
                    }
                else:
                    execution_tickets["timeout_boundary"]["applicable"] = False
            else:
                value = await response()
        if duplicate:
            execution_tickets["tool_duplicate"]["applicable"] = len(completed_invocations) == 2
        if "raw_payload_corrupted" in plan:
            raw = plan["raw_payload_corrupted"]
            ticket = self.ticket(
                "malformed_payload",
                plan,
                "tool_wire_received",
                {"raw_payload": raw, "raw_hash": evidence_hash(raw)},
            )
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                ticket["refs"].append(
                    self.controller._observe(
                        "tool_parse_rejected",
                        ticket["identity"],
                        {
                            "raw_hash": evidence_hash(raw),
                            "exception": type(exc).__name__,
                            "position": exc.pos,
                        },
                    )
                )
                value = {
                    "status": "error",
                    "error": f"InvalidJSON: {exc.msg}",
                    "fault": "malformed_payload",
                }
            else:
                ticket["applicable"] = False
        context["returned_hash"] = evidence_hash(value)
        if plan.get("tool_response_corrupted"):
            ticket = self.ticket(
                "tool_response_corruption",
                plan,
                "tool_response_produced",
                {"payload_hash": context["returned_hash"]},
            )
            ticket["applicable"] = False
        return value

    def prepare_corruption(self, original, modified, node, execution):
        context = self.pending.get()
        if context is None:
            raise RuntimeError("Response mutation requires a completed tool invocation")
        ticket = next(
            (
                ticket
                for ticket in context["tickets"]
                if ticket["identity"]["fault"] == "tool_response_corruption"
            ),
            None,
        )
        if ticket is None or ticket["identity"]["node_id"] != node:
            raise RuntimeError("Response mutation does not own the completed invocation")
        ticket["refs"].append(
            self.controller._observe(
                "tool_response_modified",
                ticket["identity"],
                {
                    "original_hash": evidence_hash(original),
                    "modified_hash": evidence_hash(modified),
                },
            )
        )
        ticket["expected_hash"] = evidence_hash(modified)
        ticket["applicable"] = context["returned_hash"] == evidence_hash(
            original
        ) and evidence_hash(original) != evidence_hash(modified)

    def take_delivery_context(self):
        context = self.pending.get()
        self.pending.set(None)
        return context

    def acknowledge(self, context, delivered):
        if context is None:
            return
        final_hash = evidence_hash(delivered)
        for ticket in context["tickets"]:
            expected = ticket.get("expected_hash", context["returned_hash"])
            row = {
                "payload_hash": final_hash,
                "expected_hash": expected,
                "consumer_received": True,
                "request_hash": context["key"],
            }
            ref = self.controller._observe("tool_consumer_received", ticket["identity"], row)
            ticket["refs"].append(ref)
            self.controller._receipt(
                ticket["identity"],
                ticket["refs"],
                row,
                delivery="DELIVERED"
                if ticket["applicable"] and final_hash == expected
                else "NOT_DELIVERED",
            )
        if context["plan"].get("replay_previous_event"):
            identity = self.controller._identity(
                "tool_delivery",
                context["plan"].get("node_id"),
                context["plan"].get("execution_instance_id"),
            )
            ref = self.controller._observe(
                "tool_response_delivered",
                identity,
                {
                    "payload_hash": final_hash,
                    "request_hash": context["key"],
                    "consumer_received": True,
                },
            )
            self.cache[context["key"]] = {"payload": copy.deepcopy(delivered), "ref": ref}


def delivery_executor(sandbox):
    executor = getattr(sandbox, "tool_faults", None)
    return executor if isinstance(executor, ToolFaultExecutor) else None
