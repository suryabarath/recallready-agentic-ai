"""Source-limited correction requests; critic prose is never executable guidance."""

from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from models import A1Result, EvidenceIDs, Nonblank, StrictModel


class CorrectionRequest(StrictModel):
    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank
    target_agent: Literal["a1", "a2", "a3"]
    reason_codes: EvidenceIDs = Field(min_length=1)
    blocking_finding_ids: EvidenceIDs = Field(min_length=1)
    evidence_ids: EvidenceIDs = Field(default_factory=list)

    @model_validator(mode="after")
    def check_scope(self) -> Self:
        if self.target_agent == "a1":
            if self.reason_codes != ["a1_identifier_interpretation"]:
                raise ValueError("Unsupported A1 correction reason")
            allowed = {f"EV-{self.recall_number}-{field}" for field in
                       ("PRODUCT_DESCRIPTION", "CODE_INFO")}
            if not self.evidence_ids or not set(self.evidence_ids) <= allowed:
                raise ValueError("A1 correction requires selected product/code evidence")
        if self.target_agent == "a2" and self.reason_codes != ["a2_sqlite_or_match_drift"]:
            raise ValueError("Unsupported A2 correction reason")
        return self


def build_correction(critic, a1, *, case_id, run_id, recall_number, snapshot_id,
                     enable_upstream=False) -> CorrectionRequest | None:
    """Select only a complete, single-target, supported round-zero request."""
    if critic.verdict != "revise" or critic.revision_round != 0:
        return None
    revision = critic.revision_request
    blocking = [finding for finding in critic.findings if finding.severity == "blocking"]
    if (not blocking or revision is None or a1 is None or a1.status != "validated"
            or not isinstance(a1.result, A1Result)):
        return None
    context = (case_id, run_id, recall_number, snapshot_id, a1.result.event_id)
    if (critic.case_id, critic.run_id, critic.recall_number, critic.snapshot_id, critic.event_id) != context:
        return None
    if (any(not f.fixable_by_revision or f.target_agent != revision.target_agent for f in blocking)
            or set(revision.blocking_finding_ids) != {f.finding_id for f in blocking}
            or len(revision.blocking_finding_ids) != len(blocking)
            or set(revision.reason_codes) != {f.code for f in blocking}
            or len(revision.reason_codes) != len(set(revision.reason_codes))):
        return None
    target = revision.target_agent
    if target != "a3" and not enable_upstream:
        return None
    if target == "a1" and any(f.source != "llm_critic" or not f.evidence_ids for f in blocking):
        return None
    if target == "a2" and any(f.source != "deterministic" for f in blocking):
        return None
    evidence = list(dict.fromkeys(eid for f in blocking for eid in f.evidence_ids))
    if not set(evidence) <= set(a1.result.facts.evidence_ids):
        return None
    try:
        return CorrectionRequest(case_id=case_id, run_id=run_id, recall_number=recall_number,
            snapshot_id=snapshot_id, event_id=a1.result.event_id, target_agent=target,
            reason_codes=list(revision.reason_codes),
            blocking_finding_ids=list(revision.blocking_finding_ids), evidence_ids=evidence)
    except ValueError:
        return None


def a1_focus_fields(original: A1Result, evidence_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(original, A1Result) or type(evidence_ids) is not tuple:
        raise ValueError("A1 correction requires an original A/B result and evidence tuple")
    fields = ("product_description", "code_info")
    allowed = {f"EV-{original.facts.recall_number}-{field.upper()}": field for field in fields}
    if (not evidence_ids or len(set(evidence_ids)) != len(evidence_ids)
            or not set(evidence_ids) <= allowed.keys()
            or not set(evidence_ids) <= set(original.facts.evidence_ids)):
        raise ValueError("Invalid A1 correction evidence")
    return tuple(field for field in fields if field in {allowed[eid] for eid in evidence_ids})


def validate_a1_correction(original: A1Result, corrected: A1Result,
                           evidence_ids: tuple[str, ...]) -> None:
    """Protect all metadata/source text, unrelated identifiers and uncertainty."""
    a1_focus_fields(original, evidence_ids)
    before, after = original.model_dump(), corrected.model_dump()
    for payload in (before, after):
        payload["facts"].pop("identifiers")
        payload["facts"].pop("uncertainties")
    if before != after:
        raise ValueError("Correction changes protected A1 source or metadata")
    focus = set(evidence_ids)
    def protected(result):
        return Counter(item.model_dump_json() for item in result.facts.identifiers
                       if not set(item.evidence_ids) <= focus)
    if protected(original) != protected(corrected):
        raise ValueError("Correction changes identifiers outside the focused fields")
    if Counter(original.facts.uncertainties) - Counter(corrected.facts.uncertainties):
        raise ValueError("Correction removes existing uncertainty")
