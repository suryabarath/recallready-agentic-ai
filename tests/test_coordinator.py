"""Real compiled LangGraph and A1 stack; only network responses are simulated."""

import json

import httpx
import pytest

from a1_trace import active_run
from case_state import CaseRequest, CaseState
from coordinator import A1Coordinator
from group_c_contract import GroupCResult
from interpreter import Budget
from source import DEVELOPMENT_RECORDS, GROUP_A, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_database_failures import track_connections
from test_interpreter import client_for


def request_for(store, recall):
    return CaseRequest(case_id="case-" + recall, run_id="graph-" + recall,
                       recall_number=recall, snapshot_id=store.snapshot_id)


@pytest.mark.parametrize("recall", DEVELOPMENT_RECORDS)
def test_graph_routes_all_eighteen_and_preserves_outputs(store, tmp_path, recall):
    proposal, expected = fixture_output(store, recall)
    cloud, model = [], []
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([(json.dumps(proposal), "completed")], model) as client:
        coordinator = A1Coordinator(store, retriever_for(store, points_for(store, recall), cloud), client, budget)
        result = coordinator.run(request_for(store, recall))
        assert not client.is_closed()
        assert store.lookup(recall, snapshot_id=store.snapshot_id)
    assert result.a1.result.model_dump() == expected
    base = expected.get("base", expected)
    review = recall in GROUP_C or bool(base["facts"]["uncertainties"])
    assert result.status == ("human_review" if review else "a1_completed")
    assert (result.review_reason is not None) == review
    assert result.errors == [] and result.revision_count == 0
    assert [event.event for event in result.events] == ["started", "a1_validated", result.status]
    assert len(model) == len(cloud) == len(budget.summary()) == 1
    assert result.a1.trace.model_attempts == 1
    assert CaseState.model_validate_json(result.model_dump_json()) == result
    if recall in GROUP_C:
        assert isinstance(result.a1.result, GroupCResult)
        assert result.a1.result.relations == GroupCResult.model_validate(expected).relations
    assert active_run.get() is None


@pytest.mark.parametrize("failure", ["context", "retrieval", "provider", "semantic", "settlement", "budget"])
def test_failed_a1_stops_without_automatic_retry(store, tmp_path, monkeypatch, failure):
    recall = GROUP_A[0]
    proposal, _ = fixture_output(store, recall)
    if failure == "semantic": proposal["identifiers"][0]["value"] = "invented-value"
    cloud, model = [], []
    budget = Budget(tmp_path / "usage.sqlite", limit_microdollars=1 if failure == "budget" else 1_000_000)
    retriever = retriever_for(store, [] if failure == "retrieval" else points_for(store, recall), cloud)
    if failure == "settlement": track_connections(monkeypatch, fail_sql="UPDATE", after_execute=True)
    output = httpx.ReadTimeout("private diagnostic") if failure == "provider" else (json.dumps(proposal), "completed")
    selected = request_for(store, recall).model_dump()
    if failure == "context": selected["event_id"] = "wrong-event"
    with client_for([output], model) as client:
        result = A1Coordinator(store, retriever, client, budget).run(selected)
    assert result.status == "unresolved" and result.a1.status == "unresolved"
    assert len(result.errors) == 1 and not result.errors[0].automatic_retry_allowed
    assert result.events[-1].event == "stopped" and result.review_reason is None
    assert result.revision_count == 0
    assert len(model) == (1 if failure in ("provider", "semantic", "settlement") else 0)
    assert "private diagnostic" not in result.model_dump_json()
    if failure in ("provider", "settlement"):
        assert budget.summary()[0]["state"] == "reserved"


def test_unexpected_exception_is_unresolved_without_invented_trace(store, tmp_path, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError("secret or model content must not be exposed")
    monkeypatch.setattr("coordinator.run_a1_with_trace", crash)
    model = []
    with client_for([], model) as client:
        result = A1Coordinator(store, retriever_for(store, [], []), client,
                               Budget(tmp_path / "usage.sqlite")).run(request_for(store, GROUP_A[0]))
    assert result.status == "unresolved" and result.a1 is None
    assert result.errors[0].code == "coordinator_internal_failure"
    assert result.errors[0].request_state == "outcome_unknown"
    assert "secret or model content" not in result.model_dump_json()
    assert [e.event for e in result.events] == ["started", "a1_unexpected_failure", "stopped"]
    assert model == []


@pytest.mark.parametrize("extra", [{"a1": {}}, {"status": "a1_completed"}, {"revision_count": 1},
                                   {"inventory_set_id": "not-an-a1-input"}])
def test_caller_cannot_inject_previous_results_or_downstream_state(store, tmp_path, extra):
    selected = request_for(store, GROUP_A[0]).model_dump() | extra
    cloud, model = [], []
    with client_for([], model) as client:
        graph = A1Coordinator(store, retriever_for(store, [], cloud), client,
                               Budget(tmp_path / "usage.sqlite"))
        with pytest.raises(ValueError): graph.run(selected)
    assert cloud == model == []


def test_terminal_state_cannot_remove_group_c_review_requirement(store, tmp_path):
    recall = GROUP_C[0]
    proposal, _ = fixture_output(store, recall)
    with client_for([(json.dumps(proposal), "completed")], []) as client:
        result = A1Coordinator(store, retriever_for(store, points_for(store, recall), []), client,
                               Budget(tmp_path / "usage.sqlite")).run(request_for(store, recall))
    altered = result.model_dump()
    altered.update(status="a1_completed", review_reason=None)
    with pytest.raises(ValueError, match="review requirement"):
        CaseState.model_validate(altered)
    altered = result.model_dump()
    altered["a1"]["run_id"] = "another-run"
    with pytest.raises(ValueError, match="case/run context"):
        CaseState.model_validate(altered)


def test_graph_has_only_a1_routes_and_disables_remote_tracing(store, tmp_path, monkeypatch):
    import coordinator as module
    original = module.tracing_context
    seen = []
    def tracing(**kwargs):
        seen.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(module, "tracing_context", tracing)
    with client_for([], []) as client:
        graph = A1Coordinator(store, retriever_for(store, [], []), client,
                               Budget(tmp_path / "usage.sqlite"))
        result = graph.run(request_for(store, GROUP_A[0]))
        nodes = set(graph._graph.get_graph().nodes)
    assert nodes == {"__start__", "begin", "interpret_a1", "complete", "review", "stop", "__end__"}
    assert seen == [{"enabled": False}]
    assert result.status == "unresolved"


def test_reusing_graph_does_not_reuse_previous_state(store, tmp_path):
    recall = GROUP_A[0]
    proposal, _ = fixture_output(store, recall)
    request = request_for(store, recall)
    before = request.model_dump()
    model = []
    with client_for([(json.dumps(proposal), "completed"), (json.dumps(proposal), "completed")], model) as client:
        graph = A1Coordinator(store, retriever_for(store, points_for(store, recall), []), client,
                               Budget(tmp_path / "usage.sqlite"))
        first = graph.run(request)
        second = graph.run(before | {"run_id": "second-run", "case_id": "second-case"})
    assert first.run_id != second.run_id
    assert first.a1.trace.calls[0].ledger_call_id != second.a1.trace.calls[0].ledger_call_id
    assert len(first.events) == len(second.events) == 3
    assert len(model) == 2 and request.model_dump() == before
    assert second.status == "a1_completed" and second.errors == []
