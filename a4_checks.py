"""Deterministic A4 checks against exact FDA and case-scoped inventory stores.

Shared validation/matching tools are reused; passing is not an independent
accuracy evaluation of those tools or approval of the pending A2 policies.
"""

import sqlite3
from typing import Literal

from pydantic import Field

from a1_trace import RequestState
from a2_agent import run_a2
from a3_agent import validate_plan_against_a2
from fda_store import StoreError
from group_c_contract import GroupCResult, validate_group_c_result
from inventory_store import InventoryStoreError
from models import EvidenceIDs, Nonblank, StrictModel
from source import FIELDS
from validation import validate_result


A4Verdict = Literal["approved", "revise", "human_review", "unresolved"]
RevisionTarget = Literal["a1", "a2", "a3"]
CheckSeverity = Literal["blocking", "warning"]
CheckSource = Literal["deterministic", "llm_critic"]
FindingCategory = Literal["evidence_integrity", "sqlite_mismatch", "unsupported_claim",
                          "uncertainty_dropped", "action_inappropriate", "prototype_boundary", "coverage_gap"]
A4ErrorStage = Literal["preflight", "deterministic_checks", "llm_critic", "accounting", "coordinator"]
A4ErrorCode = Literal["context_mismatch", "upstream_unresolved", "fda_store_unavailable",
    "inventory_store_unavailable", "budget_exhausted", "provider_failure", "incomplete_response",
    "model_refusal", "invalid_output", "usage_missing", "usage_ledger_unavailable",
    "usage_reservation_failed", "usage_settlement_failed", "critic_internal_failure"]


class CriticFinding(StrictModel):
    finding_id: Nonblank
    source: CheckSource
    severity: CheckSeverity
    category: FindingCategory
    target_agent: RevisionTarget
    code: Nonblank
    message: Nonblank
    evidence_ids: EvidenceIDs = Field(default_factory=list)
    item_ids: list[Nonblank] = Field(default_factory=list)
    fixable_by_revision: bool = True


class RevisionRequest(StrictModel):
    target_agent: RevisionTarget
    reason_codes: list[Nonblank] = Field(min_length=1)
    instructions: Nonblank
    blocking_finding_ids: list[Nonblank] = Field(min_length=1)


class A4Error(StrictModel):
    stage: A4ErrorStage
    code: A4ErrorCode
    message: Nonblank
    request_state: RequestState = "not_sent"
    automatic_retry_allowed: Literal[False] = False


class DeterministicAuditOutcome(StrictModel):
    fatal_error: A4Error | None = None
    findings: list[CriticFinding] = Field(default_factory=list)
    checks_run: list[Nonblank] = Field(default_factory=list)
    verified_evidence_ids: EvidenceIDs = Field(default_factory=list)
    verified_item_ids: list[Nonblank] = Field(default_factory=list)
    verified_passages: dict[str, dict[str, str]] = Field(default_factory=dict)
    canonical_event_id: Nonblank | None = None
    upstream_needs_review: bool = False
    review_boundary_verified: bool = False


