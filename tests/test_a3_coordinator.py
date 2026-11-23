"""Real graph and SQLite integration; external A1 responses alone are fixtures."""

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


def run_graph(store, tmp_path, recall=GROUP_A[0], **row):
    db, _ = make_inventory(tmp_path, store.snapshot_id, **row)
    proposal, _ = fixture_output(store, recall)
    with InventoryStore(db) as inventory, client_for([(json.dumps(proposal), "completed")], []) as client:
        return A1Coordinator(store, retriever_for(store, points_for(store, recall), []),
                             client, Budget(tmp_path / "usage.sqlite"),
                             inventory_store=inventory, enable_a3=True).run(request_for(store, recall))


@pytest.mark.parametrize("row,code", [({}, "REVIEW_ITEM"),
    ({"lot_code": "different"}, "RECORD_NO_DEMONSTRATED_MATCH")])
def test_resolved_a2_produces_review_only_plan(store, tmp_path, row, code):
    state = run_graph(store, tmp_path, **row)
    assert state.status == "human_review" and state.a3.status == "planned"
    assert state.a3.suggested_actions[0].action_code == code
    assert state.events[-2].event == "a3_planned"
    assert state.a1.trace.model_attempts == 1
    assert CaseState.model_validate_json(state.model_dump_json()) == state
    if code == "REVIEW_ITEM":
        assert state.a3.suggested_actions[0].evidence_ids == state.a2.findings[0].a1_evidence_ids
    else:
        assert "not a safety clearance" in state.a3.suggested_actions[0].reason


@pytest.mark.parametrize("recall,row", [(GROUP_C[0], {}), (GROUP_A[0], {"upc": ""})])
def test_upstream_review_blocks_planning(store, tmp_path, monkeypatch, recall, row):
    def forbidden(*args):
        pytest.fail("A3 must not run before upstream review")
    monkeypatch.setattr("coordinator.plan_response", forbidden)
    state = run_graph(store, tmp_path, recall, **row)
    assert state.status == "human_review" and state.a3 is None


@pytest.mark.parametrize("failure", ["exception", "citation", "context", "reason"])
def test_invalid_planner_output_stops_safely(store, tmp_path, monkeypatch, failure):
    from a3_agent import plan_response
    def broken(a2):
        if failure == "exception":
            raise RuntimeError("private diagnostic")
        plan = plan_response(a2)
        if failure == "context":
            return plan.model_copy(update={"run_id": "another-run"})
        action = plan.suggested_actions[0]
        change = {"evidence_ids": ["invented"]} if failure == "citation" else {"reason": "safe to sell"}
        return plan.model_copy(update={"suggested_actions": [action.model_copy(update=change)]})
    monkeypatch.setattr("coordinator.plan_response", broken)
    state = run_graph(store, tmp_path)
    assert state.status == "unresolved" and state.a3 is None
    assert state.errors[0].code == "response_plan_failed"
    assert state.a2.status == "matched" and state.a1.trace.model_attempts == 1
    assert "private diagnostic" not in state.model_dump_json()
    assert CaseState.model_validate_json(state.model_dump_json()) == state


def test_persisted_state_rejects_changed_plan_and_cleared_review(store, tmp_path):
    state = run_graph(store, tmp_path)
    for update in ({"status": "a2_completed", "review_reason": None},
                   {"a3": state.a3.model_copy(update={"case_id": "wrong"}).model_dump()}):
        with pytest.raises(ValueError):
            CaseState.model_validate(state.model_dump() | update)
