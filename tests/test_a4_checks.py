"""Real stores and shared source/match tools; only upstream network is replayed."""

from copy import deepcopy
import hashlib

import pytest

from a3_agent import plan_response
from a4_checks import run_deterministic_checks
from inventory_store import InventoryStore
from test_a1_service import store
from test_a3_coordinator import run_graph


@pytest.fixture
def upstream(store, tmp_path):
    state = run_graph(store, tmp_path)
    with InventoryStore(tmp_path / "synthetic.sqlite") as inventory:
        yield store, inventory, state


def audit(upstream, **kwargs):
    source, inventory, state = upstream
    selected = dict(fda_store=source, inventory_store=inventory, a1_envelope=state.a1,
        a2_envelope=state.a2, a3_envelope=state.a3, case_id=state.case_id, run_id=state.run_id,
        recall_number=state.recall_number, snapshot_id=state.snapshot_id, event_id=state.a2.event_id)
    return run_deterministic_checks(**(selected | kwargs))


def test_clean_audit_preserves_stores_and_inputs(upstream, tmp_path):
    _, _, state = upstream
    before = state.model_dump_json()
    path = tmp_path / "synthetic.sqlite"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = audit(upstream)
    assert result.fatal_error is None and result.findings == []
    assert len(result.verified_evidence_ids) == 4
    assert result.verified_item_ids == [state.a2.findings[0].item_id]
    assert result.review_boundary_verified
    assert state.model_dump_json() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("field", ["case_id", "run_id", "recall_number", "snapshot_id", "event_id"])
def test_wrong_context_stops_audit(upstream, field):
    assert audit(upstream, **{field: "wrong"}).fatal_error.code == "context_mismatch"


@pytest.mark.parametrize("change", ["text", "literal", "kind", "citation"])
def test_a1_drift_blocks(upstream, change):
    state = deepcopy(upstream[2])
    if change == "text":
        state.a1.result.source_fields.code_info.original_text = "altered"
    elif change == "literal":
        state.a1.result.facts.identifiers[0].value = "invented"
    elif change == "kind":
        state.a1.result.facts.identifiers[0].kind = "expiry_date"
    else:
        state.a1.result.facts.identifiers[0].evidence_ids = ["invented"]
    result = audit(upstream, a1_envelope=state.a1)
    assert any(f.target_agent == "a1" for f in result.findings)


@pytest.mark.parametrize("field,value", [("simulated_quantity", 999), ("lot_code", "invented"),
    ("upc", "0"), ("store_id", "other"), ("item_id", "missing")])
def test_inventory_drift_blocks(upstream, field, value):
    a2 = deepcopy(upstream[2].a2)
    setattr(a2.findings[0], field, value)
    assert any(f.code == "a2_sqlite_or_match_drift" for f in audit(upstream, a2_envelope=a2).findings)


def test_invented_no_match_detected_by_replay(upstream):
    a2 = upstream[2].a2.model_copy(update={"status": "no_match", "findings": []})
    assert any(f.target_agent == "a2" for f in audit(upstream, a2_envelope=a2).findings)


@pytest.mark.parametrize("field,value", [("reason", "safe to sell"), ("evidence_ids", ["invented"]),
    ("item_id", "missing"), ("action_code", "VERIFY_LOT")])
def test_a3_claim_or_provenance_drift_is_explicit(upstream, field, value):
    a3 = deepcopy(upstream[2].a3)
    setattr(a3.suggested_actions[0], field, value)
    result = audit(upstream, a3_envelope=a3)
    assert result.findings[-1].code == "a3_plan_policy_failed"
    assert result.findings[-1].fixable_by_revision


def test_closed_inventory_fails_without_zero_match_claim(upstream):
    upstream[1].close()
    assert audit(upstream).fatal_error.code == "inventory_store_unavailable"


def test_no_match_plan_cannot_become_clearance(upstream):
    a2 = upstream[2].a2.model_copy(update={"status": "no_match", "findings": []})
    a3 = plan_response(a2)
    a3.suggested_actions[0].reason = "The stock is safe."
    assert any(f.target_agent == "a3" for f in audit(upstream, a2_envelope=a2, a3_envelope=a3).findings)
