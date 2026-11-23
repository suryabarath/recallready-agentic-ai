"""A1-A4 through the compiled graph; only external responses are simulated."""

import json

import pytest

from case_state import CaseState
from coordinator import A1Coordinator
from interpreter import Budget
from inventory_store import InventoryStore
from source import GROUP_A, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_a2_isolated_integration import make_inventory
from test_coordinator import request_for
from test_interpreter import client_for


def execute(store, tmp_path, *, critic_outputs=(), enable_llm=False, recall=GROUP_A[0], **row):
    db, _ = make_inventory(tmp_path, store.snapshot_id, **row)
    proposal, _ = fixture_output(store, recall)
    seen = []
    with InventoryStore(db) as inventory, client_for(
            [(json.dumps(proposal), "completed"), *critic_outputs], seen) as client:
        state = A1Coordinator(store, retriever_for(store, points_for(store, recall), []),
            client, Budget(tmp_path / "usage.sqlite"), inventory_store=inventory,
            enable_a3=True, enable_a4=True, enable_a4_llm=enable_llm).run(request_for(store, recall))
    assert CaseState.model_validate_json(state.model_dump_json()) == state
    return state, seen


def critique(target="a3"):
    return dict(passed=False, findings=[dict(severity="blocking", category="unsupported_claim",
        target_agent=target, code="check_rationale", message="Review source rationale.",
        evidence_ids=["EV-H-0011-2027-CODE_INFO"], item_ids=["ISOLATED-001-A"],
        fixable_by_revision=True)], suggested_revision_target=target,
        revision_instructions="Review the source rationale.")


@pytest.mark.parametrize("row", [{}, {"lot_code": "different"}])
def test_deterministic_a4_preserves_review_on_match_and_no_match(store, tmp_path, row):
    state, seen = execute(store, tmp_path, **row)
    assert state.status == "human_review" and state.a4.verdict == "human_review"
    assert state.a4.findings == [] and state.a4.review_boundary_verified
    assert state.revision_count == 0 and len(seen) == 1
    assert [e.event for e in state.events][-2:] == ["a4_human_review", "human_review"]


@pytest.mark.parametrize("recall,row", [(GROUP_C[0], {}), (GROUP_A[0], {"upc": ""})])
def test_upstream_review_never_reaches_critic(store, tmp_path, monkeypatch, recall, row):
    def forbidden(*args, **kwargs):
        pytest.fail("A4 must not bypass upstream review")
    monkeypatch.setattr("coordinator.run_a4", forbidden)
    state, seen = execute(store, tmp_path, recall=recall, **row)
    assert state.status == "human_review" and state.a4 is None and len(seen) == 1


def test_one_replan_preserves_first_audit_and_stops(store, tmp_path):
    response = (json.dumps(critique()), "completed")
    state, seen = execute(store, tmp_path, critic_outputs=[response, response], enable_llm=True)
    assert state.status == "human_review" and state.revision_count == 1
    assert state.prior_a4.verdict == "revise" and state.a4.verdict == "human_review"
    assert state.prior_a3 == state.a3  # Deterministic replay cannot change policy.
    assert len(seen) == 3 and state.a1.trace.model_attempts == 1
    assert len(state.prior_a4.trace.calls) == len(state.a4.trace.calls) == 1
    assert state.prior_a4.trace.calls[0].ledger_call_id != state.a4.trace.calls[0].ledger_call_id
    assert sum(e.event == "revision_replay_started" for e in state.events) == 1


@pytest.mark.parametrize("target", ["a1", "a2"])
def test_upstream_revision_request_escalates_without_regeneration(store, tmp_path, target):
    state, seen = execute(store, tmp_path, critic_outputs=[(json.dumps(critique(target)), "completed")], enable_llm=True)
    assert state.status == "human_review" and state.a4.verdict == "revise"
    assert state.a4.revision_request.target_agent == target
    assert state.revision_count == 0 and len(seen) == 2


def test_semantic_failure_stops_unresolved_without_replay(store, tmp_path):
    data = critique()
    data["findings"][0]["evidence_ids"].append("EV-INVENTED")
    state, seen = execute(store, tmp_path, critic_outputs=[(json.dumps(data), "completed")], enable_llm=True)
    assert state.status == "unresolved" and state.a4.error.code == "invalid_output"
    assert state.a4.error in state.errors and len(seen) == 2
    assert state.revision_count == 0


def test_unexpected_critic_failure_is_typed(store, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private diagnostic")
    monkeypatch.setattr("coordinator.run_a4", fail)
    state, seen = execute(store, tmp_path)
    assert state.status == "unresolved" and state.errors[0].code == "critic_internal_failure"
    assert "private diagnostic" not in state.model_dump_json() and len(seen) == 1


def test_shared_state_rejects_critic_context_and_unrecorded_revision(store, tmp_path):
    state, _ = execute(store, tmp_path)
    data = state.model_dump()
    data["a4"]["run_id"] = "other"
    with pytest.raises(ValueError):
        CaseState.model_validate(data)
    with pytest.raises(ValueError):
        CaseState.model_validate(state.model_dump() | {"revision_count": 1})


@pytest.mark.parametrize("flags", [{"enable_a4": True}, {"enable_a4_llm": True},
                                   {"enable_a4": "yes"}, {"enable_a4_llm": 1}])
def test_invalid_stage_flags_fail_before_execution(store, tmp_path, flags):
    with client_for([], []) as client, pytest.raises(ValueError):
        A1Coordinator(store, retriever_for(store, [], []), client,
                      Budget(tmp_path / "unused.sqlite"), **flags)
