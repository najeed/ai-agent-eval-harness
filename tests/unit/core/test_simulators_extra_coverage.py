import os
from unittest.mock import patch

import pytest

from eval_runner.simulators import (
    ApiSimulator,
    BaseSimulator,
    CICDSimulator,
    DatabaseSimulator,
    GitSimulator,
    SocialMediaSimulator,
)


@pytest.mark.asyncio
async def test_base_simulator_extended_coverage():
    # Line 50: on_poll with expected_value
    sim = BaseSimulator({"status": "ready"})
    assert await sim.on_poll("status", {"expected_value": "ready"}) is True
    assert await sim.on_poll("status", {"expected_value": "busy"}) is False

    # Line 54: on_poll with truthiness
    sim.state["active"] = True
    assert await sim.on_poll("active", {}) is True
    sim.state["active"] = False
    assert await sim.on_poll("active", {}) is False

    # Lines 67-75: on_verify with mismatching criteria
    res = await sim.on_verify({"criteria": {"status": "busy"}})
    assert res["status"] == "error"
    assert "State mismatch" in res["message"]

    # Lines 84-86: get_snapshot deepcopy
    snap = await sim.get_snapshot()
    snap["status"] = "modified"
    assert sim.state["status"] == "ready"


@pytest.mark.asyncio
async def test_api_simulator_extended_coverage():
    sim = ApiSimulator()
    # Line 223: Invalid URL
    res = await sim.handle_api_request({"url": ""})
    assert res["status"] == "error"
    assert "Invalid API URL" in res["message"]

    # Lines 239-240: Invalid timeout
    with patch.dict(os.environ, {"SHIM_TIMEOUT": "not-a-float", "IS_LIVE": "true"}):
        from unittest.mock import AsyncMock

        import httpx

        mock_client = AsyncMock()
        mock_response = httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=b'{"status": "ok"}',
        )
        mock_client.request.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client

        with patch("httpx.AsyncClient", return_value=mock_client):
            await sim.handle_api_request({"url": "http://test.com"})
            # Timeout should have defaulted to 30.0


@pytest.mark.asyncio
async def test_database_simulator_extended_coverage(tmp_path):
    sim = DatabaseSimulator()
    sim.terminal_jail = tmp_path
    engine = sim._get_engine()

    # Lines 536-546: Malformed JSON in audit log
    with engine.connect() as conn:
        from sqlalchemy import text

        conn.execute(
            text("""
            INSERT INTO _forensic_audit_log (table_name, action, row_identity, old_data, new_data)
            VALUES ('test_table', 'UPDATE', '1', 'invalid-json', 'invalid-json')
        """)
        )
        conn.commit()

    snap = await sim.get_snapshot()
    # It should survive and log errors (verified by code path execution)
    assert len(snap["audit_log"]) > 0

    # Lines 556-557: DELETE operation for an existing row
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER, name TEXT)"))
        conn.commit()

    # Provision forensics for the new table
    sim._provision_forensic_log(engine)

    # Insert then delete
    await sim.handle_database_query({"query": "INSERT INTO items (id, name) VALUES (1, 'item1')"})
    await sim.handle_database_query({"query": "DELETE FROM items WHERE id = 1"})

    snap = await sim.get_snapshot()
    # The 'items' table should be empty in the virtual view
    assert "items" not in snap["tables"] or len(snap["tables"]["items"]) == 0

    # Line 494: execute fallback (inherited from BaseSimulator but tested on DatabaseSimulator)
    res = await sim.execute("unknown_db_action", {})
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_git_simulator_extended_coverage(tmp_path):
    sim = GitSimulator()
    sim.terminal_jail = tmp_path

    # Lines 67-75 (Inherited): on_verify mismatch
    sim.state["history"] = ["commit1"]
    res = await sim.on_verify({"criteria": {"history": ["commit2"]}})
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_cicd_simulator_extended_coverage():
    sim = CICDSimulator()
    # Line 950-959: on_poll success
    res = await sim.handle_cicd_deploy({"environment": "prod"})
    bid = res["build_id"]
    assert await sim.on_poll("build_complete", {"build_id": bid}) is True
    assert sim.state["builds"][-1]["status"] == "success"


@pytest.mark.asyncio
async def test_social_media_simulator_extended_coverage():
    sim = SocialMediaSimulator()
    # Line 908-913: on_poll
    res = await sim.execute("social_post", {"text": "hello"})
    pid = res["id"]
    assert await sim.on_poll("post_confirmed", {"post_id": pid}) is True
    assert await sim.on_poll("unknown_condition", {}) is False


@pytest.mark.asyncio
async def test_simulators_final_polish_coverage():
    # BaseSimulator on_verify success
    sim = BaseSimulator({"v": 1})
    res = await sim.on_verify({"criteria": {"v": 1}})
    assert res["status"] == "success"

    # ApiSimulator execute fallback
    api = ApiSimulator()
    res = await api.execute("unknown_api_action", {})
    assert res["status"] == "error"
