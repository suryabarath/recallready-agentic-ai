"""A2 integration using generated tiny SQLite stores, never the frozen inventory."""

import hashlib
import json
import sqlite3

import pytest

from a1_run import run_a1_with_trace
from a2_agent import A2RunEnvelope, run_a2
from case_state import CaseState
from coordinator import A1Coordinator
from interpreter import Budget
from inventory_loader import InventoryLoadError, build_inventory_store
from inventory_store import InventoryStore, InventoryStoreError
from source import DEVELOPMENT_RECORDS, GROUP_A, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_coordinator import request_for
from test_interpreter import client_for
from test_inventory_match import _make_row


def make_inventory(tmp_path, snapshot_id, secondary=None, **overrides):
    primary = _make_row(item_id="ISOLATED-001-A", **overrides)
    distractor = secondary if secondary is not None else _make_row(
        item_id="ISOLATED-001-B", product_label="Unrelated synthetic product",
        lot_code="different", upc="999999999999", package_size="99 oz")
    payload = {"synthetic": True, "reference_snapshot_id": snapshot_id,
               "records": [primary.model_dump(), distractor.model_dump()]}
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    db = tmp_path / "synthetic.sqlite"
    build_inventory_store(db, json_path=path, expected_set_count=1, expected_record_count=2)
    return db, path


def graph_run(store, tmp_path, inventory, recall=GROUP_A[0]):
    proposal, _ = fixture_output(store, recall)
    requests = []
    with client_for([(json.dumps(proposal), "completed")], requests) as client:
        graph = A1Coordinator(
            store, retriever_for(store, points_for(store, recall), []), client,
            Budget(tmp_path / "usage.sqlite"), inventory_store=inventory)
        result = graph.run(request_for(store, recall))
        assert not client.is_closed()
    assert len(requests) == 1
    return result


@pytest.mark.parametrize("variant,expected,route", [
    ({}, "matched", "a2_completed"),
    ({"lot_code": "wrong-lot"}, "no_match", "a2_completed"),
    ({"lot_code": ""}, "partial", "human_review"),
    ({"package_size": ""}, "partial", "human_review"),
    ({"upc": ""}, "partial", "human_review"),
    ({"package_size": "14 oz"}, "no_match", "a2_completed"),
    ({"upc": "999999999999"}, "no_match", "a2_completed"),
])
def test_actual_sqlite_matching_and_routing(store, tmp_path, variant, expected, route):
    db, _ = make_inventory(tmp_path, store.snapshot_id, **variant)
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    with InventoryStore(db) as inventory:
        result = graph_run(store, tmp_path, inventory)
        assert inventory.resolve_candidate_ids(("ISOLATED-001-A",))[0].lot_code == variant.get("lot_code", "26078")
    assert result.status == route and result.a2.status == expected
    assert result.errors == []
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    assert CaseState.model_validate_json(result.model_dump_json()) == result
    assert all(f.item_id != "ISOLATED-001-B" for f in result.a2.findings)
    if expected != "no_match":
        finding = result.a2.findings[0]
        assert finding.item_id == "ISOLATED-001-A"
        assert finding.simulated_quantity == 12
        assert finding.store_id == "SIM-STORE-02"
        assert set(finding.a1_evidence_ids) <= set(result.a1.result.facts.evidence_ids)
    assert result.events[-1].event == route


class FailureStore:
    def __init__(self, snapshot_id, mode):
        self.snapshot_id = snapshot_id
        self.mode = mode
        self.calls = 0

    def find_inventory_candidates(self, **kwargs):
        self.calls += 1
        if self.mode == "store_error":
            raise InventoryStoreError("private store diagnostic")
        raise RuntimeError("private unexpected diagnostic")


@pytest.mark.parametrize("mode", ["store_error", "unexpected_error", "snapshot_mismatch"])
def test_a2_failure_returns_unresolved_without_repeating_a1(store, tmp_path, mode):
    inventory = FailureStore("wrong-snapshot" if mode == "snapshot_mismatch" else store.snapshot_id, mode)
    result = graph_run(store, tmp_path, inventory)
    assert result.status == "unresolved" and result.a1.status == "validated"
    assert result.errors and not result.errors[0].automatic_retry_allowed
    assert result.events[-1].event == "stopped"
    assert "private" not in result.model_dump_json()
    assert inventory.calls == (0 if mode == "snapshot_mismatch" else 1)