def run_deterministic_checks(fda_store, inventory_store, a1_envelope, a2_envelope,
                             a3_envelope, *, case_id, run_id, recall_number,
                             snapshot_id, event_id=None, approved_lots=()):
    """Re-resolve evidence, replay exact matching and verify the actual A3 plan.

    Invalid claims become explicit blocking findings; storage/context failures
    stop the audit. No network, model, inventory write or source correction.
    """
    audit = DeterministicAuditOutcome()

    def fatal(code, message):
        audit.fatal_error = A4Error(stage="deterministic_checks", code=code, message=message)
        return audit

    def block(target, code, message, category):
        audit.findings.append(CriticFinding(
            finding_id=f"DET-{len(audit.findings) + 1:03d}", source="deterministic",
            severity="blocking", category=category, target_agent=target,
            code=code, message=message,
            fixable_by_revision=target == "a3",
        ))

    audit.checks_run.append("context_identity")
    if fda_store is None:
        return fatal("fda_store_unavailable", "Exact FDA store is unavailable.")
    if inventory_store is None:
        return fatal("inventory_store_unavailable", "Case-scoped inventory store is unavailable.")
    if (fda_store.snapshot_id != snapshot_id or inventory_store.snapshot_id != snapshot_id
            or (a1_envelope.run_id, a1_envelope.trace.recall_number, a1_envelope.trace.snapshot_id)
            != (run_id, recall_number, snapshot_id)):
        return fatal("context_mismatch", "Store or A1 identity differs from selected context.")
    context = (case_id, run_id, recall_number, snapshot_id)
    for envelope in (a2_envelope, a3_envelope):
        if tuple(getattr(envelope, name) for name in
                 ("case_id", "run_id", "recall_number", "snapshot_id")) != context:
            return fatal("context_mismatch", "A2/A3 identity differs from selected context.")
    if (a1_envelope.status != "validated" or a1_envelope.result is None
            or a2_envelope.status == "unresolved" or a3_envelope.status == "unresolved"):
        return fatal("upstream_unresolved", "Unresolved upstream results cannot pass A4.")
    result = a1_envelope.result
    base = result.base if isinstance(result, GroupCResult) else result
    canonical = base.event_id
    audit.canonical_event_id = canonical
    if ((event_id is not None and event_id != canonical)
            or a1_envelope.trace.event_id != canonical
            or a2_envelope.event_id != canonical or a3_envelope.event_id != canonical
            or base.facts.recall_number != recall_number or base.snapshot_id != snapshot_id):
        return fatal("context_mismatch", "Canonical recall/event/snapshot differs from selected context.")
    ctx = dict(recall_number=recall_number, event_id=canonical, snapshot_id=snapshot_id)
    audit.checks_run.append("exact_fda_source_and_identifiers")
    try:
        for field in FIELDS:
            evidence = fda_store.resolve(f"EV-{recall_number}-{field.upper()}", **ctx)
            audit.verified_evidence_ids.append(evidence.evidence_id)
            audit.verified_passages[evidence.evidence_id] = {
                "evidence_id": evidence.evidence_id, "field_name": field,
                "original_text": evidence.original_text,
            }
        if isinstance(result, GroupCResult):
            validate_group_c_result(result.model_dump(), fda_store, **ctx)
        else:
            validate_result(result.model_dump(), fda_store, approved_lots=approved_lots, **ctx)
    except (sqlite3.Error, OSError, StoreError):
        return fatal("fda_store_unavailable", "Exact FDA source could not be resolved.")
    except ValueError:
        block("a1", "a1_source_validation_failed", "A1 differs from exact FDA evidence or identifier policy.",
              "evidence_integrity")

    audit.checks_run.append("inventory_sqlite_and_match_replay")
    try:
        # Replay also catches omitted findings and invented no-match claims.
        replay = run_a2(inventory_store, a1_envelope, case_id=case_id,
                        run_id=run_id, **ctx)
        if replay.status == "unresolved":
            if replay.error.code in ("inventory_store_unavailable", "inventory_schema_invalid"):
                return fatal("inventory_store_unavailable", "Inventory replay could not read the exact store.")
            block("a2", "a2_replay_unresolved", "A2 scope cannot be established by exact matching.", "sqlite_mismatch")
        elif replay.model_dump() != a2_envelope.model_dump():
            block("a2", "a2_sqlite_or_match_drift", "A2 differs from replay against the selected SQLite inventory.",
                  "sqlite_mismatch")
        rows = inventory_store.resolve_candidate_ids(tuple(f.item_id for f in a2_envelope.findings))
        audit.verified_item_ids = [row.item_id for row in rows]
    except (InventoryStoreError, sqlite3.Error, OSError):
        return fatal("inventory_store_unavailable", "Exact inventory could not be read.")

    audit.checks_run.append("a3_policy_and_provenance")
    try:
        validate_plan_against_a2(a3_envelope, a2_envelope)
        audit.review_boundary_verified = a3_envelope.requires_human_review
    except ValueError:
        block("a3", "a3_plan_policy_failed", "A3 plan differs from its bounded policy or A2 provenance.",
              "unsupported_claim")
    audit.upstream_needs_review = (isinstance(result, GroupCResult)
        or bool(base.facts.uncertainties) or a2_envelope.requires_human_review)
    return audit
