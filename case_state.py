"""A1-only case state; downstream agent contracts remain outside this slice."""

from typing import Literal, Self

from pydantic import Field, model_validator

from a1_run import A1RunEnvelope, RunError
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
                   "a1_completed", "human_review", "stopped"]
    timestamp_utc: Nonblank


class CaseState(CaseRequest):
    status: Literal["pending", "running", "a1_completed", "human_review", "unresolved"] = "pending"
    a1: A1RunEnvelope | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError] = Field(default_factory=list)
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
        if self.status in ("a1_completed", "human_review"):
            if self.a1 is None or self.a1.status != "validated" or self.errors:
                raise ValueError("Successful A1 route requires a validated envelope and no errors")
            result = self.a1.result
            base = result.base if isinstance(result, GroupCResult) else result
            needs_review = isinstance(result, GroupCResult) or bool(base.facts.uncertainties)
            if needs_review != (self.status == "human_review"):
                raise ValueError("Case route does not preserve the A1 review requirement")
        if self.status == "human_review" and self.review_reason is None:
            raise ValueError("Human review requires an explicit reason")
        if self.status != "human_review" and self.review_reason is not None:
            raise ValueError("Review reason is only valid on the review route")
        if self.status == "unresolved":
            if not self.errors or (self.a1 is not None and self.a1.status != "unresolved"):
                raise ValueError("Unresolved case requires an error and no validated A1 result")
        return self