@pytest.mark.parametrize("recall", DEVELOPMENT_RECORDS)
def test_integration_preserves_all_a1_outputs_and_review_gate(store, tmp_path, recall):
    inventory = FailureStore(store.snapshot_id, "unexpected_error")
    _, expected = fixture_output(store, recall)
    base = expected.get("base", expected)
    needs_review = recall in GROUP_C or bool(base["facts"]["uncertainties"])
    result = graph_run(store, tmp_path, inventory, recall)
    assert result.a1.result.model_dump() == expected
    assert result.status == ("human_review" if needs_review else "unresolved")
    assert inventory.calls == (0 if needs_review else 1)
    if needs_review:
        assert result.a2 is None


def matched_state(store, tmp_path):
    db, _ = make_inventory(tmp_path, store.snapshot_id)
    with InventoryStore(db) as inventory:
        return graph_run(store, tmp_path, inventory)


@pytest.mark.parametrize("field", ["case_id", "run_id", "recall_number", "snapshot_id", "event_id"])
def test_rejects_cross_context_findings(store, tmp_path, field):
    altered = matched_state(store, tmp_path).model_dump()
    altered["a2"]["findings"][0][field] = "other-context"
    with pytest.raises(ValueError, match="context"):
        CaseState.model_validate(altered)


@pytest.mark.parametrize("field,value", [
    ("a1_evidence_ids", ["EV-INVENTED"]),
    ("a1_evidence_ids", ["EV-F-1542-2023-CODE_INFO"]),
    ("a1_identifier_values", ("invented-lot",)),
])
def test_rejects_unsupported_a2_provenance(store, tmp_path, field, value):
    altered = matched_state(store, tmp_path).model_dump()
    altered["a2"]["findings"][0][field] = value
    with pytest.raises(ValueError, match="outside validated A1"):
        CaseState.model_validate(altered)


def test_partial_review_cannot_be_removed(store, tmp_path):
    db, _ = make_inventory(tmp_path, store.snapshot_id, package_size="")
    with InventoryStore(db) as inventory:
        result = graph_run(store, tmp_path, inventory)
    altered = result.model_dump()
    altered.update(status="a2_completed", review_reason=None)
    with pytest.raises(ValueError, match="review requirement"):
        CaseState.model_validate(altered)
    altered = result.a2.model_dump()
    altered["requires_human_review"] = False
    with pytest.raises(ValueError, match="review"):
        A2RunEnvelope.model_validate(altered)


def test_duplicate_or_mismatched_exact_findings_are_rejected(store, tmp_path):
    result = matched_state(store, tmp_path)
    altered = result.a2.model_dump()
    altered["findings"].append(altered["findings"][0].copy())
    with pytest.raises(ValueError, match="Duplicate"):
        A2RunEnvelope.model_validate(altered)
    altered = result.a2.model_dump()
    altered["findings"][0]["package_size_match"] = "mismatched"
    with pytest.raises(ValueError, match="concrete attribute mismatch"):
        A2RunEnvelope.model_validate(altered)


def test_integration_graph_contains_a2_and_no_a3(store, tmp_path):
    with client_for([], []) as client:
        graph = A1Coordinator(store, retriever_for(store, [], []), client,
                              Budget(tmp_path / "usage.sqlite"),
                              inventory_store=FailureStore(store.snapshot_id, "unexpected_error"))
        assert set(graph._graph.get_graph().nodes) == {
            "__start__", "__end__", "begin", "interpret_a1", "complete", "review", "stop",
            "investigate_a2", "a2_complete"}


