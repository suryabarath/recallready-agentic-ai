"""Offline Cloud Inference contract and exact SQLite hit validation."""

from copy import deepcopy
from email.message import Message
from io import BytesIO
import ssl
from urllib.request import BaseHandler
from urllib.response import addinfourl

import pytest

from fda_store import FDAStore, build_fda_store
from qdrant_a1 import (COLLECTION, FILTER_FIELDS, MODEL, QdrantA1, QdrantA1Error,
                       cloud_point, collection_config)
from embedding_inputs import load_embedding_inputs
from source import DEVELOPMENT_RECORDS


def test_https_transport_uses_certifi_trust_store(tmp_path, monkeypatch):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"result":{"exists":false}}'

    class Opener:
        def open(self, request, *, timeout):
            seen.update(timeout=timeout, api_key=request.get_header("Api-key"))
            return Response()

    def fake_build_opener(https_handler, redirect_handler):
        seen["context"] = https_handler._context
        return Opener()

    monkeypatch.setattr("qdrant_a1.build_opener", fake_build_opener)
    with FDAStore(path) as store:
        client = QdrantA1("https://example.qdrant.io", "offline-test-key", store)
        assert client._request("GET", "/collections/example/exists", None) == {
            "result": {"exists": False}
        }
    assert seen["timeout"] == 30
    assert seen["api_key"] == "offline-test-key"
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED
    assert seen["context"].check_hostname is True


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as opened:
        yield opened


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
@pytest.mark.parametrize("destination", [
    "https://other.example/collect", "http://other.example/collect",
    "https://example.qdrant.io/redirected",
])
def test_redirects_never_forward_credentials(store, monkeypatch, code, method, destination):
    calls = []

    class RedirectingHTTPS(BaseHandler):
        handler_order = 100

        def https_open(self, request):
            calls.append((request.full_url, request.get_header("Api-key")))
            headers = Message()
            headers["Location"] = destination
            response = addinfourl(BytesIO(b""), headers, request.full_url, code)
            response.msg = "Redirect"
            return response

    # Exercise the real opener and redirect machinery; only the network is simulated.
    monkeypatch.setattr("qdrant_a1.HTTPSHandler", lambda **kwargs: RedirectingHTTPS())
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store)
    with pytest.raises(QdrantA1Error, match="request failed"):
        client._request(method, "/collections", {} if method != "GET" else None)
    assert calls == [("https://example.qdrant.io/collections", "dummy-key")]


@pytest.mark.parametrize("text,top_k", [
    (None, 4), (123, 4), ([], 4), (b"lot", 4), ("", 4), ("  ", 4),
    ("lot", True), ("lot", False), ("lot", 1.5), ("lot", "4"),
    ("lot", None), ("lot", 0), ("lot", 9),
])
def test_invalid_query_input_never_calls_transport(store, text, top_k):
    calls = []
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: calls.append(args))
    with pytest.raises(QdrantA1Error, match="Query text or top_k"):
        client.query(text, recall_number=DEVELOPMENT_RECORDS[0],
                     snapshot_id=store.snapshot_id, top_k=top_k)
    assert calls == []


@pytest.mark.parametrize("response", [
    None, [], "invalid", {}, {"result": None}, {"result": []},
    {"result": {"points": None}}, {"result": {"points": {}}},
    {"result": {"points": [None]}}, {"result": {"points": [12]}},
    {"result": {"points": [{"payload": None}]}},
    {"result": {"points": [{"payload": ["bad"]}]}},
])
def test_malformed_query_response_has_defined_error(store, response):
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: response)
    with pytest.raises(QdrantA1Error):
        client.query("lot", recall_number=DEVELOPMENT_RECORDS[0],
                     snapshot_id=store.snapshot_id)


@pytest.mark.parametrize("response", [None, [], {"result": None}, {"result": []}])
def test_malformed_existence_response_never_creates_collection(store, response):
    calls = []

    def transport(*args):
        calls.append(args)
        return response

    client = QdrantA1("https://example.qdrant.io", "dummy-key", store, transport=transport)
    with pytest.raises(QdrantA1Error):
        client.create_new_collection()
    assert len(calls) == 1 and calls[0][0] == "GET"


@pytest.fixture
def valid_point(store):
    recall = DEVELOPMENT_RECORDS[0]
    record = store.lookup(recall, snapshot_id=store.snapshot_id)
    exact = store.resolve(f"EV-{recall}-CODE_INFO", recall_number=recall,
                          event_id=record["event_id"], snapshot_id=store.snapshot_id)
    return {"id": exact.point_id, "score": 0.84, "payload": {
        "evidence_id": exact.evidence_id, "recall_number": recall,
        "event_id": exact.event_id, "snapshot_id": exact.snapshot_id,
        "field_name": exact.field_name, "source_system": "openFDA_food_enforcement",
    }}


@pytest.mark.parametrize("field,value", [
    ("recall_number", DEVELOPMENT_RECORDS[1]), ("event_id", "wrong-event"),
    ("snapshot_id", "wrong-snapshot"), ("evidence_id", "invented-id"),
    ("evidence_id", f"EV-{DEVELOPMENT_RECORDS[1]}-CODE_INFO"),
    ("field_name", "wrong-field"), ("source_system", "wrong-source"),
])
def test_untrusted_hit_metadata_is_rejected(store, valid_point, field, value):
    valid_point["payload"][field] = value
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: {"result": {"points": [valid_point]}})
    with pytest.raises(QdrantA1Error):
        client.query("lot", recall_number=DEVELOPMENT_RECORDS[0], snapshot_id=store.snapshot_id)


