"""
tests/golden/test_golden_hitl.py
Golden Verification Corpus: HITL Restart Durability & Resumption Token Validation
"""

import pytest

from eval_runner.hitl.pending import PendingApprovalRegistry


@pytest.mark.asyncio
async def test_golden_hitl_restart_durability_and_token(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. First session creates approval
    registry1 = PendingApprovalRegistry()
    registry1.db_path = tmp_path / "hitl.db"
    registry1._init_db()

    app1 = registry1.create(
        task_id="task_1",
        run_id="run_100",
        prompt="Authorize transfer of $5000?",
        timeout_seconds=300,
    )
    token = app1.resumption_token
    assert token.startswith("tok_")
    assert not app1.resumed_from_db

    # 2. Simulate process restart by instantiating new registry
    registry2 = PendingApprovalRegistry()
    registry2.db_path = tmp_path / "hitl.db"
    registry2._load_from_db()

    # Verify restored state
    app_restored = registry2.get_by_resumption_token(token)
    assert app_restored is not None
    assert app_restored.id == app1.id
    assert app_restored.resumed_from_db is True
    assert app_restored.prompt == "Authorize transfer of $5000?"

    # Check pending_resumed
    resumed_list = registry2.pending_resumed()
    assert any(a.id == app1.id for a in resumed_list)

    # 3. Resolve approval in new session
    success = registry2.resolve(
        app1.id, action="approve", response="Approved by security officer", resolved_by="admin@org"
    )
    assert success is True
    assert app_restored.action == "approve"
    assert app_restored.response == "Approved by security officer"
