"""Case state for the bounded A1-A4 workflow and one recorded correction."""

from typing import Literal, Self

from pydantic import Field, model_validator

from a1_run import A1RunEnvelope, RunError
from a2_agent import A2Error, A2RunEnvelope
from a3_agent import A3Error, A3RunEnvelope, validate_plan_against_a2
from a4_agent import A4RunEnvelope
from a4_checks import A4Error
from corrections import CorrectionRequest, build_correction, validate_a1_correction
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
                   "a2_unexpected_failure", "a2_completed", "a3_planned", "a3_unexpected_failure",
                   "a4_human_review", "a4_revise", "a4_unresolved", "a4_approved", "a4_unexpected_failure",
                   "revision_replay_started", "a3_replanned", "human_review", "stopped"]
    timestamp_utc: Nonblank


class CaseState(CaseRequest):
    status: Literal["pending", "running", "a1_completed", "a2_completed", "human_review", "unresolved"] = "pending"
    a1: A1RunEnvelope | None = None
    a2: A2RunEnvelope | None = None
    a3: A3RunEnvelope | None = None
    a4: A4RunEnvelope | None = None
    prior_a4: A4RunEnvelope | None = None
    prior_a3: A3RunEnvelope | None = None
    prior_a1: A1RunEnvelope | None = None
    prior_a2: A2RunEnvelope | None = None
    correction: CorrectionRequest | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError | A2Error | A3Error | A4Error] = Field(default_factory=list)
    review_reason: Nonblank | None = None
    revision_count: Literal[0, 1] = 0

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.a4 is not None:
            if self.a3 is None or self.a2 is None:
                raise ValueError("A4 requires A2 and A3 outcomes")
            critic = A4RunEnvelope.model_validate(self.a4.model_dump())
            if (critic.case_id, critic.run_id, critic.recall_number, critic.snapshot_id,
                critic.event_id, critic.revision_round) != (
                    self.case_id, self.run_id, self.recall_number, self.snapshot_id,
                    self.a2.event_id, self.revision_count):
                raise ValueError("A4 differs from case context or revision count")
            if critic.verdict == "approved" and self.a3.requires_human_review:
                raise ValueError("A4 cannot remove A3 human review")
            if critic.verdict == "unresolved" and self.status == "human_review":
                raise ValueError("Unresolved A4 must use unresolved case status")
            if self.status == "unresolved" and critic.verdict == "unresolved" and critic.error not in self.errors:
                raise ValueError("Case must preserve the A4 error")
        if self.revision_count == 1:
            if self.prior_a4 is None or self.prior_a3 is None or self.prior_a4.verdict != "revise":
                raise ValueError("Revision requires original A3 and A4 artifacts")
            if self.prior_a4.revision_round != 0:
                raise ValueError("Correction requires the original round-zero audit")
            target = self.prior_a4.revision_request.target_agent
            if target in ("a1", "a2"):
                if self.prior_a1 is None or self.prior_a2 is None or self.correction is None:
                    raise ValueError("Upstream correction requires original A1/A2 and its request")
                # Validate the entire original chain against its own findings,
                # not the potentially different corrected inventory result.
                CaseState.model_validate({
                    **{field: getattr(self, field) for field in CaseRequest.model_fields},
                    "status": "running", "a1": self.prior_a1, "a2": self.prior_a2,
                    "a3": self.prior_a3, "a4": self.prior_a4})
                if target == "a2" and self.a1 != self.prior_a1:
                    raise ValueError("A2 correction must preserve A1 exactly")
                if target == "a1" and self.a1 is not None:
                    if self.a1.trace.correction_evidence_ids != self.correction.evidence_ids:
                        raise ValueError("A1 trace differs from correction focus")
                    if self.a1.status == "validated":
                        validate_a1_correction(self.prior_a1.result, self.a1.result,
                                               tuple(self.correction.evidence_ids))
                        for field in ("archive_sha256", "collection", "embedding_model",
                                      "interpretation_model", "sdk_retries", "max_output_tokens"):
                            if getattr(self.a1.trace, field) != getattr(self.prior_a1.trace, field):
                                raise ValueError("A1 correction changes source/model configuration")
            else:
                if self.a2 is None or self.prior_a1 is not None or self.prior_a2 is not None:
                    raise ValueError("A3 replay requires unchanged upstream outcomes")
                validate_plan_against_a2(self.prior_a3, self.a2)
            original_a1 = self.prior_a1 if self.prior_a1 is not None else self.a1
            expected = build_correction(self.prior_a4, original_a1,
                case_id=self.case_id, run_id=self.run_id, recall_number=self.recall_number,
                snapshot_id=self.snapshot_id, enable_upstream=True)
            if expected is None or (self.correction is not None and self.correction != expected):
                raise ValueError("Correction request differs from the original audit")
            traces = [original_a1.trace, self.prior_a4.trace]
            if target == "a1" and self.a1 is not None:
                traces.append(self.a1.trace)
            if self.a4 is not None:
                traces.append(self.a4.trace)
            call_ids = [call.ledger_call_id for trace in traces for call in trace.calls]
            if len(set(call_ids)) != len(call_ids):
                raise ValueError("Correction attempts must retain distinct ledger calls")
            original_event = self.prior_a3.event_id
            for prior in (self.prior_a4, self.prior_a3):
                if (prior.case_id, prior.run_id, prior.recall_number, prior.snapshot_id, prior.event_id) != (
                        self.case_id, self.run_id, self.recall_number, self.snapshot_id, original_event):
                    raise ValueError("Prior revision artifact differs from selected case")
        elif any(value is not None for value in
                 (self.prior_a4, self.prior_a3, self.prior_a1, self.prior_a2, self.correction)):
            raise ValueError("Prior artifacts require a recorded revision")
        if self.a3 is not None:
            if self.a2 is None or self.a2.status not in ("matched", "no_match") or self.a2.requires_human_review:
                raise ValueError("A3 requires resolved A2 without upstream review")
            validate_plan_against_a2(self.a3, self.a2)
            if self.status not in ("running", "human_review") and not (
                    self.status == "unresolved" and any(isinstance(e, A4Error) for e in self.errors)):
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
            items = {finding.item_id for finding in self.a2.findings}
            critics = (self.a4,) if self.prior_a2 is not None else (self.a4, self.prior_a4)
            for critic in critics:
                if critic is not None and (
                        not set(critic.trace.verified_evidence_ids) <= evidence
                        or not set(critic.trace.verified_item_ids) <= items):
                    raise ValueError("A4 provenance differs from upstream case references")
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
                                   and not any(isinstance(error, (A3Error, A4Error)) for error in self.errors)):
                raise ValueError("Unresolved case requires an error and no resolved A2 result")
            if self.a1 is not None and self.a1.status == "validated" and not any(
                isinstance(error, (A2Error, A3Error, A4Error)) for error in self.errors
            ):
                raise ValueError("Validated A1 requires an A2 error to stop unresolved")
        return self
