"""
test_mutator.py

Unit tests for the adversarial mutation engine.
"""

import json

from eval_runner import mutator


def test_mutator_typo():
    """Verify typo mutation replaces characters."""
    scenario = {
        "aes_version": 1.4,
        "id": "typo_test",
        "title": "Typo Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "typo_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "Please clone the repo"}],
            "edges": [],
        },
    }
    mutated = mutator.mutate_scenario(scenario, "typo")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    assert desc != "Please clone the repo"
    assert len(desc) > 0


def test_mutator_ambiguity():
    """Verify ambiguity mutation adds confusing phrases."""
    scenario = {
        "aes_version": 1.4,
        "id": "ambiguity_test",
        "title": "Ambiguity Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "ambiguity_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}], "edges": []},
    }
    mutated = mutator.mutate_scenario(scenario, "ambiguity")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    fillers = ["I think", "maybe", "if you can", "sure though"]
    assert any(f in desc for f in fillers)
    assert desc != "Clone the repo"


def test_mutator_injection():
    """Verify injection mutation adds adversarial instructions."""
    scenario = {
        "aes_version": 1.4,
        "id": "injection_test",
        "title": "Injection Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "injection_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}], "edges": []},
    }
    mutated = mutator.mutate_scenario(scenario, "injection")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    assert "Ignore all previous instructions" in desc


def test_save_mutated_scenario(tmp_path):
    """Verify saving mutated scenario to file."""
    scenario = {"test": "data"}
    output_file = tmp_path / "mutated.json"
    mutator.save_mutated_scenario(scenario, output_file)
    assert output_file.exists()
    with open(output_file) as f:
        data = json.load(f)
    assert data == scenario


def test_mutate_text_with_typos_edge_cases():
    """Verify edge cases and specific branches in mutate_text_with_typos."""
    from unittest.mock import patch

    from eval_runner.mutator import mutate_text_with_typos

    # empty text
    assert mutate_text_with_typos("") == ""

    # Mocking choices to test swap, repeat, delete, and fallback branches
    with patch("random.random", return_value=0.0):
        # 1. Swap
        with patch("random.choice", return_value="swap"):
            res = mutate_text_with_typos("ab")
            assert res == "ba"

        # 2. Repeat
        with patch("random.choice", return_value="repeat"):
            res = mutate_text_with_typos("a")
            assert res == "aa"

        # 3. Delete
        with patch("random.choice", return_value="delete"):
            res = mutate_text_with_typos("ab")
            assert res == ""

        # 4. Unreachable Else branch (choice = "invalid")
        with patch("random.choice", return_value="invalid"):
            res = mutate_text_with_typos("ab")
            assert res == "ba"

    # Guarantee branch (not mutated, probability > 0)
    # 1. idx > 0
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=1):
        assert mutate_text_with_typos("ab", probability=0.1) == "ba"

    # 2. idx == 0 and len > 1
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=0):
        assert mutate_text_with_typos("ab", probability=0.1) == "ba"

    # 3. len == 1
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=0):
        assert mutate_text_with_typos("a", probability=0.1) == ""


def test_core_mutator_can_mutate():
    """Verify CoreMutator.can_mutate branch coverage."""
    from eval_runner.mutator import CoreMutator

    mutator_obj = CoreMutator()
    assert mutator_obj.can_mutate("typos") is True
    assert mutator_obj.can_mutate("invalid_mutation") is False


def test_core_mutator_metadata_id():
    """Verify CoreMutator updates metadata id if present."""
    scenario = {
        "id": "base",
        "metadata": {"id": "meta_base"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "text"}]},
    }
    mutated = mutator.mutate_scenario(scenario, "typos")
    assert mutated["metadata"]["id"] == "meta_base_mutated_typos"


def test_mutation_service_recursion_protection():
    """Verify that MutationService raises RecursionError on cycle (>50 depth)."""
    import pytest

    from eval_runner.mutator import MutationService, ScenarioMutator

    service = MutationService()

    class DummyMutator(ScenarioMutator):
        def can_mutate(self, mutation_type: str) -> bool:
            return True

        def mutate(self, scenario: dict, mutation_type: str, next_mutator) -> dict:
            return next_mutator(scenario, mutation_type)

    for _ in range(55):
        service.register_provider(DummyMutator())

    scenario = {
        "id": "base",
        "workflow": {"nodes": []},
    }
    with pytest.raises(RecursionError) as exc_info:
        service.mutate(scenario, "typos")
    assert "Max interceptor" in str(exc_info.value)


