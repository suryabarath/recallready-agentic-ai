"""A3 contract tests using the actual A2 Pydantic model."""
import pytest
from a2_agent import A2RunEnvelope, InventoryFinding
from a3_agent import plan_response

BASE = dict(case_id="case-1", run_id="run-1", recall_number="R-1",
            snapshot_id="snap-1", event_id="event-1")


def finding(status, item="item-1", lot="matched"):
    return InventoryFinding(
        **BASE, inventory_set_id="SIMSET-001", item_id=item,
        retailer_id="retailer-1", store_id="store-1", brand="Brand",
        product_label="Product", package_size="12 oz", lot_code="LOT-1",
        upc="012345678905", simulated_quantity=2, quantity_unit="units",
        inventory_reference_date="2026-01-01", match_status=status,
        lot_match=lot, brand_match="matched", product_name_match="matched",
        package_size_match="matched", upc_match="unknown",
        reason_codes=("deterministic_comparison",), a1_evidence_ids=["ev-1"],
        requires_human_review=status == "partial")


def test_exact_recommends_review_without_mutation():
    a2 = A2RunEnvelope(**BASE, status="matched", findings=[finding("exact")])
    a3 = plan_response(a2)
    assert a3.status == "planned"
    assert a3.suggested_actions[0].action_code == "REVIEW_ITEM"
    assert a3.suggested_actions[0].evidence_ids == ["ev-1"]
    assert a3.requires_human_review


def test_partial_unknown_lot_requires_verification():
    a2 = A2RunEnvelope(**BASE, status="partial", findings=[finding("partial", lot="unknown")],
                       requires_human_review=True)
    assert plan_response(a2).suggested_actions[0].action_code == "VERIFY_LOT"


def test_partial_known_lot_requests_information():
    a2 = A2RunEnvelope(**BASE, status="partial", findings=[finding("partial")],
                       requires_human_review=True)
    assert plan_response(a2).suggested_actions[0].action_code == "REQUEST_MORE_INFORMATION"


def test_no_match_is_not_safety_clearance():
    a2 = A2RunEnvelope(**BASE, status="no_match")
    action = plan_response(a2).suggested_actions[0]
    assert action.action_code == "RECORD_NO_DEMONSTRATED_MATCH"
    assert action.item_id is None and action.evidence_ids == []
    assert "not a safety clearance" in action.reason


def test_unresolved_never_becomes_no_match():
    from a2_agent import A2Error
    a2 = A2RunEnvelope(**BASE, status="unresolved", error=A2Error(
        code="ambiguous_recall_scope", message="Scope unclear"), requires_human_review=True)
    a3 = plan_response(a2)
    assert a3.status == "unresolved" and not a3.suggested_actions


def test_duplicate_item_ids_are_rejected():
    a2 = A2RunEnvelope(**BASE, status="matched", findings=[finding("exact"), finding("exact")])
    with pytest.raises(ValueError, match="duplicate item_id"):
        plan_response(a2)
