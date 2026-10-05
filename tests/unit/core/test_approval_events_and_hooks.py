"""
tests/unit/core/test_approval_events_and_hooks.py
Unit tests verifying Open Core HITL approval lifecycle events and plugin hooks:
1. CoreEvents.APPROVAL_CREATED and CoreEvents.APPROVAL_RESOLVED constant definitions.
2. BaseEvalPlugin.on_approval_created and on_approval_resolved interface methods.
3. SessionApprovalManager event emissions and plugin hooks on create_durable_request
   and resolve_durable_request.
4. Fail-safe best-effort error isolation (plugin or listener failures never halt Open Core).
5. Authoritative org_id and tenant context propagation from scenario/session metadata.
6. handle_hitl_resume and console resume_run event emissions and hook triggers.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.events import CoreEvents, EventEmitter
from eval_runner.handlers.evaluation import handle_hitl_resume
from eval_runner.plugins import BaseEvalPlugin, PluginManager
from eval_runner.reference.approval_store import (
    FileApprovalStore,
    reset_default_approval_store,
)
from eval_runner.session_components.approval_manager import SessionApprovalManager


class DummyAuditPlugin(BaseEvalPlugin):
    """Test plugin that captures approval lifecycle hooks."""

    def __init__(self):
        self.created_calls = []
        self.resolved_calls = []

    def on_approval_created(self, context: Any, request: Any) -> None:
        self.created_calls.append((context, request))

    def on_approval_resolved(self, context: Any, request: Any) -> None:
        self.resolved_calls.append((context, request))


class FailingPlugin(BaseEvalPlugin):
    """Test plugin that maliciously raises exceptions in hooks to test isolation."""

    def on_approval_created(self, context: Any, request: Any) -> None:
        raise RuntimeError("Crash in on_approval_created")

    def on_approval_resolved(self, context: Any, request: Any) -> None:
        raise RuntimeError("Crash in on_approval_resolved")


@pytest.fixture(autouse=True)
def clean_approval_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_default_approval_store()
    test_root = tmp_path / ".agentv"
    monkeypatch.setenv("AGENTV_APPROVAL_DIR", str(test_root / "approvals"))
    monkeypatch.setenv("AGENTV_APPROVAL_DB", str(test_root / "approvals.db"))
    yield
    reset_default_approval_store()


class TestApprovalEventsAndHooksContracts:
    def test_core_events_constants(self):
        assert CoreEvents.APPROVAL_CREATED == "approval_created"
        assert CoreEvents.APPROVAL_RESOLVED == "approval_resolved"

    def test_base_plugin_default_hooks(self):
        plugin = BaseEvalPlugin()
        # Default implementations are pass / no-op
        req = ApprovalRequest(
            approval_token="tok_1",
            run_id="run_1",
            turn_index=0,
            outbound_payload_hash="hash_1",
        )
        assert plugin.on_approval_created(None, req) is None
        assert plugin.on_approval_resolved(None, req) is None

    def test_plugin_manager_trigger_hook_alias(self):
        mgr = PluginManager()
        assert mgr.trigger_hook == mgr.trigger


class TestSessionApprovalManagerDispatch:
    def test_create_durable_request_dispatches_hook_and_emits_event(self):
        bus = EventEmitter(run_id="run_test_dispatch", async_mode=False)
        emitted_events = []
        bus.subscribe(lambda e: emitted_events.append(e))

        plugin_mgr = PluginManager()
        audit_plugin = DummyAuditPlugin()
        plugin_mgr.plugins.append(audit_plugin)

        store = FileApprovalStore()
        manager = SessionApprovalManager(
            run_id="run_test_dispatch",
            approval_store=store,
            plugin_manager=plugin_mgr,
            event_bus=bus,
        )

        req = manager.create_durable_request(
            turn_index=1,
            action_payload={"tool": "transfer", "amount": 100},
            metadata={"org_id": "tenant-corp", "task_id": "task_42"},
            prompt="Authorize transfer",
        )

        # Verify hook was triggered
        assert len(audit_plugin.created_calls) == 1
        ctx, hook_req = audit_plugin.created_calls[0]
        assert ctx is manager
        assert hook_req.approval_token == req.approval_token
        assert hook_req.metadata.get("org_id") == "tenant-corp"

        # Verify event was emitted
        assert len(emitted_events) == 1
        event = emitted_events[0]
        assert event.name == CoreEvents.APPROVAL_CREATED
        assert event.data["approval_token"] == req.approval_token
        assert event.data["run_id"] == "run_test_dispatch"
        assert event.data["metadata"]["org_id"] == "tenant-corp"
        assert event.data["metadata"]["task_id"] == "task_42"

    def test_resolve_durable_request_dispatches_hook_and_emits_event(self):
        bus = EventEmitter(run_id="run_test_resolve", async_mode=False)
        emitted_events = []
        bus.subscribe(lambda e: emitted_events.append(e))

        plugin_mgr = PluginManager()
        audit_plugin = DummyAuditPlugin()
        plugin_mgr.plugins.append(audit_plugin)

        store = FileApprovalStore()
        manager = SessionApprovalManager(
            run_id="run_test_resolve",
            approval_store=store,
            plugin_manager=plugin_mgr,
            event_bus=bus,
        )

        created = manager.create_durable_request(
            turn_index=2,
            action_payload={"tool": "refund"},
            metadata={"org_id": "tenant-corp"},
        )

        resolved = manager.resolve_durable_request(
            approval_token=created.approval_token,
            decision="APPROVED",
            decided_by="admin_user",
            decision_reason="Legitimate request",
        )
        assert resolved.status == "APPROVED"

        # Verify hook was triggered
        assert len(audit_plugin.resolved_calls) == 1
        ctx, hook_req = audit_plugin.resolved_calls[0]
        assert ctx is manager
        assert hook_req.approval_token == created.approval_token
        assert hook_req.status == "APPROVED"
        assert hook_req.decision == "APPROVED"
        assert hook_req.decided_by == "admin_user"
        assert hook_req.decision_reason == "Legitimate request"

        # Verify APPROVAL_RESOLVED event was emitted
        resolved_events = [e for e in emitted_events if e.name == CoreEvents.APPROVAL_RESOLVED]
        assert len(resolved_events) == 1
        res_evt = resolved_events[0]
        assert res_evt.data["approval_token"] == created.approval_token
        assert res_evt.data["status"] == "APPROVED"
        assert res_evt.data["decision"] == "APPROVED"
        assert res_evt.data["decided_by"] == "admin_user"
        assert res_evt.data["decision_reason"] == "Legitimate request"

    def test_fail_safe_isolation_when_bus_emit_fails(self):
        failing_bus = MagicMock()
        failing_bus.emit.side_effect = RuntimeError("Broken event bus")

        store = FileApprovalStore()
        manager = SessionApprovalManager(
            run_id="run_test_failsafe_bus",
            approval_store=store,
            event_bus=failing_bus,
        )

        # create_durable_request must not raise
        req = manager.create_durable_request(
            turn_index=0,
            action_payload={"step": "check"},
            metadata={"org_id": "tenant-isolated"},
        )
        assert req is not None
        assert req.status == "PENDING"

        # resolve_durable_request must not raise
        resolved = manager.resolve_durable_request(
            approval_token=req.approval_token,
            decision="REJECTED",
            decided_by="security_scanner",
            decision_reason="Policy violation",
        )
        assert resolved is not None
        assert resolved.status == "REJECTED"

    def test_fail_safe_isolation_when_plugin_trigger_fails(self):
        plugin_mgr = MagicMock()
        plugin_mgr.trigger.side_effect = RuntimeError("Crash inside plugin manager trigger")

        store = FileApprovalStore()
        manager = SessionApprovalManager(
            run_id="run_test_failsafe_plugin",
            approval_store=store,
            plugin_manager=plugin_mgr,
        )

        # create_durable_request must not raise and must catch trigger exception
        req = manager.create_durable_request(
            turn_index=0,
            action_payload={"step": "check"},
            metadata={"org_id": "tenant-isolated"},
        )
        assert req is not None
        assert req.status == "PENDING"

        # resolve_durable_request must not raise and must catch trigger exception
        resolved = manager.resolve_durable_request(
            approval_token=req.approval_token,
            decision="APPROVED",
            decided_by="approver",
        )
        assert resolved is not None
        assert resolved.status == "APPROVED"


class TestSessionTenantProvenancePropagation:
    @pytest.mark.asyncio
    async def test_session_propagates_org_id_from_scenario_and_session_metadata(self):
        from eval_runner.session import Session

        scenario = {
            "title": "HITL Tenant Scoping Test",
            "metadata": {
                "org_id": "tenant-enterprise-99",
                "correlation_id": "corr-xyz",
            },
            "steps": [],
        }

        session = Session(
            scenario=scenario,
            run_id="run_tenant_scoping",
            metadata={"org_id": "tenant-enterprise-99", "project_id": "proj-alpha"},
        )

        # Inspect approval manager creation inside _handle_hitl
        with patch.object(session.approval_manager, "create_durable_request") as mock_create:
            mock_create.return_value = ApprovalRequest(
                approval_token="tok_test",
                run_id="run_tenant_scoping",
                turn_index=1,
                outbound_payload_hash="h123",
                metadata={"org_id": "tenant-enterprise-99"},
            )

            # Trigger pause branch with non-interactive mock
            with (
                patch("sys.stdin.isatty", return_value=False),
                patch.dict("os.environ", {"AGENTV_CLI_HITL_SUSPEND": "1"}),
            ):
                with pytest.raises(InterruptedError):
                    await session._handle_hitl(
                        turn=1,
                        agent_response={"action": "reboot_cluster", "prompt": "Approve action"},
                        history=[],
                        actions={},
                        turn_ctx=MagicMock(task_id="task_pause_01"),
                    )

            mock_create.assert_called_once()
            called_kwargs = mock_create.call_args.kwargs
            called_metadata = called_kwargs["metadata"]
            assert called_metadata["org_id"] == "tenant-enterprise-99"
            assert called_metadata["task_id"] == "task_pause_01"
            assert called_metadata["correlation_id"] == "corr-xyz"
            assert called_metadata["project_id"] == "proj-alpha"

    @pytest.mark.asyncio
    async def test_session_propagates_org_id_when_metadata_is_none_or_top_level(self):
        from eval_runner.session import Session

        scenario = {
            "title": "HITL Top-Level Org ID Test",
            "org_id": "tenant-top-level",
            "steps": [],
        }

        session = Session(
            scenario=scenario,
            run_id="run_top_level_tenant",
        )

        with patch.object(session.approval_manager, "create_durable_request") as mock_create:
            mock_create.return_value = ApprovalRequest(
                approval_token="tok_top",
                run_id="run_top_level_tenant",
                turn_index=1,
                outbound_payload_hash="h123",
                metadata={"org_id": "tenant-top-level"},
            )

            with (
                patch("sys.stdin.isatty", return_value=False),
                patch.dict("os.environ", {"AGENTV_CLI_HITL_SUSPEND": "1"}),
            ):
                with pytest.raises(InterruptedError):
                    await session._handle_hitl(
                        turn=1,
                        agent_response={"action": "reboot_cluster", "prompt": "Approve action"},
                        history=[],
                        actions={},
                        turn_ctx=MagicMock(task_id="task_pause_02"),
                    )

            mock_create.assert_called_once()
            called_metadata = mock_create.call_args.kwargs["metadata"]
            assert called_metadata["org_id"] == "tenant-top-level"
            assert called_metadata["task_id"] == "task_pause_02"


class TestHitlResumeChannelsDispatch:
    @pytest.mark.asyncio
    async def test_handle_hitl_resume_triggers_hook_and_emits_event(self):
        from eval_runner import events, plugins

        store = FileApprovalStore()
        req = ApprovalRequest(
            approval_token="tok_resume_dispatch",
            run_id="run_resume_01",
            turn_index=1,
            outbound_payload_hash="hash_abc",
            metadata={"org_id": "tenant-omega"},
        )
        store.create_request(req)

        emitted = []
        events.subscribe(lambda e: emitted.append(e))

        audit_plugin = DummyAuditPlugin()
        plugins.manager.plugins.append(audit_plugin)

        args = argparse.Namespace(
            run_id="run_resume_01",
            approval_token="tok_resume_dispatch",
            decision="REJECTED",
            reviewer="ops_team",
            reason="Blocked by SOC",
            store="file",
        )

        code = await handle_hitl_resume(args)
        assert code == 0

        # Check plugin hook
        assert any(
            hook_req.approval_token == "tok_resume_dispatch" and hook_req.decision == "REJECTED"
            for _, hook_req in audit_plugin.resolved_calls
        )

        # Check global event
        resolved_evts = [
            e
            for e in emitted
            if e.name == CoreEvents.APPROVAL_RESOLVED
            and e.data.get("approval_token") == "tok_resume_dispatch"
        ]
        assert len(resolved_evts) >= 1
        assert resolved_evts[0].data["decision"] == "REJECTED"
        assert resolved_evts[0].data["decided_by"] == "ops_team"

    def test_console_resume_run_triggers_hook_and_emits_event(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from flask import Flask

        from eval_runner import events, plugins
        from eval_runner.console.routes.runs import run_bp

        monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
        app = Flask(__name__)
        app.register_blueprint(run_bp)
        client = app.test_client()

        store = FileApprovalStore()
        req = ApprovalRequest(
            approval_token="tok_console_resume",
            run_id="run_console_01",
            turn_index=0,
            outbound_payload_hash="hash_123",
            metadata={"org_id": "tenant-enterprise-fintech"},
        )
        store.create_request(req)

        emitted = []
        events.subscribe(lambda e: emitted.append(e))

        audit_plugin = DummyAuditPlugin()
        plugins.manager.plugins.append(audit_plugin)

        with patch("eval_runner.reference.inprocess_backend.get_execution_backend") as mock_backend:
            mock_backend.return_value.resume.return_value = {"status": "SUCCESS"}
            resp = client.post(
                "/v1/runs/run_console_01/resume",
                json={
                    "approval_token": "tok_console_resume",
                    "decision": "APPROVED",
                    "reviewer": "compliance_lead",
                },
            )
            assert resp.status_code == 200

        # Verify hook
        assert any(
            hook_req.approval_token == "tok_console_resume" and hook_req.decision == "APPROVED"
            for _, hook_req in audit_plugin.resolved_calls
        )

        # Verify event
        resolved_evts = [
            e
            for e in emitted
            if e.name == CoreEvents.APPROVAL_RESOLVED
            and e.data.get("approval_token") == "tok_console_resume"
        ]
        assert len(resolved_evts) >= 1
        assert resolved_evts[0].data["decision"] == "APPROVED"
        assert resolved_evts[0].data["decided_by"] == "compliance_lead"

    @pytest.mark.asyncio
    async def test_handle_hitl_resume_hook_exception_isolation(self):
        from eval_runner import events

        store = FileApprovalStore()
        req = ApprovalRequest(
            approval_token="tok_resume_fail",
            run_id="run_resume_fail",
            turn_index=1,
            outbound_payload_hash="hash_abc",
        )
        store.create_request(req)

        args = argparse.Namespace(
            run_id="run_resume_fail",
            approval_token="tok_resume_fail",
            decision="REJECTED",
            reviewer="ops_team",
            reason="Denied",
            store="file",
        )

        with patch.object(events, "emit", side_effect=RuntimeError("Bus emit error")):
            code = await handle_hitl_resume(args)
            assert code == 0

    def test_console_resume_hook_exception_isolation(self, monkeypatch: pytest.MonkeyPatch):
        from flask import Flask

        from eval_runner import events
        from eval_runner.console.routes.runs import run_bp

        monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
        app = Flask(__name__)
        app.register_blueprint(run_bp)
        client = app.test_client()

        store = FileApprovalStore()
        req = ApprovalRequest(
            approval_token="tok_console_fail",
            run_id="run_console_fail",
            turn_index=0,
            outbound_payload_hash="hash_123",
        )
        store.create_request(req)

        with patch("eval_runner.reference.inprocess_backend.get_execution_backend") as mock_backend:
            mock_backend.return_value.resume.return_value = {"status": "SUCCESS"}
            with patch.object(events, "emit", side_effect=RuntimeError("Console event bus error")):
                resp = client.post(
                    "/v1/runs/run_console_fail/resume",
                    json={
                        "approval_token": "tok_console_fail",
                        "decision": "APPROVED",
                        "reviewer": "compliance_lead",
                    },
                )
                assert resp.status_code == 200