def test_mutation_service_negative_intercept():
    """Verify that MutationService bypasses provider if can_mutate returns False."""
    from eval_runner.mutator import MutationService, ScenarioMutator

    service = MutationService()

    class SkipMutator(ScenarioMutator):
        def can_mutate(self, mutation_type: str) -> bool:
            return False

        def mutate(self, scenario: dict, mutation_type: str, next_mutator) -> dict:
            scenario["skipped"] = False
            return next_mutator(scenario, mutation_type)

    service.register_provider(SkipMutator())
    scenario = {
        "id": "base",
        "workflow": {"nodes": []},
    }
    res = service.mutate(scenario, "typos")
    assert "skipped" not in res


def test_scenario_mutator_base_methods():
    """Verify base ScenarioMutator defaults, apply, and composition."""
    from agentv_runtime.contracts import MutationContext
    from eval_runner.mutator import ScenarioMutator, SequenceMutator

    mut = ScenarioMutator()
    assert mut.can_mutate("anything") is False
    res = mut.mutate({"k": "v"}, "test", lambda s, m: {**s, "mutated": True})
    assert res == {"k": "v", "mutated": True}

    ctx = MutationContext(scenario={"k": "v"}, seed=42)
    handle = mut.apply(ctx)
    assert handle.applied is True
    assert handle.name == "scenario_mutator"

    mut2 = ScenarioMutator()
    combined = mut + mut2
    assert isinstance(combined, SequenceMutator)
    assert len(combined.mutators) == 2


def test_sequence_mutator_exhaustive():
    """Verify SequenceMutator execution, filtering, and apply."""
    from agentv_runtime.contracts import MutationContext, MutationHandle
    from eval_runner.mutator import ScenarioMutator, sequence

    class DummyAddA(ScenarioMutator):
        name = "add_a"

        def can_mutate(self, m):
            return m == "seq_test"

        def mutate(self, s, m, next_m):
            s["a"] = 1
            return next_m(s, m)

        def apply(self, ctx, rng=None):
            ctx.scenario["a"] = 1
            return MutationHandle(mutation_id="1", name="add_a", applied=True, target="test")

    class DummyAddB(ScenarioMutator):
        name = "add_b"

        def can_mutate(self, m):
            return m == "seq_test"

        def mutate(self, s, m, next_m):
            s["b"] = 2
            return next_m(s, m)

        def apply(self, ctx, rng=None):
            ctx.scenario["b"] = 2
            return MutationHandle(mutation_id="2", name="add_b", applied=False, target="test")

    seq = sequence(DummyAddA(), DummyAddB())
    assert seq.can_mutate("seq_test") is True
    assert seq.can_mutate("unknown") is False
    assert seq.can_mutate("sequence") is True

    mutated = seq.mutate({"init": True}, "seq_test", lambda s, m: s)
    assert mutated["a"] == 1
    assert mutated["b"] == 2

    ctx = MutationContext(scenario={})
    handle = seq.apply(ctx)
    assert handle.applied is True
    assert "add_a" in handle.details["sequence"]
    assert "add_b" not in handle.details["sequence"]


def test_repeat_mutator_exhaustive():
    """Verify RepeatMutator repetition, min count, and apply."""
    from agentv_runtime.contracts import MutationContext, MutationHandle
    from eval_runner.mutator import ScenarioMutator, repeat

    class CounterMutator(ScenarioMutator):
        name = "counter"

        def can_mutate(self, m):
            return m == "count"

        def mutate(self, s, m, next_m):
            s["count"] = s.get("count", 0) + 1
            return s

        def apply(self, ctx, rng=None):
            ctx.scenario["count"] = ctx.scenario.get("count", 0) + 1
            return MutationHandle(mutation_id="c", name="counter", applied=True, target="counter")

    rep = repeat(CounterMutator(), count=3)
    assert rep.can_mutate("count") is True
    assert rep.can_mutate("repeat") is True
    assert rep.can_mutate("unknown") is False

    mutated = rep.mutate({}, "count", lambda s, m: s)
    assert mutated["count"] == 3

    ctx = MutationContext(scenario={})
    h = rep.apply(ctx)
    assert h.applied is True
    assert h.details["repeated_count"] == 3
    assert ctx.scenario["count"] == 3

    rep_min = repeat(CounterMutator(), count=0)
    assert rep_min.count == 1


