"""Agent 3: bounded, deterministic, evidence-preserving response recommendations.

This version intentionally does not ask an LLM to infer regulatory dispositions.
It produces review-only recommendations from the validated A2 envelope; A4 and
human approval are separate downstream responsibilities.
"""
from typing import Literal, Self
from pydantic import Field, model_validator
from models import Nonblank, StrictModel
from a2_agent import A2RunEnvelope

ActionCode = Literal[
    "REVIEW_ITEM", "VERIFY_LOT", "REQUEST_MORE_INFORMATION",
    "RECORD_NO_DEMONSTRATED_MATCH",
]

class SuggestedAction(StrictModel):
    item_id: Nonblank | None
    action_code: ActionCode
    reason: Nonblank
    evidence_ids: list[Nonblank] = Field(default_factory=list)
    requires_human_review: bool = True

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Duplicate evidence references")
        if self.action_code == "RECORD_NO_DEMONSTRATED_MATCH":
            if self.item_id is not None or self.evidence_ids:
                raise ValueError("No-match case-level action cannot cite a nonexistent inventory finding")
        elif self.item_id is None or not self.evidence_ids:
            raise ValueError("Item action requires an item_id and A1 evidence")
        return self

class A3RunEnvelope(StrictModel):
    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None
    status: Literal["planned", "unresolved"]
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    requires_human_review: bool = True
    error: Nonblank | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "planned" and (not self.suggested_actions or self.error is not None):
            raise ValueError("Planned result requires actions and no error")
        if self.status == "unresolved" and (self.suggested_actions or self.error is None):
            raise ValueError("Unresolved result requires error and no actions")
        return self


def plan_response(a2: A2RunEnvelope) -> A3RunEnvelope:
    """Map authoritative A2 findings to non-executing, human-review actions.

    No SQLite mutations, stock disposition, public notification, or clearance.
    A2 unresolved is not silently converted into a no-match decision.
    """
    if not isinstance(a2, A2RunEnvelope):
        raise TypeError("A3 requires a validated A2RunEnvelope")
    identity = dict(case_id=a2.case_id, run_id=a2.run_id,
                    recall_number=a2.recall_number, snapshot_id=a2.snapshot_id,
                    event_id=a2.event_id)
    if a2.status == "unresolved":
        return A3RunEnvelope(**identity, status="unresolved",
                             error="A2 unresolved; no response recommendation can be established.")
    actions = []
    seen = set()
    for finding in a2.findings:
        if (finding.case_id, finding.run_id, finding.recall_number,
            finding.snapshot_id, finding.event_id) != (
                a2.case_id, a2.run_id, a2.recall_number,
                a2.snapshot_id, a2.event_id):
            raise ValueError("A2 finding context differs from its envelope")
        if finding.item_id in seen:
            raise ValueError("A2 supplied duplicate item_id")
        seen.add(finding.item_id)
        if finding.match_status == "exact":
            action = "REVIEW_ITEM"
            reason = "Deterministic A2 match; reviewer must confirm any operational response."
        elif finding.match_status == "partial":
            action = "VERIFY_LOT" if finding.lot_match != "matched" else "REQUEST_MORE_INFORMATION"
            reason = "Partial A2 match; verify unresolved attributes and recall scope before any decision."
        else:
            raise ValueError("A2 findings must not include no_match entries")
        actions.append(SuggestedAction(item_id=finding.item_id, action_code=action,
                                       reason=reason, evidence_ids=list(finding.a1_evidence_ids)))
    if a2.status == "no_match":
        if actions:
            raise ValueError("A2 no_match cannot include findings")
        actions = [SuggestedAction(item_id=None, action_code="RECORD_NO_DEMONSTRATED_MATCH",
                                   reason="No demonstrated inventory match in the selected snapshot; this is not a safety clearance.")]
    elif not actions:
        raise ValueError("Resolved A2 match status requires findings")
    return A3RunEnvelope(**identity, status="planned", suggested_actions=actions)
