"""
Unit contract for ``SessionManager._evaluate_consensus`` sub-semantics.

Locked behavior:
  - strategies = Majority_Vote | Absolute_Unanimity | Weighted_Average
  - quorum = min_judges successfully-executed judge votes; a shortfall is a
    LOUD evaluated=false result, never replaced by silent fallbacks
  - unknown strategy => loud evaluated=false
  - ija_threshold breach demotes status to INCONCLUSIVE and overrides PASS
    at the decision layer (certification withheld pending human review)
  - 'Luna-1' panel alias provisions through config.JUDGE_PROVIDER
"""

import pytest

from eval_runner import config as config_mod
from eval_runner.metrics import MetricRegistry
from eval_runner.session import SessionManager


class _SilentBus:
    """Records nothing; satisfies event_bus.emit in NOT_EVALUATED paths."""

    def emit(self, *args, **kwargs):
        pass


def _bare_session() -> SessionManager:
    session = object.__new__(SessionManager)
    session.event_bus = _SilentBus()
    session.session_metadata = {}
    session._last_transition_expectations = ["Done"]
    return session


HISTORY = [{"role": "agent", "content": "Done"}]

pytestmark = pytest.mark.asyncio


@pytest.fixture
def judge_env(monkeypatch):
    """
    Patches the two authoritative primitives consensus executes through:
    LLMProviderFactory.create (provisioning/quorum) and the
    luna_judge_score metric primitive (the votes themselves).
    """
    state: dict = {"scores": [], "created": [], "unprovisionable": set()}

    class _FakeFactory:
        @staticmethod
        def create(provider_name):
            if provider_name in state["unprovisionable"]:
                raise RuntimeError(f"no credentials for provider '{provider_name}'")
            state["created"].append(provider_name)
            return object()

    async def fake_score(cfg, agent_summary, metadata):
        assert cfg["expected_outcome"] == "Done"
        return state["scores"].pop(0)

    monkeypatch.setattr("eval_runner.llm_providers.LLMProviderFactory", _FakeFactory, raising=False)
    monkeypatch.setattr(MetricRegistry, "get", staticmethod(lambda name: fake_score))
    monkeypatch.setattr(config_mod, "JUDGE_PROVIDER", "fake-default-provider")
    return state


def _consensus_cfg(strategy="Majority_Vote", judges=("j1", "j2", "j3"), **extra):
    cons = {"strategy": strategy, "judge_panel": list(judges)}
    cons.update(extra)
    return {"consensus": cons}


async def test_majority_pass(judge_env):
    judge_env["scores"] = [0.9, 0.8, 0.7]
    result = await _bare_session()._evaluate_consensus(_consensus_cfg(), HISTORY)
    assert result["evaluated"] is True
    assert result["verdict"] == "PASS"
    assert result["status"] == "PASS"
    assert result["tally"] == {"pass": 3, "fail": 0}
    assert result["agreement"] == 0.8


async def test_majority_fail(judge_env):
    judge_env["scores"] = [0.2, 0.3, 0.1]
    result = await _bare_session()._evaluate_consensus(_consensus_cfg(), HISTORY)
    assert result["evaluated"] is True
    assert result["status"] == "FAIL"
    assert result["tally"] == {"pass": 0, "fail": 3}


async def test_quorum_fail_is_loud_not_fallback(judge_env):
    judge_env["unprovisionable"] = {"bad-provider"}
    judge_env["scores"] = [0.9]  # only one judge ever votes
    judges = [
        {"name": "good", "provider": "ok-provider"},
        {"name": "u1", "provider": "bad-provider"},
        {"name": "u2", "provider": "bad-provider"},
    ]
    result = await _bare_session()._evaluate_consensus(
        _consensus_cfg(min_judges=2, judges=judges), HISTORY
    )
    assert result["evaluated"] is False
    assert result["status"] == "NOT_EVALUATED"
    assert result["reason"].startswith("Quorum not met: 1 judge(s) executed")
    unavailable = [v for v in result["votes"] if v["status"] == "UNAVAILABLE"]
    assert len(unavailable) == 2


async def test_unknown_strategy_is_loud(judge_env):
    judge_env["scores"] = [1.0, 1.0, 1.0]
    result = await _bare_session()._evaluate_consensus(
        _consensus_cfg(strategy="Bogus_Vote"), HISTORY
    )
    assert result["evaluated"] is False
    assert "Unknown consensus strategy 'Bogus_Vote'" in result["reason"]


async def test_ija_inconclusive_overrides_pass(judge_env):
    judge_env["scores"] = [1.0, 1.0, 0.6]  # agreement 0.4
    result = await _bare_session()._evaluate_consensus(_consensus_cfg(ija_threshold=0.9), HISTORY)
    assert result["evaluated"] is True
    assert result["verdict"] == "PASS"  # majority still passes...
    assert result["status"] == "INCONCLUSIVE"  # ...but certification is withheld
    assert "human review" in result["reason"]


async def test_absolute_unanimity_buckets(judge_env):
    judge_env["scores"] = [0.9, 0.9]
    unanimous = await _bare_session()._evaluate_consensus(
        _consensus_cfg(strategy="Absolute_Unanimity", judges=("a", "b")), HISTORY
    )
    assert unanimous["status"] == "PASS"
    assert unanimous["tally"]["buckets"] == [0.9]

    judge_env["scores"] = [0.9, 0.7]
    dissenting = await _bare_session()._evaluate_consensus(
        _consensus_cfg(strategy="Absolute_Unanimity", judges=("a", "b")), HISTORY
    )
    assert dissenting["status"] == "INCONCLUSIVE"


async def test_weighted_average_mean_threshold(judge_env):
    judge_env["scores"] = [0.9, 0.6]
    passing = await _bare_session()._evaluate_consensus(
        _consensus_cfg(strategy="Weighted_Average", judges=("a", "b")), HISTORY
    )
    assert passing["status"] == "PASS"
    assert passing["mean_score"] == 0.75

    judge_env["scores"] = [0.4, 0.2]
    failing = await _bare_session()._evaluate_consensus(
        _consensus_cfg(strategy="Weighted_Average", judges=("a", "b")), HISTORY
    )
    assert failing["status"] == "FAIL"


async def test_luna_1_alias_provisions_through_default_provider(judge_env):
    judge_env["scores"] = [0.9]
    result = await _bare_session()._evaluate_consensus(
        _consensus_cfg(min_judges=1, judges=("Luna-1",)), HISTORY
    )
    # Alias resolves to the configured default judge provider.
    assert judge_env["created"] == ["fake-default-provider"]
    assert result["evaluated"] is True
    assert result["status"] == "PASS"


async def test_no_expected_message_never_judges(judge_env):
    session = object.__new__(SessionManager)
    session.event_bus = _SilentBus()
    session.session_metadata = {}
    session._last_transition_expectations = []
    result = await session._evaluate_consensus(_consensus_cfg(), HISTORY)
    assert result["evaluated"] is False
    assert result["reason"].startswith("No expected outcome available to judge")
