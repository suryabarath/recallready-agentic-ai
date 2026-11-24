"""Explicit dataset checks: pytest this file after preparing the private subset.

The filename deliberately keeps external-data checks outside default discovery.
Missing data fails this explicitly requested run; no test is skipped.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from case_state import CaseState
from coordinator import A1Coordinator
from development_inventory import INVENTORY, load_development_package
from interpreter import Budget
from inventory_loader import build_inventory_store
from inventory_store import InventoryStore
from source import DEVELOPMENT_RECORDS, GROUP_C
from test_a1_service import fixture_output, points_for, retriever_for, store
from test_interpreter import client_for


@pytest.fixture(scope="module")
def development():
    directory = Path(os.environ.get("RECALLREADY_A2_DEVELOPMENT_DIR",
                                   Path(__file__).resolve().parents[1] / "runtime" / "a2_development_18_v1"))
    return load_development_package(directory)


@pytest.mark.parametrize("recall", DEVELOPMENT_RECORDS)
@pytest.mark.parametrize("enable_a3,enable_a4,corrections", [
    (False, False, False), (True, False, False), (True, True, False), (True, True, True)])
def test_real_development_case(store, tmp_path, development, recall, record_property,
                               enable_a3, enable_a4, corrections):
    payload, cases, _ = development
    case = next(c for c in cases if c["recall_number"] == recall)
    rows = [r for r in payload["records"] if r["inventory_set_id"] == case["inventory_set_id"]]
    # Coordinator has no inventory-set input yet. Supply only this case's
    # original pair to avoid broadening the search across other scenarios.
    case_json = tmp_path / "case_inventory.json"
    case_json.write_text(json.dumps(dict(payload, records=rows)), encoding="utf-8")
    db = tmp_path / "case_inventory.sqlite"
    build_inventory_store(db, json_path=case_json, expected_set_count=1, expected_record_count=2)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    proposal, expected_a1 = fixture_output(store, recall)
    model_calls, cloud_calls, inventory_queries = [], [], []
    with InventoryStore(db) as inventory:
        inventory._db.set_trace_callback(inventory_queries.append)
        with client_for([(json.dumps(proposal), "completed")], model_calls) as client:
            result = A1Coordinator(store, retriever_for(store, points_for(store, recall), cloud_calls),
                                   client, Budget(tmp_path / "usage.sqlite"), inventory_store=inventory,
                                   enable_a3=enable_a3, enable_a4=enable_a4,
                                   enable_targeted_corrections=corrections).run({
                "case_id": case["case_id"], "run_id": "development-" + recall,
                "recall_number": recall, "snapshot_id": case["snapshot_id"], "event_id": case["event_id"],
            })
    assert len(model_calls) == len(cloud_calls) == 1
    assert result.a1.result.model_dump() == expected_a1
    assert result.revision_count == 0 and result.correction is None
    base = expected_a1.get("base", expected_a1)
    needs_review = recall in GROUP_C or bool(base["facts"]["uncertainties"])
    if needs_review:
        assert result.status == "human_review" and result.a2 is None
        assert result.a4 is None
        assert not inventory_queries
    else:
        assert result.a2 is not None
        if result.a2.status == "unresolved":
            assert result.status == "unresolved"
            assert result.a2.error.code == "ambiguous_recall_scope"
        else:
            assert result.status == ("human_review" if result.a2.requires_human_review or enable_a3 else "a2_completed")
            if enable_a3 and not result.a2.requires_human_review:
                assert result.a3 is not None and result.a3.status == "planned"
                assert result.a3.requires_human_review
                if enable_a4:
                    assert result.a4.verdict == "human_review" and result.a4.findings == []
                    assert result.a4.review_boundary_verified and not result.a4.trace.llm_invoked
        originals = {row["item_id"]: row for row in rows}
        for finding in result.a2.findings:
            original = originals[finding.item_id]
            for name in ("inventory_set_id", "retailer_id", "store_id", "brand", "product_label",
                         "package_size", "lot_code", "upc", "simulated_quantity", "quantity_unit",
                         "inventory_reference_date"):
                assert getattr(finding, name) == original[name]
            assert set(finding.a1_evidence_ids) <= set(base["facts"]["evidence_ids"])
            if finding.match_status == "exact":
                lots = {i["value"] for i in base["facts"]["identifiers"] if i["kind"] in ("lot", "batch")}
                assert finding.lot_code in lots
                assert finding.lot_match == finding.product_name_match == "matched"
                assert not finding.requires_human_review
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert CaseState.model_validate_json(result.model_dump_json()) == result
    record_property("recall_number", recall)
    record_property("a3_enabled", enable_a3)
    record_property("a4_enabled", enable_a4)
    record_property("targeted_corrections_enabled", corrections)
    record_property("inventory_set_id", case["inventory_set_id"])
    record_property("case_status", result.status)
    record_property("a2_status", result.a2.status if result.a2 else "not_run_requires_A1_review")
    record_property("finding_count", len(result.a2.findings) if result.a2 else 0)


def test_full_selected_store_preserves_all_36_rows(tmp_path, development):
    payload, cases, _ = development
    path = tmp_path / INVENTORY
    path.write_text(json.dumps(payload), encoding="utf-8")
    db = tmp_path / "all_development.sqlite"
    build_inventory_store(db, json_path=path, expected_set_count=18, expected_record_count=36)
    with InventoryStore(db) as inventory:
        assert inventory.set_count == len(cases) == 18
        assert inventory.record_count == len(payload["records"]) == 36
        actual = inventory.resolve_candidate_ids(tuple(row["item_id"] for row in payload["records"]))
        assert {r.item_id: r.model_dump() for r in actual} == {r["item_id"]: r for r in payload["records"]}