def test_probability_mutator_exhaustive():
    """Verify ProbabilityMutator branching and apply."""
    from unittest.mock import patch

    from agentv_runtime.contracts import MutationContext, MutationHandle
    from eval_runner.mutator import ScenarioMutator, probability

    class MarkMutator(ScenarioMutator):
        name = "marker"

        def can_mutate(self, m):
            return True

        def mutate(self, s, m, next_m):
            s["marked"] = True
            return next_m(s, m)

        def apply(self, ctx, rng=None):
            ctx.scenario["marked"] = True
            return MutationHandle(mutation_id="m", name="marker", applied=True, target="m")

    prob = probability(MarkMutator(), p=0.5)
    assert prob.can_mutate("marker") is True
    assert prob.can_mutate("probability") is True

    with patch("random.random", return_value=0.2):
        mut_yes = prob.mutate({}, "marker", lambda s, m: s)
        assert mut_yes.get("marked") is True

    with patch("random.random", return_value=0.8):
        mut_no = prob.mutate({}, "marker", lambda s, m: s)
        assert mut_no.get("marked") is None

    ctx_yes = MutationContext(scenario={})
    with patch.object(ctx_yes.rng, "random", return_value=0.2):
        h_yes = prob.apply(ctx_yes)
        assert h_yes.applied is True

    ctx_no = MutationContext(scenario={})
    with patch.object(ctx_no.rng, "random", return_value=0.8):
        h_no = prob.apply(ctx_no)
        assert h_no.applied is False
        assert h_no.details["skipped_probability"] == 0.5


def test_conditional_mutators_and_helpers():
    """Verify ConditionalMutator and after_event/before_commit/between_steps helpers."""
    from agentv_runtime.contracts import MutationContext, MutationHandle
    from eval_runner.mutator import (
        ConditionalMutator,
        ScenarioMutator,
        after_event,
        before_commit,
        between_steps,
    )

    class ActionMutator(ScenarioMutator):
        name = "action"

        def can_mutate(self, m):
            return True

        def mutate(self, s, m, next_m):
            s["action_run"] = True
            return next_m(s, m)

        def apply(self, ctx, rng=None):
            ctx.scenario["action_run"] = True
            return MutationHandle(mutation_id="a", name="action", applied=True, target="a")

    cond = after_event(ActionMutator(), "user_login")
    assert cond.can_mutate("conditional") is True
    assert cond.can_mutate(cond.name) is True

    ctx_ev = MutationContext(scenario={}, event={"event": "user_login"})
    h_ev = cond.apply(ctx_ev)
    assert h_ev.applied is True

    ctx_hist = MutationContext(scenario={}, history=[{"event": "user_login"}])
    h_hist = cond.apply(ctx_hist)
    assert h_hist.applied is True

    ctx_none = MutationContext(scenario={}, history=[{"event": "other"}])
    h_none = cond.apply(ctx_none)
    assert h_none.applied is False

    cond_true = ConditionalMutator(ActionMutator(), lambda c: True)
    res_true = cond_true.mutate({}, "any", lambda s, m: s)
    assert res_true.get("action_run") is True

    cond_false = ConditionalMutator(ActionMutator(), lambda c: False)
    res_false = cond_false.mutate({}, "any", lambda s, m: s)
    assert res_false.get("action_run") is None

    bc = before_commit(ActionMutator())
    ctx_commit = MutationContext(scenario={}, event={"event": "commit"})
    assert bc.apply(ctx_commit).applied is True
    ctx_other = MutationContext(scenario={}, event={"event": "other"})
    assert bc.apply(ctx_other).applied is False
    ctx_no_ev = MutationContext(scenario={})
    assert bc.apply(ctx_no_ev).applied is True

    bs = between_steps(ActionMutator(), 2, 5)
    ctx_step_in = MutationContext(scenario={}, step_index=3)
    assert bs.apply(ctx_step_in).applied is True
    ctx_step_out = MutationContext(scenario={}, step_index=6)
    assert bs.apply(ctx_step_out).applied is False


def test_concurrent_mutator_exhaustive():
    """Verify ConcurrentMutator execution, metadata, and apply."""
    from agentv_runtime.contracts import MutationContext, MutationHandle
    from eval_runner.mutator import ScenarioMutator, concurrent

    class M1(ScenarioMutator):
        name = "m1"

        def can_mutate(self, m):
            return True

        def mutate(self, s, m, next_m):
            s["m1"] = True
            return s

        def apply(self, ctx, rng=None):
            ctx.scenario["m1"] = True
            return MutationHandle(mutation_id="1", name="m1", applied=True, target="m1")

    conc = concurrent(M1())
    assert conc.can_mutate("concurrent") is True
    assert conc.can_mutate("anything") is True

    res = conc.mutate({}, "any", lambda s, m: s)
    assert res["m1"] is True
    assert res["metadata"]["simulated_race"] is True

    ctx = MutationContext(scenario={})
    h = conc.apply(ctx)
    assert h.applied is True
    assert ctx.metadata["concurrent_race_simulated"] is True


