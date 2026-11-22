"""Offline integration: real source, retriever, SDK and output validators."""

from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest

from a1_service import A1RunError, RETRIEVAL_QUERY, run_a1
from fda_store import FDAStore, build_fda_store
from interpreter import Budget
from qdrant_a1 import COLLECTION, QdrantA1, QdrantA1Error
from reviews import load_reviews
from source import DEVELOPMENT_RECORDS, FIELDS, GROUP_A, GROUP_C
from test_group_b import expected_result
from test_group_c_contract import example
from test_group_c_interpreter import proposal as group_c_proposal
from test_interpreter import EXAMPLES, REVIEW_PATH, client_for


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as opened:
        yield opened


def points_for(store, recall):
    record = store.lookup(recall, snapshot_id=store.snapshot_id)
    points = []
    for field in FIELDS:
        evidence = store.resolve(f"EV-{recall}-{field.upper()}", recall_number=recall,
                                 event_id=record["event_id"], snapshot_id=store.snapshot_id)
        points.append(dict(id=evidence.point_id, score=0.75, payload={
            key: getattr(evidence, key) for key in
            ("evidence_id", "recall_number", "event_id", "snapshot_id", "field_name")
        }))
        points[-1]["payload"]["source_system"] = "openFDA_food_enforcement"
    return points


def retriever_for(store, points, calls):
    def transport(method, path, body):
        calls.append((method, path, body))
        return {"result": {"points": points}}
    return QdrantA1("https://example.qdrant.io", "dummy-qdrant-key", store, transport=transport)


def fixture_output(store, recall):
    if recall in GROUP_C:
        return group_c_proposal(store, recall), example(store, recall)[0]
    expected = (EXAMPLES[GROUP_A.index(recall)] if recall in GROUP_A
                else expected_result(store, recall))
    proposal = dict(identifiers=[{key: item[key] for key in ("kind", "value", "evidence_ids")}
                                for item in expected["facts"]["identifiers"]],
                    uncertainties=expected["facts"]["uncertainties"])
    return proposal, expected


@pytest.mark.parametrize("recall", DEVELOPMENT_RECORDS)
def test_eighteen_complete_offline_pipelines(store, tmp_path, recall):
    proposal, expected = fixture_output(store, recall)
    cloud_calls, model_calls = [], []
    # Deliberately reverse rank order; exact fields and citations must still match.
    retriever = retriever_for(store, list(reversed(points_for(store, recall))), cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([(json.dumps(proposal), "completed")], model_calls) as client:
        result = run_a1(store, retriever, client, budget, recall_number=recall,
                        snapshot_id=store.snapshot_id)
    assert result.model_dump() == expected
    assert len(cloud_calls) == len(model_calls) == len(budget.summary()) == 1
    method, path, body = cloud_calls[0]
    assert method == "POST" and path == f"/collections/{COLLECTION}/points/query"
    assert body["query"]["text"] == RETRIEVAL_QUERY
    assert body["filter"]["must"] == [
        {"key": "recall_number", "match": {"value": recall}},
        {"key": "snapshot_id", "match": {"value": store.snapshot_id}},
    ]
    sent = json.loads(model_calls[0]["input"])
    assert len(sent) == 4
    for passage in sent:
        assert passage["original_text"] == store.resolve(
            passage["evidence_id"], recall_number=recall,
            event_id=passage["event_id"], snapshot_id=store.snapshot_id).original_text
    assert "tools" not in model_calls[0]


@pytest.mark.parametrize("failure", ["empty", "partial", "duplicate", "cross-recall", "cross-event",
                                     "cross-snapshot", "invented-id", "wrong-point"])
def test_retrieval_failure_prevents_model_and_reservation(store, tmp_path, failure):
    recall = GROUP_A[0]
    points = points_for(store, recall)
    if failure == "empty":
        points = []
    elif failure == "partial":
        points.pop()
    elif failure == "duplicate":
        points[-1] = deepcopy(points[0])
    elif failure == "wrong-point":
        points[0]["id"] = "invented-point"
    else:
        field = {"cross-recall": "recall_number", "cross-event": "event_id",
                 "cross-snapshot": "snapshot_id", "invented-id": "evidence_id"}[failure]
        points[0]["payload"][field] = "incorrect-context-or-id"
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points, cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([], model_calls) as client:
        with pytest.raises(A1RunError, match="retrieval failed"):
            run_a1(store, retriever, client, budget, recall_number=recall, snapshot_id=store.snapshot_id)
    assert len(cloud_calls) == 1
    assert model_calls == budget.summary() == []


@pytest.mark.parametrize("failure", ["recall", "snapshot", "event", "review", "cap", "retries"])
def test_invalid_preflight_makes_no_cloud_or_model_request(store, tmp_path, failure):
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points_for(store, GROUP_A[0]), cloud_calls)
    kwargs = dict(recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    if failure == "recall": kwargs["recall_number"] = "invented-recall"
    elif failure == "snapshot": kwargs["snapshot_id"] = "wrong-snapshot"
    elif failure == "event": kwargs["event_id"] = "wrong-event"
    elif failure == "review": kwargs["approved_lots"] = load_reviews(REVIEW_PATH)
    elif failure == "cap": kwargs["max_output_tokens"] = True
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([], model_calls) as client:
        if failure == "retries": client.max_retries = 2
        with pytest.raises(A1RunError, match="preflight failed"):
            run_a1(store, retriever, client, budget, **kwargs)
    assert cloud_calls == model_calls == budget.summary() == []


@pytest.mark.parametrize("recall", [GROUP_A[1], GROUP_C[0]])
@pytest.mark.parametrize("failure", ["unsupported-literal", "invented-citation", "transport"])
def test_model_errors_stop_without_semantic_retry(store, tmp_path, recall, failure):
    proposal, _ = fixture_output(store, recall)
    if failure == "unsupported-literal":
        if recall in GROUP_C:
            proposal["relations"][0]["parts"][0]["value"] = "invented-value"
        else:
            proposal["identifiers"][0]["value"] = "invented-value"
    elif failure == "invented-citation":
        if recall in GROUP_C:
            proposal["relations"][0]["evidence_id"] = "EV-INVENTED"
        else:
            proposal["identifiers"][0]["evidence_ids"] = ["EV-INVENTED"]
    response = httpx.ReadTimeout("offline timeout") if failure == "transport" else (json.dumps(proposal), "completed")
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points_for(store, recall), cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([response], model_calls) as client:
        with pytest.raises(A1RunError, match="interpretation failed"):
            run_a1(store, retriever, client, budget, recall_number=recall, snapshot_id=store.snapshot_id)
    assert len(model_calls) == len(budget.summary()) == 1
    if failure == "transport": assert budget.summary()[0]["state"] == "reserved"


def test_explicit_review_stays_out_of_model_prompt(store, tmp_path):
    recall = GROUP_A[4]
    proposal, _ = fixture_output(store, recall)
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points_for(store, recall), cloud_calls)
    with client_for([(json.dumps(proposal), "completed")], model_calls) as client:
        result = run_a1(store, retriever, client, Budget(tmp_path / "usage.sqlite"),
                        recall_number=recall, snapshot_id=store.snapshot_id,
                        approved_lots=load_reviews(REVIEW_PATH))
    assert result.facts.identifiers[0].kind == "lot"
    assert result.facts.identifiers[0].value == "04162026 BC 6937218914734"
    assert "Member 1" not in model_calls[0]["input"]


