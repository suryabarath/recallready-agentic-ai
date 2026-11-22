"""Optional real Agent 2 contract compatibility test (no real datasets)."""

import pytest


def test_real_a2_pydantic_envelope_is_accepted_if_agent2_is_present():
    a2_module = pytest.importorskip("a2_agent", reason="A2 branch is not on this feature branch")
    from a3_agent import plan_response

    shared = dict(case_id="case-1", run_id="run-1", recall_number="H-0011-2027",
                  snapshot_id="snap-1", event_id="event-1")
    finding = a2_module.InventoryFinding(
        **shared, inventory_set_id="SIM-SET-1", item_id="INV-001",
        retailer_id="retailer-1", store_id="store-1", brand="Brand",
        product_label="Product", package_size="12 oz", lot_code="26078",
        upc="850041392103", simulated_quantity=2, quantity_unit="units",
        inventory_reference_date="2026-01-01", match_status="exact",
        lot_match="matched", brand_match="matched", product_name_match="matched",
        package_size_match="matched", upc_match="matched",
        reason_codes=("deterministic_comparison",),
        a1_evidence_ids=["ev-1"], requires_human_review=False,
    )
    result = a2_module.A2RunEnvelope(**shared, status="matched", findings=[finding])
    a3 = plan_response(result)
    assert a3.suggested_actions[0].action_code == "REVIEW_ITEM"
    assert a3.suggested_actions[0].evidence_ids == ["ev-1"]
