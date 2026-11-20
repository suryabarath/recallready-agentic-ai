"""Coordinator envelopes through real A1 code with simulated network responses."""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import httpx
from openai import OpenAI
import pytest

from a1_run import A1RunEnvelope, RunError, run_a1_with_trace
from a1_trace import active_run, RunTrace
from fda_store import FDAStore, build_fda_store
from interpreter import Budget
from source import DEVELOPMENT_RECORDS, GROUP_A, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_database_failures import track_connections
from test_interpreter import client_for


def ledger_links(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT run_id,call_id FROM run_calls ORDER BY call_id").fetchall()
    finally:
        connection.close()


@pytest.mark.parametrize("recall", DEVELOPMENT_RECORDS)
def test_all_eighteen_envelopes_preserve_results_and_trace(store, tmp_path, recall):
    proposal, expected = fixture_output(store, recall)
    budget = Budget(tmp_path / "usage.sqlite")
    cloud, model = [], []
    retriever = retriever_for(store, points_for(store, recall), cloud)
    with client_for([(json.dumps(proposal), "completed")], model) as client:
        envelope = run_a1_with_trace(store, retriever, client, budget, run_id="run-" + recall,
                                     recall_number=recall, snapshot_id=store.snapshot_id)
        assert not client.is_closed()
    assert envelope.status == "validated" and envelope.error is None
    assert envelope.result.model_dump() == expected
    trace = envelope.trace
    assert trace.model_attempts == 1 and trace.repair_count == 0
    assert len(trace.retrieved) == 4
    assert trace.retrieval_seconds is not None and trace.elapsed_seconds >= trace.retrieval_seconds
    call = trace.calls[0]
    assert call.request_state == "response_received" and call.accounting_state == "settled"
    assert call.input_tokens == 4000 and call.output_tokens == 2000
    assert call.reasoning_tokens == 1500 and trace.estimated_cost_usd == 0.0014
    assert ledger_links(budget.path) == [(envelope.run_id, call.ledger_call_id)]
    assert A1RunEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    operational = trace.model_dump_json()
    assert "offline-test-key" not in operational and "original_text" not in operational
    assert "instructions" not in operational and "scope_note" not in operational
    assert active_run.get() is None


@pytest.mark.parametrize("recall", [GROUP_A[0], GROUP_C[0]])
def test_structural_repair_counts_actual_attempts(store, tmp_path, recall):
    proposal, _ = fixture_output(store, recall)
    budget = Budget(tmp_path / "usage.sqlite")
    retriever = retriever_for(store, points_for(store, recall), [])
    with client_for([("{}", "completed"), (json.dumps(proposal), "completed")], []) as client:
        envelope = run_a1_with_trace(store, retriever, client, budget, run_id="repair",
                                     recall_number=recall, snapshot_id=store.snapshot_id)
    assert envelope.status == "validated"
    assert envelope.trace.model_attempts == 2 and envelope.trace.repair_count == 1
    assert envelope.trace.estimated_cost_usd == 0.0028
    assert len(ledger_links(budget.path)) == 2


@pytest.mark.parametrize("failure", ["reserve", "settle", "timeout", "semantic", "missing-usage"])
@pytest.mark.parametrize("recall", [GROUP_A[0], GROUP_C[0]])
def test_unresolved_envelopes_preserve_request_and_accounting_state(
        store, tmp_path, monkeypatch, failure, recall):
    proposal, _ = fixture_output(store, recall)
    if failure == "semantic":
        if recall in GROUP_C: proposal["relations"][0]["parts"][0]["value"] = "invented-value"
        else: proposal["identifiers"][0]["value"] = "invented-value"
    budget = Budget(tmp_path / "usage.sqlite")
    if failure in {"reserve", "settle"}:
        track_connections(monkeypatch, fail_sql="INSERT" if failure == "reserve" else "UPDATE",
                          after_execute=True)
    seen = []
    if failure == "missing-usage":
        # Real SDK deserialization, with a valid response that omits optional usage.
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json=dict(id="response-no-usage", object="response",
                created_at=1, model="gpt-6-luna", status="completed", output=[]))
        client = OpenAI(api_key="dummy-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    else:
        outputs = [httpx.ReadTimeout("secret-diagnostic")] if failure == "timeout" else [(json.dumps(proposal), "completed")]
        client = client_for(outputs, seen)
    retriever = retriever_for(store, points_for(store, recall), [])
    with client:
        envelope = run_a1_with_trace(store, retriever, client, budget, run_id="failed-run",
                                     recall_number=recall, snapshot_id=store.snapshot_id)
    assert envelope.status == "unresolved" and envelope.result is None
    assert envelope.error.automatic_retry_allowed is False
    assert envelope.trace.model_attempts == len(seen) == (0 if failure == "reserve" else 1)
    assert envelope.trace.repair_count == 0
    expected = {"reserve": ("accounting", "usage_reservation_failed", "not_sent"),
                "settle": ("accounting", "usage_settlement_failed", "response_received"),
                "timeout": ("interpretation", "provider_failure", "outcome_unknown"),
                "semantic": ("validation", "citation_source_failed", "response_received"),
                "missing-usage": ("accounting", "usage_missing", "response_received")}[failure]
    assert (envelope.error.stage, envelope.error.code, envelope.error.request_state) == expected
    if failure != "semantic": assert envelope.trace.estimated_cost_usd is None
    if failure == "settle":
        assert envelope.trace.calls[0].input_tokens == 4000
        assert budget.summary()[0]["state"] == "reserved"
    if failure == "timeout": assert envelope.trace.calls[0].input_tokens is None
    if failure == "missing-usage":
        assert envelope.trace.calls[0].response_id == "response-no-usage"
        assert envelope.trace.calls[0].input_tokens is None
    assert "secret-diagnostic" not in envelope.model_dump_json()
    assert active_run.get() is None


def test_preflight_and_partial_retrieval_have_no_model_calls(store, tmp_path):
    budget = Budget(tmp_path / "usage.sqlite")
    for recall, points, stage in [("invented", [], "preflight"), (GROUP_A[0], [], "retrieval")]:
        with client_for([], []) as client:
            envelope = run_a1_with_trace(store, retriever_for(store, points, []), client, budget,
                                         run_id="no-request-" + stage, recall_number=recall,
                                         snapshot_id=store.snapshot_id)
        assert envelope.status == "unresolved" and envelope.error.stage == stage
        assert envelope.trace.model_attempts == 0 and envelope.trace.calls == []
        assert envelope.error.request_state == "not_sent"
    assert ledger_links(budget.path) == []


def test_committed_reservation_is_not_counted_as_sent_request(store, tmp_path, monkeypatch):
    budget = Budget(tmp_path / "usage.sqlite")
    proposal, _ = fixture_output(store, GROUP_A[0])
    def interrupt(call_id):
        raise RuntimeError("simulated interruption before request dispatch")
    monkeypatch.setattr("interpreter.request_started", interrupt)
    seen = []
    with client_for([(json.dumps(proposal), "completed")], seen) as client:
        with pytest.raises(RuntimeError, match="before request dispatch"):
            run_a1_with_trace(store, retriever_for(store, points_for(store, GROUP_A[0]), []), client,
                               budget, run_id="interrupted", recall_number=GROUP_A[0],
                               snapshot_id=store.snapshot_id)
    assert seen == []
    assert budget.summary()[0]["state"] == "reserved"
    assert ledger_links(budget.path)[0][0] == "interrupted"
    assert active_run.get() is None


@pytest.mark.parametrize("run_id", ["", "  ", None, 123])
def test_invalid_run_id_rejected_before_requests(store, tmp_path, run_id):
    cloud, model = [], []
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([], model) as client:
        with pytest.raises(ValueError):
            run_a1_with_trace(store, retriever_for(store, [], cloud), client, budget,
                               run_id=run_id, recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    assert cloud == model == budget.summary() == []


def test_concurrent_runs_have_separate_traces_and_persistent_links(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    budget = Budget(tmp_path / "usage.sqlite")
    barrier = Barrier(2)
    def worker(run_id):
        with FDAStore(path) as store:
            proposal, _ = fixture_output(store, GROUP_A[0])
            original = client_for([(json.dumps(proposal), "completed")], [])
            create = original.responses.create
            def synchronize(**kwargs):
                barrier.wait(timeout=10)
                return create(**kwargs)
            original.responses.create = synchronize
            with original as client:
                return run_a1_with_trace(store, retriever_for(store, points_for(store, GROUP_A[0]), []),
                    client, budget, run_id=run_id, recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ["concurrent-A", "concurrent-B"]))
    links = dict(ledger_links(budget.path))
    assert len(set(links.values())) == 2
    for result in results:
        assert result.status == "validated" and result.trace.model_attempts == 1
        assert result.trace.calls[0].ledger_call_id == links[result.run_id]
    assert active_run.get() is None


@pytest.mark.parametrize("status,has_result,has_error", [
    ("validated", False, False), ("validated", True, True),
    ("unresolved", True, True), ("unresolved", False, False),
])
def test_envelope_rejects_contradictory_outcomes(store, status, has_result, has_error):
    _, expected = fixture_output(store, GROUP_A[0])
    trace = RunTrace(recall_number=GROUP_A[0], snapshot_id=store.snapshot_id,
                     collection="recallready_fda_food_a1_v1", embedding_model="test",
                     max_output_tokens=4000, started_utc="offline-test")
    error = RunError(stage="validation", code="citation_source_failed",
                     message="Review required", request_state="response_received")
    with pytest.raises(ValueError):
        A1RunEnvelope.model_validate(dict(run_id="invalid-outcome", status=status,
            result=expected if has_result else None,
            error=error if has_error else None, trace=trace))
