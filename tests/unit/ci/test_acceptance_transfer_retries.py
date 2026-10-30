import json
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from tests.acceptance.fixtures.agents import compliant_transfer_agent as actor


@pytest.mark.parametrize("receipt", ["exact", "missing", "different", "duplicate"])
def test_transfer_retry_requires_independent_confirmation(monkeypatch, receipt):
    row = {
        "id": "acceptance-compliant-transfer",
        "source": "operating",
        "target": "recipient",
        "amount": 200,
    }
    transfers = {
        "exact": [row],
        "missing": [],
        "different": [{**row, "amount": 400}],
        "duplicate": [row, dict(row)],
    }[receipt]
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps({"state": {"transfers": transfers}}).encode()
    transport = MagicMock(
        side_effect=[HTTPError("http://oracle/transfers", 409, "Conflict", {}, None), response]
    )
    monkeypatch.setenv("AGENTV_ACCEPTANCE_ORACLE_URL", "http://oracle")
    monkeypatch.setattr(actor, "urlopen", transport)

    if receipt == "exact":
        actor.commit_external_acceptance_transfer()
    else:
        with pytest.raises(RuntimeError, match="did not confirm"):
            actor.commit_external_acceptance_transfer()
    assert transport.call_count == 2
    assert transport.call_args.args[0] == "http://oracle/state"


def test_transfer_retry_does_not_hide_authority_failure(monkeypatch):
    transport = MagicMock(
        side_effect=HTTPError("http://oracle/transfers", 503, "Unavailable", {}, None)
    )
    monkeypatch.setenv("AGENTV_ACCEPTANCE_ORACLE_URL", "http://oracle")
    monkeypatch.setattr(actor, "urlopen", transport)
    with pytest.raises(HTTPError):
        actor.commit_external_acceptance_transfer()
    assert transport.call_count == 1
