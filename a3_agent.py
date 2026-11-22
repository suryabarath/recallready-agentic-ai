"""Standalone RecallReady Agent 3 response planner.

This module deliberately DOES NOT import Agent 1, Agent 2, LangGraph, SQLite,
Qdrant, or any project data loader. It accepts the validated Agent 2 envelope
(or its JSON-like model_dump) and revalidates the fields A3 needs.

All recommendations are proposals requiring human review; no side effects.
The deterministic baseline is intentionally distinct from a future optional
LLM reasoning adapter. Do not present it as an LLM-powered agent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Expected a nonblank string")
    # Preserve all source identifiers literally; do not trim or normalize.
    return value


Nonblank = Annotated[str, Field(min_length=1), AfterValidator(_nonblank)]
A2Status = Literal["matched", "partial", "no_match", "unresolved"]
MatchStatus = Literal["exact", "partial", "no_match"]
AttributeStatus = Literal["matched", "mismatched", "unknown"]
ActionCode = Literal[
    "REVIEW_ITEM",
    "VERIFY_LOT",
    "REQUEST_MORE_INFORMATION",
    "RECORD_NO_DEMONSTRATED_MATCH",
]


class _ExternalInputModel(BaseModel):
    # A2 owns its schema. Ignore fields A3 does not consume rather than
    # pretending A3 has authority to freeze the entire A2 data contract.
    model_config = ConfigDict(extra="ignore", strict=True, revalidate_instances="always")


class A2ErrorInput(_ExternalInputModel):
    code: Nonblank
    message: Nonblank
    automatic_retry_allowed: Literal[False] = False


class A2FindingInput(_ExternalInputModel):
    """Subset of the actual baseline/agent2 InventoryFinding contract."""

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank
    inventory_set_id: Nonblank
    item_id: Nonblank
    match_status: MatchStatus
    lot_match: AttributeStatus
    product_name_match: AttributeStatus
    a1_evidence_ids: list[Nonblank] = Field(min_length=1)
    a1_uncertainties: list[Nonblank] | tuple[Nonblank, ...] = ()
    requires_human_review: bool

    @model_validator(mode="after")
    def check_finding(self) -> Self:
        if len(self.a1_evidence_ids) != len(set(self.a1_evidence_ids)):
            raise ValueError("A2 finding contains duplicate A1 evidence IDs")
        if self.match_status == "exact":
            if self.lot_match != "matched" or self.product_name_match != "matched":
                raise ValueError("Exact A2 finding must have matched lot and product name")
            if self.requires_human_review or self.a1_uncertainties:
                raise ValueError("Exact A2 finding conflicts with A2 uncertainty/review flags")
        if self.match_status == "partial" and not self.requires_human_review:
            raise ValueError("Partial A2 finding must require human review")
        if self.match_status == "no_match":
            raise ValueError("A2 must not place no_match entries in findings")
        return self


class A2InputEnvelope(_ExternalInputModel):
    """A3-owned read-only projection of the actual A2RunEnvelope contract.

    This is a validation boundary, NOT a replacement for Agent 2's schema.
    It permits fully isolated A3 tests while remaining compatible with the
    real `a2_agent.A2RunEnvelope.model_dump(mode='python')`.
    """

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None
    status: A2Status
    findings: list[A2FindingInput] = Field(default_factory=list)
    error: A2ErrorInput | None = None
    requires_human_review: bool = False

    @model_validator(mode="after")
    def check_a2_invariants(self) -> Self:
        if self.status == "unresolved":
            if self.error is None or self.findings:
                raise ValueError("Unresolved A2 must have an error and no findings")
            return self

        if self.event_id is None:
            raise ValueError("Resolved A2 must identify an event_id")
        if self.error is not None:
            raise ValueError("Resolved A2 must not have an error")
        if self.status == "no_match":
            if self.findings:
                raise ValueError("A2 no_match must have zero findings")
        elif self.status == "partial":
            if not self.findings or any(f.match_status != "partial" for f in self.findings):
                raise ValueError("A2 partial must contain only partial findings")
            if not self.requires_human_review:
                raise ValueError("A2 partial must require human review")
        elif self.status == "matched":
            if not any(f.match_status == "exact" for f in self.findings):
                raise ValueError("A2 matched requires at least one exact finding")

        context = (
            self.case_id, self.run_id, self.recall_number,
            self.snapshot_id, self.event_id,
        )
        item_ids: set[str] = set()
        inventory_sets: set[str] = set()
        for finding in self.findings:
            finding_context = (
                finding.case_id, finding.run_id, finding.recall_number,
                finding.snapshot_id, finding.event_id,
            )
            if finding_context != context:
                raise ValueError("A2 finding context differs from its envelope")
            if finding.item_id in item_ids:
                raise ValueError("A2 supplied duplicate item_id")
            item_ids.add(finding.item_id)
            inventory_sets.add(finding.inventory_set_id)
        if len(inventory_sets) > 1:
            raise ValueError("A2 findings mix inventory_set_id values")
        return self


class _StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class SuggestedAction(_StrictOutputModel):
    """Non-executing simulated recommendation grounded in an A2 finding."""

    item_id: Nonblank | None
    action_code: ActionCode
    reason: Nonblank
    evidence_ids: list[Nonblank] = Field(default_factory=list)
    requires_human_review: Literal[True] = True

    @model_validator(mode="after")
    def check_action(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Duplicate action evidence IDs")
        if self.action_code == "RECORD_NO_DEMONSTRATED_MATCH":
            if self.item_id is not None or self.evidence_ids:
                raise ValueError("Case-level no-match action cannot cite a nonexistent finding")
        elif self.item_id is None or not self.evidence_ids:
            raise ValueError("Item action must cite an item_id and A1 evidence IDs")
        return self


class A3RunEnvelope(_StrictOutputModel):
    """Typed response-planning handoff for future A4/human review."""

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None
    status: Literal["planned", "unresolved"]
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    requires_human_review: Literal[True] = True
    error: Nonblank | None = None

    @model_validator(mode="after")
    def check_result(self) -> Self:
        if self.status == "planned":
            if not self.suggested_actions or self.error is not None:
                raise ValueError("Planned A3 requires nonempty actions and no error")
        elif self.suggested_actions or self.error is None:
            raise ValueError("Unresolved A3 requires error and zero actions")
        return self


def _coerce_a2(a2: Any) -> A2InputEnvelope:
    """Accept a real A2 Pydantic envelope or a serialized mapping."""
    if isinstance(a2, A2InputEnvelope):
        # Revalidate a fresh snapshot; never trust an object mutated afterward.
        a2 = a2.model_dump(mode="python")
    elif isinstance(a2, BaseModel):
        a2 = a2.model_dump(mode="python")
    elif isinstance(a2, Mapping):
        a2 = dict(a2)
    else:
        raise TypeError("A3 expects an A2RunEnvelope or its serialized mapping")
    return A2InputEnvelope.model_validate(a2)


def _identity(a2: A2InputEnvelope) -> dict[str, Any]:
    return {
        "case_id": a2.case_id,
        "run_id": a2.run_id,
        "recall_number": a2.recall_number,
        "snapshot_id": a2.snapshot_id,
        "event_id": a2.event_id,
    }


def _recommendation(finding: A2FindingInput) -> tuple[ActionCode, str]:
    if finding.match_status == "exact":
        return (
            "REVIEW_ITEM",
            "A2 established an exact deterministic inventory match. "
            "Queue this simulated item for human review; no stock action is authorized.",
        )
    if finding.lot_match == "unknown":
        return (
            "VERIFY_LOT",
            "A2 reported a partial match with an unknown lot comparison. "
            "Verify the source lot and inventory label before any disposition.",
        )
    if finding.lot_match == "mismatched":
        return (
            "VERIFY_LOT",
            "A2 reported a partial finding with a deterministic lot mismatch. "
            "Recheck identifiers; do not regard this item as an affected-lot match.",
        )
    return (
        "REQUEST_MORE_INFORMATION",
        "A2 reported a partial finding with a matched lot, but other identity "
        "or scope attributes remain unresolved. Request supporting information.",
    )


NO_MATCH_REASON = (
    "A2 found no demonstrated inventory match in the selected simulated "
    "snapshot. This is not a safety clearance. Human review is required."
)


def plan_response(a2: Any) -> A3RunEnvelope:
    """Produce review-only recommendations from Agent 2. Pure and offline.

    Invalid input raises TypeError or Pydantic ValidationError, rather than
    hiding a contract violation behind a fabricated no-match result.
    An explicitly unresolved A2 envelope yields an unresolved A3 envelope.
    """
    source = _coerce_a2(a2)
    identity = _identity(source)

    if source.status == "unresolved":
        assert source.error is not None  # guaranteed by the input validator
        return A3RunEnvelope(
            **identity,
            status="unresolved",
            error=f"A2 unresolved ({source.error.code}); no response recommendation produced.",
        )

    if source.status == "no_match":
        actions = [
            SuggestedAction(
                item_id=None,
                action_code="RECORD_NO_DEMONSTRATED_MATCH",
                reason=NO_MATCH_REASON,
            )
        ]
    else:
        actions = []
        for finding in source.findings:
            action, reason = _recommendation(finding)
            actions.append(
                SuggestedAction(
                    item_id=finding.item_id,
                    action_code=action,
                    reason=reason,
                    evidence_ids=list(finding.a1_evidence_ids),
                )
            )

    result = A3RunEnvelope(
        **identity, status="planned", suggested_actions=actions,
    )
    validate_plan_against_a2(result, source)
    return result


def validate_plan_against_a2(plan: A3RunEnvelope, a2: Any) -> None:
    """Validate an A3 plan against A2 provenance and deterministic policy.

    Also suitable as a guardrail for *future* LLM-produced candidate plans:
    callers must validate a candidate before exposing it downstream.
    It does not independently resolve evidence in SQLite.
    """
    if not isinstance(plan, A3RunEnvelope):
        raise TypeError("Expected a validated A3RunEnvelope")
    # model_copy(update=...) does not validate in Pydantic; check all current
    # output invariants again before any plan crosses the A3 boundary.
    A3RunEnvelope.model_validate(plan.model_dump(mode="python"))
    source = _coerce_a2(a2)
    if _identity(source) != {key: getattr(plan, key) for key in _identity(source)}:
        raise ValueError("A3 context differs from its A2 input")

    if source.status == "unresolved":
        if plan.status != "unresolved" or plan.suggested_actions:
            raise ValueError("Unresolved A2 cannot produce planned actions")
        return
    if plan.status != "planned":
        raise ValueError("Resolved A2 requires a planned A3 envelope")

    if source.status == "no_match":
        if len(plan.suggested_actions) != 1 or (
            plan.suggested_actions[0].action_code != "RECORD_NO_DEMONSTRATED_MATCH"
        ):
            raise ValueError("A2 no_match must yield exactly one case-level no-match action")
        if plan.suggested_actions[0].reason != NO_MATCH_REASON:
            raise ValueError("A3 no-match reason must preserve its non-clearance wording")
        return

    if len(plan.suggested_actions) != len(source.findings):
        raise ValueError("One A3 action is required for each A2 finding")
    findings_by_id = {finding.item_id: finding for finding in source.findings}
    seen: set[str] = set()
    for action in plan.suggested_actions:
        if action.item_id is None or action.item_id not in findings_by_id:
            raise ValueError("A3 contains an unknown A2 item_id")
        if action.item_id in seen:
            raise ValueError("A3 contains duplicate actions for one item_id")
        seen.add(action.item_id)
        finding = findings_by_id[action.item_id]
        permitted_code, permitted_reason = _recommendation(finding)
        if action.action_code != permitted_code:
            raise ValueError("A3 action_code contradicts A2 deterministic findings")
        if action.evidence_ids != finding.a1_evidence_ids:
            raise ValueError("A3 evidence IDs do not match the A2 finding citations")
        if action.reason != permitted_reason:
            raise ValueError("A3 reason differs from the bounded deterministic rationale")


__all__ = [
    "A2InputEnvelope", "A3RunEnvelope", "SuggestedAction", "ActionCode",
    "plan_response", "validate_plan_against_a2",
]