def test_service_rechecks_altered_retriever_text(store, tmp_path, monkeypatch):
    retriever = retriever_for(store, points_for(store, GROUP_A[0]), [])
    hits = list(retriever.query("lot", recall_number=GROUP_A[0], snapshot_id=store.snapshot_id))
    hits[0] = replace(hits[0], original_text="altered-text")
    monkeypatch.setattr(retriever, "query", lambda *args, **kwargs: tuple(hits))
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([], []) as client:
        with pytest.raises(A1RunError, match="differs from exact SQLite"):
            run_a1(store, retriever, client, budget, recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    assert budget.summary() == []


def test_cloud_transport_error_prevents_paid_request(store, tmp_path):
    def unavailable(*args):
        raise QdrantA1Error("offline cloud failure")
    retriever = QdrantA1("https://example.qdrant.io", "dummy-key", store, transport=unavailable)
    budget = Budget(tmp_path / "usage.sqlite")
    model_calls = []
    with client_for([], model_calls) as client:
        with pytest.raises(A1RunError, match="retrieval failed"):
            run_a1(store, retriever, client, budget, recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    assert model_calls == budget.summary() == []


def test_different_store_is_rejected_before_requests(store, tmp_path):
    other_path = tmp_path / "other.sqlite"
    build_fda_store(other_path)
    cloud_calls, model_calls = [], []
    budget = Budget(tmp_path / "usage.sqlite")
    with FDAStore(other_path) as other:
        retriever = retriever_for(other, [], cloud_calls)
        with client_for([], model_calls) as client:
            with pytest.raises(A1RunError, match="same exact FDA store"):
                run_a1(store, retriever, client, budget,
                        recall_number=GROUP_A[0], snapshot_id=store.snapshot_id)
    assert cloud_calls == model_calls == budget.summary() == []


def test_group_c_never_silently_ignores_lot_approval(store, tmp_path):
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, [], cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([], model_calls) as client:
        with pytest.raises(A1RunError, match="does not accept"):
            run_a1(store, retriever, client, budget, recall_number=GROUP_C[0],
                    snapshot_id=store.snapshot_id, approved_lots=load_reviews(REVIEW_PATH))
    assert cloud_calls == model_calls == budget.summary() == []


@pytest.mark.parametrize("recall", [GROUP_A[0], GROUP_C[0]])
def test_structural_repair_does_not_repeat_retrieval(store, tmp_path, recall):
    proposal, expected = fixture_output(store, recall)
    cloud_calls, model_calls = [], []
    retriever = retriever_for(store, points_for(store, recall), cloud_calls)
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([("{}", "completed"), (json.dumps(proposal), "completed")], model_calls) as client:
        result = run_a1(store, retriever, client, budget,
                        recall_number=recall, snapshot_id=store.snapshot_id)
    assert result.model_dump() == expected
    assert len(cloud_calls) == 1
    assert len(model_calls) == len(budget.summary()) == 2
