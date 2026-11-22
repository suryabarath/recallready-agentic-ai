"""Standalone A3 contract tests: no FDA fixture, inventory JSON, database, or LLM."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from a3_agent import A3RunEnvelope, SuggestedAction, plan_response, validate_plan_against_a2


CONTEXT = dict(
    case_id="case-1", run_id="run-1", recall_number="H-0011-2027",
    snapshot_id="snap-1", event_id="event-1",
)


def finding(*, item="INV-001", match="exact", lot="matched", evidence=None,
            inventory_set="SIM-SET-1", **overrides):
    base = dict(
        **CONTEXT, inventory_set_id=inventory_set, item_id=item,
        match_status=match, lot_match=lot, product_name_match="matched",
        a1_evidence_ids=list(evidence if evidence is not None else ["ev-product", "ev-lot"]),
        a1_uncertainties=[], requires_human_review=match == "partial",
    )
    base.update(overrides)
    return base


def envelope(status="matched", findings=None, *, error=None, review=False, **overrides):
    base = dict(
        **CONTEXT, status=status,
        findings=[finding()] if findings is None and status == "matched" else (findings or []),
        error=error, requires_human_review=review,
    )
    base.update(overrides)
    return base


def test_exact_retains_ids_and_requires_review():
    a2 = envelope()
    result = plan_response(a2)
    assert result.status == "planned"
    assert result.suggested_actions[0].action_code == "REVIEW_ITEM"
    assert result.suggested_actions[0].item_id == "INV-001"
    assert result.suggested_actions[0].evidence_ids == ["ev-product", "ev-lot"]
    assert result.requires_human_review is True
    assert result.suggested_actions[0].requires_human_review is True
    assert result.model_dump()["snapshot_id"] == "snap-1"


@pytest.mark.parametrize("lot,expected", [
    ("unknown", "VERIFY_LOT"),
    ("mismatched", "VERIFY_LOT"),
    ("matched", "REQUEST_MORE_INFORMATION"),
])
def test_partial_match_routes_conservatively(lot, expected):
    data = envelope(status="partial", findings=[finding(match="partial", lot=lot)], review=True)
    result = plan_response(data)
    action = result.suggested_actions[0]
    assert action.action_code == expected
    if lot == "mismatched":
        assert "do not regard" in action.reason
    assert action.evidence_ids == ["ev-product", "ev-lot"]


def test_a2_matched_can_contain_exact_and_partial_findings():
    data = envelope(findings=[finding(item="INV-001"),
                              finding(item="INV-002", match="partial", lot="unknown")])
    actions = plan_response(data).suggested_actions
    assert [(a.item_id, a.action_code) for a in actions] == [
        ("INV-001", "REVIEW_ITEM"), ("INV-002", "VERIFY_LOT")]


def test_no_match_is_case_level_without_safety_clearance():
    result = plan_response(envelope(status="no_match"))
    assert len(result.suggested_actions) == 1
    action = result.suggested_actions[0]
    assert action.action_code == "RECORD_NO_DEMONSTRATED_MATCH"
    assert action.item_id is None and action.evidence_ids == []
    assert "not a safety clearance" in action.reason.lower()


def test_upstream_unresolved_never_produces_no_match():
    data = envelope(status="unresolved", error={
        "code": "a1_unresolved", "message": "Missing evidence",
        "automatic_retry_allowed": False,
    }, event_id=None, review=True)
    result = plan_response(data)
    assert result.status == "unresolved"
    assert result.suggested_actions == []
    assert "a1_unresolved" in result.error


@pytest.mark.parametrize("update,match_text", [
    ({"case_id": "wrong-case"}, "context differs"),
    ({"snapshot_id": "wrong-snap"}, "context differs"),
    ({"event_id": "wrong-event"}, "context differs"),
    ({"run_id": "wrong-run"}, "context differs"),
    ({"recall_number": "wrong-recall"}, "context differs"),
])
def test_finding_context_mismatch_fails_closed(update, match_text):
    with pytest.raises(ValidationError, match=match_text):
        plan_response(envelope(findings=[finding(**update)]))


def test_duplicate_item_rejected():
    with pytest.raises(ValidationError, match="duplicate item_id"):
        plan_response(envelope(findings=[finding(), finding()]))


def test_mixed_inventory_sets_rejected():
    with pytest.raises(ValidationError, match="mix inventory_set_id"):
        plan_response(envelope(findings=[finding(), finding(item="INV-002", inventory_set="ANOTHER")]))


def test_duplicate_evidence_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate A1 evidence"):
        plan_response(envelope(findings=[finding(evidence=["ev-1", "ev-1"])]))


def test_missing_evidence_rejected():
    with pytest.raises(ValidationError, match="at least 1"):
        plan_response(envelope(findings=[finding(evidence=[])]))


def test_finding_no_match_rejected_even_with_matched_envelope():
    with pytest.raises(ValidationError, match="no_match entries"):
        plan_response(envelope(findings=[finding(match="no_match")]))


def test_exact_with_lot_mismatch_rejected():
    with pytest.raises(ValidationError, match="Exact A2 finding"):
        plan_response(envelope(findings=[finding(lot="mismatched")]))


def test_partial_without_review_rejected():
    with pytest.raises(ValidationError, match="must require human review"):
        plan_response(envelope(status="partial", findings=[finding(match="partial")], review=False))


def test_no_match_with_findings_rejected():
    with pytest.raises(ValidationError, match="zero findings"):
        plan_response(envelope(status="no_match", findings=[finding()]))


def test_planned_empty_actions_cannot_be_constructed():
    with pytest.raises(ValidationError, match="nonempty actions"):
        A3RunEnvelope(**CONTEXT, status="planned")


def test_human_review_cannot_be_disabled():
    with pytest.raises(ValidationError):
        SuggestedAction(item_id="INV-001", action_code="REVIEW_ITEM", reason="review",
                        evidence_ids=["ev-1"], requires_human_review=False)
    with pytest.raises(ValidationError):
        A3RunEnvelope(**CONTEXT, status="planned", requires_human_review=False,
                      suggested_actions=[SuggestedAction(item_id="INV-001", action_code="REVIEW_ITEM",
                                                      reason="review", evidence_ids=["ev-1"])])


def test_output_policy_rejects_fabricated_evidence_and_item_ids():
    input_a2 = envelope()
    plan = plan_response(input_a2)
    fake_evidence = plan.model_copy(update={"suggested_actions": [
        SuggestedAction(item_id="INV-001", action_code="REVIEW_ITEM", reason="review",
                        evidence_ids=["made-up-evidence"])]})
    with pytest.raises(ValueError, match="evidence IDs"):
        validate_plan_against_a2(fake_evidence, input_a2)

    fake_item = plan.model_copy(update={"suggested_actions": [
        SuggestedAction(item_id="OTHER", action_code="REVIEW_ITEM", reason="review",
                        evidence_ids=["ev-product"])]})
    with pytest.raises(ValueError, match="unknown A2 item_id"):
        validate_plan_against_a2(fake_item, input_a2)


def test_policy_rejects_wrong_action_and_duplicate_action():
    a2 = envelope()
    original = plan_response(a2)
    bad_action = original.model_copy(update={"suggested_actions": [
        SuggestedAction(item_id="INV-001", action_code="VERIFY_LOT", reason="review",
                        evidence_ids=["ev-product", "ev-lot"])]})
    with pytest.raises(ValueError, match="contradicts"):
        validate_plan_against_a2(bad_action, a2)

    repeated = original.model_copy(update={"suggested_actions": 2 * original.suggested_actions})
    with pytest.raises(ValueError, match="One A3 action"):
        validate_plan_against_a2(repeated, a2)


def test_source_payload_is_not_mutated():
    data = envelope()
    before = deepcopy(data)
    plan_response(data)
    assert data == before


def test_reject_wrong_input_type():
    with pytest.raises(TypeError, match="A2RunEnvelope"):
        plan_response("not an A2 envelope")


def test_extra_a2_fields_do_not_break_projection():
    a2 = envelope(findings=[finding(product_label="A2 keeps extra inventory fields")],
                  new_a2_metadata="future-compatible")
    assert plan_response(a2).status == "planned"


def test_unresolved_does_not_require_local_datasets():
    # Directly exercises the isolated boundary; no imports of A1/A2, SQLite or Qdrant.
    assert plan_response(envelope()).status == "planned"


def test_policy_rejects_clearance_claim_even_with_correct_evidence():
    a2 = envelope(status="no_match")
    plan = plan_response(a2)
    forged = plan.model_copy(update={"suggested_actions": [
        SuggestedAction(item_id=None, action_code="RECORD_NO_DEMONSTRATED_MATCH",
                        reason="This product is safe to sell.")
    ]})
    with pytest.raises(ValueError, match="non-clearance wording"):
        validate_plan_against_a2(forged, a2)


def test_policy_rejects_altered_item_reason():
    a2 = envelope()
    plan = plan_response(a2)
    altered = plan.model_copy(update={"suggested_actions": [
        SuggestedAction(item_id="INV-001", action_code="REVIEW_ITEM",
                        reason="Safe to sell, no review needed.",
                        evidence_ids=["ev-product", "ev-lot"])
    ]})
    with pytest.raises(ValueError, match="bounded deterministic rationale"):
        validate_plan_against_a2(altered, a2)