@pytest.mark.parametrize("score", [None, True, "0.8", float("nan"), float("inf"), -float("inf")])
def test_invalid_scores_are_rejected(store, valid_point, score):
    valid_point["score"] = score
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: {"result": {"points": [valid_point]}})
    with pytest.raises(QdrantA1Error, match="score is invalid"):
        client.query("lot", recall_number=DEVELOPMENT_RECORDS[0], snapshot_id=store.snapshot_id)


@pytest.mark.parametrize("failure", ["duplicate", "wrong-point-id", "too-many"])
def test_duplicate_wrong_id_and_excess_hits_are_rejected(store, valid_point, failure):
    points = [valid_point]
    if failure == "duplicate":
        points.append(deepcopy(valid_point))
    elif failure == "wrong-point-id":
        valid_point["id"] = "wrong-point-id"
    else:
        points *= 9
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: {"result": {"points": points}})
    with pytest.raises(QdrantA1Error):
        client.query("lot", recall_number=DEVELOPMENT_RECORDS[0], snapshot_id=store.snapshot_id)


@pytest.mark.parametrize("top_k", [1, 8])
def test_valid_query_limits_allow_empty_results(store, top_k):
    client = QdrantA1("https://example.qdrant.io", "dummy-key", store,
                      transport=lambda *args: {"result": {"points": []}})
    assert client.query("lot", recall_number=DEVELOPMENT_RECORDS[0],
                        snapshot_id=store.snapshot_id, top_k=top_k) == ()


def test_new_collection_plan_and_72_cloud_points(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    calls = []

    def transport(method, path, body):
        calls.append((method, path, body))
        if path.endswith("/exists"):
            return {"result": {"exists": False}}
        if path.endswith("/index?wait=true"):
            return {"status": "ok"}
        if method == "PUT" and path.endswith("/points?wait=true"):
            return {"status": "ok"}
        return {"result": True}

    with FDAStore(path) as store:
        client = QdrantA1("https://example.qdrant.io", "offline-test-key", store,
                          transport=transport)
        client.create_new_collection()
        client.upsert_verified()
        inputs = load_embedding_inputs(store)
        assert cloud_point(inputs[0])["vector"] == {"text": inputs[0].text_for_embedding,
                                                    "model": MODEL}
    assert calls[0][:2] == ("GET", f"/collections/{COLLECTION}/exists")
    assert calls[1] == ("PUT", f"/collections/{COLLECTION}", collection_config())
    index_calls = calls[2:4]
    assert [body for method, path, body in index_calls] == [
        {"field_name": name, "field_schema": "keyword"} for name in FILTER_FIELDS
    ]
    assert all(path == f"/collections/{COLLECTION}/index?wait=true"
               for method, path, body in index_calls)
    batches = [body["points"] for method, path, body in calls[4:]]
    assert len(batches) == 5 and sum(map(len, batches)) == 72
    assert len({point["id"] for batch in batches for point in batch}) == 72
    assert all(point["vector"]["model"] == MODEL for batch in batches for point in batch)


def test_existing_collection_is_not_modified(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    calls = []

    def transport(method, path, body):
        calls.append(method)
        return {"result": {"exists": True}}

    with FDAStore(path) as store:
        client = QdrantA1("https://example.qdrant.io", "offline-test-key", store,
                          transport=transport)
        with pytest.raises(QdrantA1Error, match="already exists"):
            client.create_new_collection()
    assert calls == ["GET"]


def test_query_filters_then_resolves_hit_exactly(tmp_path):
    path = tmp_path / "fda.sqlite"
    build_fda_store(path)
    with FDAStore(path) as store:
        record = store.lookup(DEVELOPMENT_RECORDS[0], snapshot_id=store.snapshot_id)
        exact = store.resolve(f"EV-{DEVELOPMENT_RECORDS[0]}-CODE_INFO",
                              recall_number=DEVELOPMENT_RECORDS[0],
                              event_id=record["event_id"], snapshot_id=store.snapshot_id)
        point = {"id": exact.point_id, "score": 0.84,
                 "payload": {"evidence_id": exact.evidence_id,
                             "recall_number": exact.recall_number,
                             "event_id": exact.event_id,
                             "snapshot_id": exact.snapshot_id,
                             "field_name": exact.field_name,
                             "source_system": "openFDA_food_enforcement"}}
        seen = []

        def transport(method, path, body):
            seen.append((method, path, body))
            return {"result": {"points": [point]}}

        client = QdrantA1("https://example.qdrant.io", "offline-test-key", store,
                          transport=transport)
        hits = client.query("donut lot", recall_number=DEVELOPMENT_RECORDS[0],
                            snapshot_id=store.snapshot_id)
        assert hits[0].original_text == exact.original_text
        assert hits[0].evidence_id == exact.evidence_id
        assert seen[0][2]["query"]["model"] == MODEL
        assert seen[0][2]["filter"]["must"] == [
            {"key": "recall_number", "match": {"value": DEVELOPMENT_RECORDS[0]}},
            {"key": "snapshot_id", "match": {"value": store.snapshot_id}},
        ]
        bad = deepcopy(point)
        bad["payload"]["recall_number"] = DEVELOPMENT_RECORDS[1]
        point = bad
        with pytest.raises(QdrantA1Error, match="metadata differs"):
            client.query("donut lot", recall_number=DEVELOPMENT_RECORDS[0],
                         snapshot_id=store.snapshot_id)
