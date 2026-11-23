"""Case state for A1, optional A2 and A3; A4 remains outside this slice."""

from typing import Literal, Self

from pydantic import Field, model_validator

from a1_run import A1RunEnvelope, RunError
from a2_agent import A2Error, A2RunEnvelope
from a3_agent import A3Error, A3RunEnvelope, validate_plan_against_a2
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
                   "a2_unexpected_failure", "a2_completed", "a3_planned", "a3_unexpected_failure", "human_review", "stopped"]
    timestamp_utc: Nonblank


class CaseState(CaseRequest):
    status: Literal["pending", "running", "a1_completed", "a2_completed", "human_review", "unresolved"] = "pending"
    a1: A1RunEnvelope | None = None
    a2: A2RunEnvelope | None = None
    a3: A3RunEnvelope | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError | A2Error | A3Error] = Field(default_factory=list)
    review_reason: Nonblank | None = None
    revision_count: Literal[0] = 0  # No critic/revision loop in this graph.

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.a3 is not None:
            if self.a2 is None or self.a2.status not in ("matched", "no_match") or self.a2.requires_human_review:
                raise ValueError("A3 requires resolved A2 without upstream review")
            validate_plan_against_a2(self.a3, self.a2)
            if self.status not in ("running", "human_review"):
                raise ValueError("A3 plan requires human review")
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
            if self.a1 is None or self.a1.status != "validated":
                raise ValueError("A2 requires validated A1")
            result = self.a1.result
            if isinstance(result, GroupCResult) or result.facts.uncertainties:
                raise ValueError("A2 must not bypass the A1 review requirement")
            if (self.a2.case_id, self.a2.run_id, self.a2.recall_number,
                self.a2.snapshot_id, self.a2.event_id) != (
                    self.case_id, self.run_id, self.recall_number, self.snapshot_id, result.event_id):
                raise ValueError("A2 differs from selected case/run context")
            evidence = set(result.facts.evidence_ids)
            identifiers = {item.value for item in result.facts.identifiers}
            for finding in self.a2.findings:
                if not set(finding.a1_evidence_ids) <= evidence:
                    raise ValueError("A2 finding cites evidence outside validated A1")
                if not set(finding.a1_identifier_values) <= identifiers:
                    raise ValueError("A2 finding cites identifier values outside validated A1")
                if finding.a1_uncertainties != tuple(result.facts.uncertainties):
                    raise ValueError("A2 finding changes A1 uncertainty")
        if self.status in ("a1_completed", "a2_completed", "human_review"):
            if self.a1 is None or self.a1.status != "validated" or self.errors:
                raise ValueError("Successful A1 route requires a validated envelope and no errors")
            result = self.a1.result
            base = result.base if isinstance(result, GroupCResult) else result
            needs_review = (isinstance(result, GroupCResult) or bool(base.facts.uncertainties)
                            or (self.a2 is not None and self.a2.requires_human_review)
                            or self.a3 is not None)
            if needs_review != (self.status == "human_review"):
                raise ValueError("Case route does not preserve the A1 review requirement")
            if self.status == "a1_completed" and self.a2 is not None:
                raise ValueError("A1 completion cannot contain downstream outcomes")
            if self.status == "a2_completed" or (self.status == "human_review" and self.a2 is not None):
                if self.a2 is None or self.a2.status == "unresolved":
                    raise ValueError("A2 completion/review requires a resolved A2 envelope")
        if self.status == "human_review" and self.review_reason is None:
            raise ValueError("Human review requires an explicit reason")
        if self.status != "human_review" and self.review_reason is not None:
            raise ValueError("Review reason is only valid on the review route")
        if self.status == "unresolved":
            if not self.errors or (self.a2 is not None and self.a2.status != "unresolved"
                                   and not any(isinstance(error, A3Error) for error in self.errors)):
                raise ValueError("Unresolved case requires an error and no resolved A2 result")
            if self.a1 is not None and self.a1.status == "validated" and not any(
                isinstance(error, (A2Error, A3Error)) for error in self.errors
            ):
                raise ValueError("Validated A1 requires an A2 error to stop unresolved")
        return self