def test_read_only_sqlite_and_candidate_ids(store, tmp_path):
    db, _ = make_inventory(tmp_path, store.snapshot_id, lot_code="000123")
    with InventoryStore(db) as inventory:
        with pytest.raises(sqlite3.OperationalError):
            inventory._db.execute("DELETE FROM inventory")
        assert [r.lot_code for r in inventory.find_inventory_candidates(None, None, ("000123",), ())] == ["000123"]
        assert inventory.find_inventory_candidates(None, None, ("123",), ()) == []
        assert inventory.resolve_candidate_ids(("invented-id",)) == []
        assert inventory.find_inventory_candidates(None, None, ("000123",), (), candidate_item_ids=()) == []


def test_loader_refuses_overwrite_and_preserves_source(store, tmp_path):
    db, path = make_inventory(tmp_path, store.snapshot_id)
    with pytest.raises(InventoryLoadError, match="overwrite"):
        build_inventory_store(db, json_path=path, expected_set_count=1, expected_record_count=2)
    with InventoryStore(db) as inventory:
        assert inventory.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_standalone_a2_rejects_context_before_inventory_access(store, tmp_path):
    recall = GROUP_A[0]
    proposal, _ = fixture_output(store, recall)
    with client_for([(json.dumps(proposal), "completed")], []) as client:
        envelope = run_a1_with_trace(store, retriever_for(store, points_for(store, recall), []),
                                    client, Budget(tmp_path / "usage.sqlite"),
                                    run_id="run-standalone", recall_number=recall, snapshot_id=store.snapshot_id)
    inventory = FailureStore(store.snapshot_id, "unexpected_error")
    for context in ({"run_id": "other"}, {"recall_number": "other"},
                    {"snapshot_id": "other"}, {"event_id": "other"}):
        result = run_a2(inventory, envelope, case_id="standalone", **context)
        assert result.status == "unresolved" and result.error.code == "a1_context_mismatch"
    assert inventory.calls == 0


def test_exact_and_partial_rows_keep_separate_quantities_and_review(store, tmp_path):
    second = _make_row(item_id="ISOLATED-001-B", simulated_quantity=44,
                       store_id="other-store", package_size="")
    db, _ = make_inventory(tmp_path, store.snapshot_id, secondary=second)
    with InventoryStore(db) as inventory:
        result = graph_run(store, tmp_path, inventory)
    assert result.status == "human_review" and result.a2.status == "matched"
    assert [(f.item_id, f.match_status, f.simulated_quantity, f.store_id) for f in result.a2.findings] == [
        ("ISOLATED-001-A", "exact", 12, "SIM-STORE-02"),
        ("ISOLATED-001-B", "partial", 44, "other-store"),
    ]
    assert result.a2.requires_human_review


@pytest.mark.parametrize("field", ["case_id", "run_id", "recall_number", "snapshot_id", "event_id"])
def test_rejects_replacement_a2_envelope_context(store, tmp_path, field):
    altered = matched_state(store, tmp_path).model_dump()
    altered["a2"][field] = "other-context"
    altered["a2"]["findings"][0][field] = "other-context"
    with pytest.raises(ValueError, match="case/run context"):
        CaseState.model_validate(altered)


def test_invalid_a2_return_becomes_safe_unresolved_case(store, tmp_path, monkeypatch):
    valid = matched_state(store, tmp_path)
    altered = valid.a2.model_dump()
    altered["findings"][0]["a1_evidence_ids"] = ["EV-INVENTED"]
    invalid_provenance = A2RunEnvelope.model_validate(altered)
    monkeypatch.setattr("coordinator.run_a2", lambda *args, **kwargs: invalid_provenance)
    result = graph_run(store, tmp_path, FailureStore(store.snapshot_id, "unexpected_error"))
    assert result.status == "unresolved" and result.a2 is None
    assert result.errors[0].code == "inventory_match_failed"


def test_closed_real_sqlite_is_unresolved(store, tmp_path):
    db, _ = make_inventory(tmp_path, store.snapshot_id)
    inventory = InventoryStore(db)
    inventory.close()
    result = graph_run(store, tmp_path, inventory)
    assert result.status == "unresolved"
    assert result.a2.error.code == "inventory_store_unavailable"