def test_all_vector_sub_engines():
    """Verify all 9 vector sub-engines and their supported mutation types."""
    from eval_runner.mutator import (
        AuthorizationMutators,
        ContextMutators,
        InputMutators,
        MemoryMutators,
        ObjectiveMutators,
        RetrievalMutators,
        StateMutators,
        TemporalMutators,
        ToolMutators,
    )

    im = InputMutators()
    assert im.can_mutate("typo") is True
    assert im.can_mutate("ambiguity") is True
    assert im.can_mutate("injection") is True
    scen_im = {"workflow": {"nodes": [{"id": "n1", "task_description": "Initial task"}]}}
    im.apply_mutation(scen_im, "typo")
    im.apply_mutation(scen_im, "ambiguity")
    im.apply_mutation(scen_im, "injection")
    assert "ADVERSARIAL_SUCCESS" in scen_im["workflow"]["nodes"][0]["task_description"]

    cm = ContextMutators()
    assert cm.can_mutate("goal_drift") is True
    assert cm.can_mutate("constraint_drop") is True
    scen_cm = {
        "workflow": {"nodes": [{"id": "n1", "task_description": "Do not delete without approval"}]}
    }
    cm.apply_mutation(scen_cm, "goal_drift")
    assert "alternative goal" in scen_cm["workflow"]["nodes"][0]["task_description"]
    cm.apply_mutation(scen_cm, "constraint_drop")
    assert "without approval" not in scen_cm["workflow"]["nodes"][0]["task_description"]

    mm = MemoryMutators()
    assert mm.can_mutate("memory_drift") is True
    scen_mm = {"workflow": {"nodes": [{"id": "n1"}]}}
    mm.apply_mutation(scen_mm, "memory_drift")
    assert "scratchpad" in scen_mm["workflow"]["nodes"][0]

    rm = RetrievalMutators()
    for t in rm.SUPPORTED_TYPES:
        assert rm.can_mutate(t) is True
        scen_rm = {"workflow": {"nodes": [{"id": "n1"}]}}
        rm.apply_mutation(scen_rm, t)
        assert len(scen_rm["workflow"]["nodes"][0]["retrieved_documents"]) >= 1

    tm = ToolMutators()
    for t in tm.SUPPORTED_TYPES:
        assert tm.can_mutate(t) is True
    scen_tm = {
        "workflow": {
            "nodes": [{"id": "n1", "parameters": {"num": 123, "str_num": "456", "other": "val"}}]
        }
    }
    tm.apply_mutation(scen_tm, "schema_type")
    assert scen_tm["workflow"]["nodes"][0]["parameters"]["num"] == "123"
    assert scen_tm["workflow"]["nodes"][0]["parameters"]["str_num"] == 456
    tm.apply_mutation(scen_tm, "missing_field")
    tm.apply_mutation(scen_tm, "enum_drift")
    tm.apply_mutation(scen_tm, "malformed_payload")
    tm.apply_mutation(scen_tm, "tool_contract")
    tm.apply_mutation(scen_tm, "duplicate")
    tm.apply_mutation(scen_tm, "replay")
    node_tm = scen_tm["workflow"]["nodes"][0]
    assert node_tm.get("unsupported_enum_value") is not None
    assert node_tm.get("raw_payload_corrupted") is not None
    assert node_tm.get("duplicate_execution") is True
    assert node_tm.get("replay_previous_event") is True

    sm = StateMutators()
    for t in sm.SUPPORTED_TYPES:
        assert sm.can_mutate(t) is True
    scen_sm = {"workflow": {"nodes": [{"id": "n1"}]}, "failure_policy": {}}
    sm.apply_mutation(scen_sm, "stale_state")
    sm.apply_mutation(scen_sm, "partial_commit")
    sm.apply_mutation(scen_sm, "rollback_failure")
    sm.apply_mutation(scen_sm, "concurrency")
    sm.apply_mutation(scen_sm, "duplicate_commit")
    sm.apply_mutation(scen_sm, "commit_after_cancel")
    sm.apply_mutation(scen_sm, "stale_commit")
    assert scen_sm["metadata"]["concurrency_conflict"] is True

    scen_sm_no_fp = {"workflow": {"nodes": [{"id": "n1"}]}}
    sm.apply_mutation(scen_sm_no_fp, "rollback_failure")
    sm.apply_mutation(scen_sm_no_fp, "duplicate_commit")
    sm.apply_mutation(scen_sm_no_fp, "commit_after_cancel")
    assert "failure_policy" in scen_sm_no_fp

    am = AuthorizationMutators()
    for t in am.SUPPORTED_TYPES:
        assert am.can_mutate(t) is True
        scen_am = {"workflow": {"nodes": [{"id": "n1"}]}}
        am.apply_mutation(scen_am, t)
        assert len(scen_am["workflow"]["nodes"][0]) > 1

    tem = TemporalMutators()
    for t in tem.SUPPORTED_TYPES:
        assert tem.can_mutate(t) is True
        scen_tem = {"workflow": {"nodes": [{"id": "n1"}]}}
        tem.apply_mutation(scen_tem, t)
        assert len(scen_tem["workflow"]["nodes"][0]) > 1

    om = ObjectiveMutators()
    for t in om.SUPPORTED_TYPES:
        assert om.can_mutate(t) is True
        scen_om = {"workflow": {"nodes": [{"id": "n1", "task_description": "Goal"}]}}
        om.apply_mutation(scen_om, t)
        assert len(scen_om["workflow"]["nodes"][0]) > 2


