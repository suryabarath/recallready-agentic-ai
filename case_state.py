"""Typed case state for A1 -> A2 -> A3, pending A4 and human approval."""

from typing import Literal, Self

from pydantic import Field, model_validator

from a1_run import A1RunEnvelope, RunError
from a2_agent import A2RunEnvelope, A2Error
from a3_agent import A3RunEnvelope
from group_c_contract import GroupCResult
from models import Nonblank, StrictModel


class CaseRequest(StrictModel):
    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None = None


class CaseEvent(StrictModel):
    event: Literal["started", "a1_validated", "a1_unresolved", "a1_unexpected_failure",
                   "a1_completed", "a2_matched", "a2_partial", "a2_no_match", "a2_unresolved",
                   "a2_unexpected_failure", "a3_planned", "a3_unresolved", "a3_unexpected_failure",
                   "a3_completed", "human_review", "stopped"]
    timestamp_utc: Nonblank


class CaseState(CaseRequest):
    status: Literal["pending", "running", "a1_completed", "a3_completed", "human_review", "unresolved"] = "pending"
    a1: A1RunEnvelope | None = None
    a2: A2RunEnvelope | None = None
    a3: A3RunEnvelope | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError | A2Error] = Field(default_factory=list)
    review_reason: Nonblank | None = None
    revision_count: Literal[0] = 0  # No critic/revision loop in the A1-only graph.

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.a1 is not None:
            if (self.a1.run_id, self.a1.trace.recall_number, self.a1.trace.snapshot_id) != (
                    self.run_id, self.recall_number, self.snapshot_id):
                raise ValueError("A1 envelope differs from selected case/run context")
            if self.a1.status == "validated":
                result = self.a1.result
                base = result.base if isinstance(result, GroupCResult) else result
                if (base.facts.recall_number, base.snapshot_id) != (self.recall_number, self.snapshot_id):
                    raise ValueError("A1 facts differ from selected case context")
                if self.event_id is not None and base.event_id != self.event_id:
                    raise ValueError("A1 event differs from selected case event")
        if self.a2 is not None:
            if (self.a2.case_id, self.a2.run_id, self.a2.recall_number, self.a2.snapshot_id) != (
                    self.case_id, self.run_id, self.recall_number, self.snapshot_id):
                raise ValueError("A2 context mismatch")
            if self.a1 is None or self.a1.status != "validated":
                raise ValueError("A2 requires validated A1")
            base = self.a1.result.base if isinstance(self.a1.result, GroupCResult) else self.a1.result
            if self.a2.event_id != base.event_id:
                raise ValueError("A2 event mismatch")
        if self.a3 is not None:
            if self.a2 is None or (self.a3.case_id, self.a3.run_id, self.a3.recall_number,
                self.a3.snapshot_id, self.a3.event_id) != (self.a2.case_id, self.a2.run_id,
                self.a2.recall_number, self.a2.snapshot_id, self.a2.event_id):
                raise ValueError("A3 requires matching A2")
            if self.a3.status == "planned":
                available = {f.item_id: set(f.a1_evidence_ids) for f in self.a2.findings}
                for action in self.a3.suggested_actions:
                    if action.item_id is not None and (
                        action.item_id not in available or not set(action.evidence_ids) <= available[action.item_id]
                    ):
                        raise ValueError("A3 cites unsupported inventory finding or evidence")
        if self.status in ("a1_completed", "a3_completed", "human_review"):
            if self.a1 is None or self.a1.status != "validated" or self.errors:
                raise ValueError("Successful/review route requires validated A1 and no errors")
            result = self.a1.result
            base = result.base if isinstance(result, GroupCResult) else result
            a1_review = isinstance(result, GroupCResult) or bool(base.facts.uncertainties)
            if self.status == "a1_completed" and a1_review:
                raise ValueError("A1-only completion must not bypass review or downstream results")
            if self.status == "a3_completed" and (self.a3 is None or self.a3.status != "planned"
                                                   or self.a2 is None or self.a2.requires_human_review
                                                   or a1_review):
                raise ValueError("A3 completion requires an unambiguous plan")
            if self.status == "human_review" and not (
                a1_review or (self.a2 is not None and self.a2.requires_human_review)
                or (self.a3 is not None and self.a3.status == "planned")
            ):
                raise ValueError("Human review requires reviewable evidence")
        if self.status == "human_review" and self.review_reason is None:
            raise ValueError("Human review requires an explicit reason")
        if self.status != "human_review" and self.review_reason is not None:
            raise ValueError("Review reason only valid on review route")
        if self.status == "unresolved":
            if not self.errors or (self.a1 is not None and self.a1.status == "unresolved" and self.a2 is not None):
                raise ValueError("Unresolved requires errors and consistent upstream state")
        return self
