import pytest

from eval_runner.hitl.pending import PendingApprovalRegistry


@pytest.mark.asyncio
async def test_pending_approval_lifecycle(tmp_path):
    # Setup isolated database path
    db_file = tmp_path / "hitl.db"

    # Initialize registry manually with test db
    registry = PendingApprovalRegistry()
    registry.db_path = db_file
    registry._init_db()

    # Clear any memory states
    registry._items = {}

    # 1. Create approval
    approval = registry.create("task_1", "run_1", "Please authorize transfer", timeout_seconds=5)
    assert approval.task_id == "task_1"
    assert approval.run_id == "run_1"
    assert approval.prompt == "Please authorize transfer"
    assert approval.action is None
    assert approval.response is None

    # 2. Query pending queue
    pending_list = registry.pending()
    assert len(pending_list) == 1
    assert pending_list[0].id == approval.id

    # 3. Resolve approval
    success = registry.resolve(approval.id, "approve", "Override signed by Admin-01", "root-admin")
    assert success is True
    assert approval.action == "approve"
    assert approval.response == "Override signed by Admin-01"
    assert approval.resolved_by == "root-admin"

    # Wait for the approval which is now resolved (signaled = True)
    await approval.wait()

    # Queue should be empty
    assert len(registry.pending()) == 0


@pytest.mark.asyncio
async def test_pending_approval_timeout(tmp_path):
    db_file = tmp_path / "hitl.db"
    registry = PendingApprovalRegistry()
    registry.db_path = db_file
    registry._init_db()
    registry._items = {}

    # Create approval with ultra-short timeout
    approval = registry.create(
        "task_timeout", "run_timeout", "Fast response needed", timeout_seconds=1
    )

    # Wait for the waiter to timeout
    await approval.wait()

    assert approval.action == "timeout"
    assert "approval window expired" in approval.response


def test_pending_approval_sqlite_persistence(tmp_path):
    db_file = tmp_path / "hitl.db"
    registry1 = PendingApprovalRegistry()
    registry1.db_path = db_file
    registry1._init_db()
    registry1._items = {}

    # Create item
    item = registry1.create("persist_task", "persist_run", "Verify public key signature")

    # Load registry2 from the same DB
    registry2 = PendingApprovalRegistry()
    registry2.db_path = db_file
    registry2._load_from_db()

    # Parity verification
    loaded_item = registry2._items.get(item.id)
    assert loaded_item is not None
    assert loaded_item.task_id == "persist_task"
    assert loaded_item.prompt == "Verify public key signature"


def test_pending_approval_to_dict_fields(tmp_path):
    """Verify to_dict() returns all expected keys and remaining_seconds is non-negative."""

    from eval_runner.hitl.pending import PendingApproval

    approval = PendingApproval("task_td", "run_td", "Check this", timeout_seconds=300)
    d = approval.to_dict()

    assert d["task_id"] == "task_td"
    assert d["run_id"] == "run_td"
    assert d["prompt"] == "Check this"
    assert d["timeout_seconds"] == 300
    assert d["action"] is None
    assert d["response"] is None
    assert d["resolved_by"] is None
    assert d["remaining_seconds"] >= 0


def test_pending_approval_resolve_no_such_item(tmp_path):
    """Resolving a non-existent approval_id returns False."""
    registry = PendingApprovalRegistry()
    registry._items = {}
    result = registry.resolve("no-such-id", "approve", "ok", "admin")
    assert result is False


def test_pending_approval_sse_subscribe_unsubscribe():
    """Verify subscribe/unsubscribe correctly manage _sse_listeners list."""
    from eval_runner.hitl.pending import _sse_listeners, subscribe_sse, unsubscribe_sse

    initial_len = len(_sse_listeners)

    def noop_listener(e, d):
        pass

    subscribe_sse(noop_listener)
    assert len(_sse_listeners) == initial_len + 1

    unsubscribe_sse(noop_listener)
    assert len(_sse_listeners) == initial_len


def test_pending_approval_unsubscribe_not_registered():
    """Unsubscribing a listener that was never registered is a safe no-op."""
    from eval_runner.hitl.pending import unsubscribe_sse

    def ghost_listener(e, d):
        pass

    # Must not raise
    unsubscribe_sse(ghost_listener)


def test_pending_approval_notify_sse_listener_exception(tmp_path):
    """A listener that raises should not crash _notify_sse (logged as debug)."""
    registry = PendingApprovalRegistry()
    registry._items = {}

    broken_listener_called = [False]

    def broken_listener(event_type, data):
        broken_listener_called[0] = True
        raise RuntimeError("SSE listener crash")

    from eval_runner.hitl import pending as pending_module

    original = pending_module._sse_listeners[:]

    pending_module._sse_listeners.clear()
    pending_module._sse_listeners.append(broken_listener)

    try:
        # Should NOT raise despite the listener crashing
        registry._notify_sse("test_event", {"key": "value"})
        assert broken_listener_called[0] is True
    finally:
        pending_module._sse_listeners.clear()
        pending_module._sse_listeners.extend(original)


def test_pending_registry_load_from_db_missing_file(tmp_path):
    """_load_from_db returns silently when DB file does not exist."""
    registry = PendingApprovalRegistry()
    registry.db_path = tmp_path / "nonexistent.db"
    registry._items = {}
    # Should not raise
    registry._load_from_db()
    assert len(registry._items) == 0


def test_pending_approval_already_resolved_event_set():
    """PendingApproval with pre-set action should have _event already set."""
    from eval_runner.hitl.pending import PendingApproval

    approval = PendingApproval(
        "task_r", "run_r", "Already done", action="approve", response="yes", resolved_by="admin"
    )
    assert approval._event.is_set()
    assert approval.action == "approve"


def test_pending_approval_sqlite_exceptions(tmp_path):
    """Verify sqlite operations raise SQLite errors gracefully (logging and continuing)."""
    import sqlite3
    from unittest.mock import patch

    from eval_runner.hitl.pending import PendingApprovalRegistry

    # Mock sqlite3.connect to fail
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mock DB Error")):
        registry = PendingApprovalRegistry()

        # 1. _init_db failure
        registry.db_path = tmp_path / "fail.db"
        registry._init_db()

        # 2. _load_from_db failure
        registry._load_from_db()

        # 3. create failure
        appr = registry.create("t", "r", "p")
        assert appr is not None

        # 4. resolve failure
        success = registry.resolve(appr.id, "approve", "res", "usr")
        assert success is True