def test_core_mutator_apply_and_metadata():
    """Verify CoreMutator orchestration, lineage tracking, and apply."""
    from agentv_runtime.contracts import MutationContext
    from eval_runner.mutator import CoreMutator

    cm = CoreMutator()
    scen = {
        "id": "s1",
        "title": "Title",
        "metadata": {"id": "m1"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Desc"}]},
    }
    mutated = cm.mutate(scen, "typos", lambda s, m: s)
    assert "_mutated_typos" in mutated["id"]
    assert "_mutated_typos" in mutated["metadata"]["id"]
    assert "(Mutated: typos)" in mutated["title"]
    assert len(mutated["metadata"]["applied_mutations"]) == 1

    scen_minimal = {"workflow": {"nodes": []}}
    mut_min = cm.mutate(scen_minimal, "typos", lambda s, m: s)
    assert len(mut_min["metadata"]["applied_mutations"]) == 1

    ctx = MutationContext(
        scenario={"workflow": {"nodes": [{"id": "n1", "task_description": "abc"}]}}, seed=123
    )
    h = cm.apply(ctx)
    assert h.applied is True
    assert h.target == "scenario"


def test_mutation_service_comprehensive(tmp_path):
    """Verify MutationService registration, override, failure handling, and in-run execution."""
    import pytest

    from agentv_runtime.contracts import MutationContext
    from eval_runner import mutator
    from eval_runner.mutator import MutationService, ScenarioMutator

    service = MutationService()

    class CustomMut(ScenarioMutator):
        name = "custom_test"

        def can_mutate(self, m):
            return m == "custom_test"

        def mutate(self, s, m, next_m):
            s["custom_applied"] = True
            return next_m(s, m)

    service.register_provider(CustomMut())
    res_dict_spec = service.mutate_scenario(
        {"workflow": {"nodes": []}},
        {"type": "custom_test"},
        seed=999,
    )
    assert res_dict_spec["custom_applied"] is True
    assert res_dict_spec["metadata"]["mutation_seed"] == 999

    res_direct_obj = service.mutate_scenario(
        {"workflow": {"nodes": []}},
        CustomMut(),
    )
    assert res_direct_obj["custom_applied"] is True

    class FailingMandatory(ScenarioMutator):
        is_mandatory = True

        def can_mutate(self, m):
            return True

        def mutate(self, s, m, next_m):
            raise ValueError("Mandatory crash")

    service.register_provider(FailingMandatory())
    with pytest.raises(RuntimeError, match="Mandatory mutator"):
        service.mutate_scenario({"workflow": {"nodes": []}}, "typos")

    service.reset()

    class FailingOptional(ScenarioMutator):
        is_mandatory = False

        def can_mutate(self, m):
            return True

        def mutate(self, s, m, next_m):
            raise ValueError("Optional warning")

    service.register_provider(FailingOptional())
    res_opt = service.mutate_scenario(
        {"workflow": {"nodes": [{"id": "n1", "task_description": "clean"}]}},
        "typos",
    )
    assert res_opt is not None

    service.reset()
    with service.override_provider(CustomMut()):
        res_override = service.mutate({"workflow": {"nodes": []}}, "custom_test")
        assert res_override["custom_applied"] is True
    assert len(service._providers) == 0

    ctx_str = MutationContext(
        scenario={"workflow": {"nodes": [{"id": "n1", "task_description": "test"}]}}, seed=1
    )
    h_str = service.apply_in_run(ctx_str, "typos")
    assert h_str.applied is True
    assert len(ctx_str.metadata["applied_mutation_records"]) == 1

    ctx_mut = MutationContext(scenario={"workflow": {"nodes": []}})
    h_mut = service.apply_in_run(ctx_mut, CustomMut())
    assert h_mut.applied is True

    catalog = service.list_supported_mutators()
    assert len(catalog) > 10
    service.register_provider(CustomMut())
    catalog_with_p = service.list_supported_mutators()
    assert any(c["name"] == "custom_test" for c in catalog_with_p)

    out_file = tmp_path / "saved_scen.json"
    mutator.save_mutated_scenario({"saved": True}, out_file)
    assert out_file.exists()


def test_mutator_edge_cases_and_branch_completions(tmp_path):
    from agentv_runtime.contracts import (
        MutationContext,
        MutationCoordinate,
        MutationHandle,
        MutationOperation,
        MutationTier,
        MutationVector,
    )
    from eval_runner.mutator import (
        AuthorizationMutators,
        ConcurrentMutator,
        ContextMutators,
        InputMutators,
        MemoryMutators,
        MutationService,
        ObjectiveMutators,
        RepeatMutator,
        RetrievalMutators,
        ScenarioMutator,
        StateMutators,
        TemporalMutators,
        ToolMutators,
    )

    class InactiveMutator(ScenarioMutator):
        name = "inactive"

        def apply(self, context, rng=None):
            return MutationHandle(
                mutation_id="dummy",
                name=self.name,
                applied=False,
                coordinate=MutationCoordinate(
                    MutationVector.INPUT, MutationOperation.INSERT, MutationTier.T0_LINGUISTIC
                ),
                target="node",
                details={},
            )

    ctx = MutationContext(scenario={"workflow": {"nodes": []}})

    rep = RepeatMutator(InactiveMutator(), count=2)
    rep_handle = rep.apply(ctx)
    assert rep_handle.applied is False

    conc = ConcurrentMutator([InactiveMutator()])
    conc_handle = conc.apply(ctx)
    assert conc_handle.applied is False

    empty_scen = {"workflow": {"nodes": []}}
    InputMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    ContextMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    MemoryMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    RetrievalMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    ToolMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    StateMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    AuthorizationMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    TemporalMutators().apply_mutation(empty_scen, "unrecognized_mutation")
    ObjectiveMutators().apply_mutation(empty_scen, "unrecognized_mutation")

    scen_empty_params = {"workflow": {"nodes": [{"parameters": {}}]}}
    ToolMutators().apply_mutation(scen_empty_params, "missing_field")

    scen_string_fp = {"failure_policy": "not_a_dict", "workflow": {"nodes": [{}]}}
    StateMutators().apply_mutation(scen_string_fp, "rollback_failure")
    StateMutators().apply_mutation(scen_string_fp, "duplicate_commit")
    StateMutators().apply_mutation(scen_string_fp, "commit_after_cancel")

    scen_none_fp_1 = {"failure_policy": None, "workflow": {"nodes": [{}]}}
    StateMutators().apply_mutation(scen_none_fp_1, "duplicate_commit")
    assert scen_none_fp_1["failure_policy"]["duplicate_commit"] is True

    scen_none_fp_2 = {"failure_policy": None, "workflow": {"nodes": [{}]}}
    StateMutators().apply_mutation(scen_none_fp_2, "commit_after_cancel")
    assert scen_none_fp_2["failure_policy"]["commit_after_cancel"] is True

    fresh_service = MutationService()
    fresh_service.reset()

    clean_service = MutationService()
    override_mut = InactiveMutator()
    with clean_service.override_provider(override_mut):
        clean_service._global_providers.clear()
        if hasattr(clean_service._local, "providers"):
            clean_service._local.providers.clear()

    non_standard_spec_scen = {"workflow": {"nodes": [{"id": "n1", "task_description": "base"}]}}
    res_non_std = clean_service.mutate_scenario(non_standard_spec_scen, mutation_spec=12345)
    assert res_non_std is not None
