"""Pure deterministic evidence, SQLite cross-verification, and safety policy checks for A4.

Zero LLM, vector-store, or network imports. Re-verifies A1/A2/A3 artifacts
directly against authoritative read-only FDA and retailer inventory SQLite
stores without reading synthetic_generation_note or item_id suffixes (-A/-B).
"""

import re
import sqlite3
from typing import Annotated, Literal

from pydantic import Field

from a1_trace import RequestState
from citations import CitationError, validate_literal_identifier
from fda_store import StoreError
from group_c_contract import GroupCResult
from inventory_store import InventoryStoreError
from models import EvidenceIDs, Nonblank, StrictModel
from source import FIELDS


ActionType = Literal[
    "quarantine_hold",
    "verify_lot_manually",
    "notify_store_manager",
    "escalate_human_review",
    "no_stock_action_required",
    "auto_clear_stock",       # Accepted in input schema ONLY so A4 deterministically rejects it
    "modify_live_inventory",  # Accepted in input schema ONLY so A4 deterministically rejects it
    "send_live_fda_alert",    # Accepted in input schema ONLY so A4 deterministically rejects it
]

A4Verdict = Literal["approved", "revise", "human_review", "unresolved"]
RevisionTarget = Literal["a1", "a2", "a3"]
CheckSeverity = Literal["blocking", "warning"]
CheckSource = Literal["deterministic", "llm_critic"]
FindingCategory = Literal[
    "evidence_integrity",
    "sqlite_mismatch",
    "unsupported_claim",
    "uncertainty_dropped",
    "action_inappropriate",
    "prototype_boundary",
    "coverage_gap",
]
A4ErrorStage = Literal["preflight", "deterministic_checks", "llm_critic", "accounting", "coordinator"]
A4ErrorCode = Literal[
    "context_mismatch",
    "upstream_unresolved",
    "fda_store_unavailable",
    "inventory_store_unavailable",
    "budget_exhausted",
    "provider_failure",
    "incomplete_response",
    "model_refusal",
    "invalid_output",
    "usage_missing",
    "usage_ledger_unavailable",
    "usage_reservation_failed",
    "usage_settlement_failed",
    "critic_internal_failure",
]

FORBIDDEN_ACTIONS = frozenset({"auto_clear_stock", "modify_live_inventory", "send_live_fda_alert"})
PROTECTIVE_ACTIONS = frozenset({"quarantine_hold", "notify_store_manager"})
VERIFICATION_ACTIONS = frozenset({"verify_lot_manually", "escalate_human_review"})
NO_MATCH_ACTIONS = frozenset({"no_stock_action_required", "escalate_human_review"})

_PROTOTYPE_MARKERS = re.compile(r"\b(?:prototype|historical|educational)\b", re.IGNORECASE)
_ADVISORY_MARKERS = re.compile(r"\b(?:not\s+live|no\s+live|advisory|human|no\s+real|simulated)\b", re.IGNORECASE)
_PROHIBITED_CLAIMS = (
    ("live_fda_alert_claim", re.compile(r"\b(?:sent|dispatched|issued|triggered)\s+(?:a\s+)?live\s+fda\s+alert\b", re.IGNORECASE)),
    ("live_inventory_mutation_claim", re.compile(
        r"\b(?:updated|modified|deducted|removed|adjusted)\s+(?:the\s+)?(?:(?:live|erp|pos|production)\s+)+inventory\b"
        r"|\binventory\s+(?:was\s+|has\s+been\s+)?(?:updated|modified|deducted|removed|adjusted)\s+in\s+(?:the\s+)?(?:live|erp|pos|production)\b",
        re.IGNORECASE)),
    ("auto_clearance_claim", re.compile(r"\b(?:automatically\s+cleared|auto-?cleared|cleared\s+for\s+sale\s+without\s+(?:human\s+)?review)\b", re.IGNORECASE)),
)
_UNAVAILABLE_TOKENS = frozenset({"", "unknown", "no codes", "no code", "n/a"})


class ActionRecommendation(StrictModel):
    """Provisional A3 recommendation contract; adapted via normalize_a3_envelope on merge."""

    recommendation_id: Nonblank
    action_type: ActionType
    target_item_ids: list[Nonblank] = Field(default_factory=list)
    store_ids: list[Nonblank] = Field(default_factory=list)
    urgency: Literal["high", "medium", "low", "informational"]
    summary: Nonblank
    rationale: Nonblank
    cited_evidence_ids: Annotated[EvidenceIDs, Field(min_length=1)]
    requires_human_approval: bool
    is_advisory_only: bool


class A3RunEnvelope(StrictModel):
    """Provisional A3 execution boundary consumed by A4."""

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None = None
    status: Literal["planned", "review_required", "unresolved"]
    recommendations: list[ActionRecommendation] = Field(default_factory=list)
    uncertainties: list[Nonblank] = Field(default_factory=list)
    requires_human_review: bool = False
    prototype_disclaimer: str | None = None
    error: dict | None = None


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
    verified_inventory_rows: dict[str, dict[str, object]] = Field(default_factory=dict)
    canonical_event_id: Nonblank | None = None
    upstream_needs_review: bool = False
    prototype_disclaimer_verified: bool = False


def _normalize_upc_digits(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[\s\-]+", "", value)
    return cleaned if cleaned and cleaned.isdigit() else None


def _is_unavailable(text: str | None) -> bool:
    return text is None or text.strip().casefold() in _UNAVAILABLE_TOKENS


def _unique_nonblank(values) -> tuple[str, ...]:
    seen: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip() and item not in seen:
            seen.append(item)
    return tuple(seen)


def run_deterministic_checks(
    fda_store,
    inventory_store,
    a1_envelope,
    a2_envelope,
    a3_envelope: A3RunEnvelope,
    *,
    case_id: str,
    run_id: str,
    recall_number: str,
    snapshot_id: str,
    event_id: str | None = None,
) -> DeterministicAuditOutcome:
    """Execute D01-D09 deterministic evidence, SQLite, and safety checks."""
    checks_run: list[str] = []
    findings: list[CriticFinding] = []
    counter = 0

    def add_finding(
        *,
        severity: CheckSeverity,
        category: FindingCategory,
        target_agent: RevisionTarget,
        code: str,
        message: str,
        evidence_ids: list[str] | tuple[str, ...] = (),
        item_ids: list[str] | tuple[str, ...] = (),
        fixable_by_revision: bool = True,
    ) -> None:
        nonlocal counter
        counter += 1
        findings.append(
            CriticFinding(
                finding_id=f"DET-{counter:03d}",
                source="deterministic",
                severity=severity,
                category=category,
                target_agent=target_agent,
                code=code,
                message=message,
                evidence_ids=list(_unique_nonblank(evidence_ids)),
                item_ids=list(_unique_nonblank(item_ids)),
                fixable_by_revision=fixable_by_revision,
            )
        )

    def fatal(stage: A4ErrorStage, code: A4ErrorCode, message: str, *, canonical_ev: str | None = None) -> DeterministicAuditOutcome:
        return DeterministicAuditOutcome(
            fatal_error=A4Error(stage=stage, code=code, message=message),
            findings=findings,
            checks_run=checks_run,
            canonical_event_id=canonical_ev,
        )

    # ── D01: Context Identity & Store Availability ────────────────────────────
    checks_run.append("D01_context_identity")
    if fda_store is None or not (
        hasattr(fda_store, "snapshot_id") and hasattr(fda_store, "lookup") and hasattr(fda_store, "resolve")
    ):
        return fatal("preflight", "fda_store_unavailable", "Authoritative FDA SQLite store is unavailable.")
    if inventory_store is None or not (
        hasattr(inventory_store, "snapshot_id") and hasattr(inventory_store, "resolve_candidate_ids")
    ):
        return fatal("preflight", "inventory_store_unavailable", "Authoritative retailer inventory SQLite store is unavailable.")

    try:
        fda_snap = fda_store.snapshot_id
    except (StoreError, sqlite3.Error, OSError):
        return fatal("preflight", "fda_store_unavailable", "Authoritative FDA SQLite store failed snapshot check.")
    try:
        inv_snap = inventory_store.snapshot_id
    except (InventoryStoreError, sqlite3.Error, OSError):
        return fatal("preflight", "inventory_store_unavailable", "Authoritative inventory SQLite store failed snapshot check.")

    if (
        fda_snap != snapshot_id
        or inv_snap != snapshot_id
        or a1_envelope.run_id != run_id
        or a1_envelope.trace.recall_number != recall_number
        or a1_envelope.trace.snapshot_id != snapshot_id
        or (a2_envelope.case_id, a2_envelope.run_id, a2_envelope.recall_number, a2_envelope.snapshot_id)
        != (case_id, run_id, recall_number, snapshot_id)
        or (a3_envelope.case_id, a3_envelope.run_id, a3_envelope.recall_number, a3_envelope.snapshot_id)
        != (case_id, run_id, recall_number, snapshot_id)
    ):
        return fatal(
            "preflight",
            "context_mismatch",
            "Caller context differs from upstream A1/A2/A3 envelopes or SQLite store snapshots.",
        )

    if event_id is not None:
        for candidate_ev in (a1_envelope.trace.event_id, a2_envelope.event_id, a3_envelope.event_id):
            if candidate_ev is not None and candidate_ev != event_id:
                return fatal(
                    "preflight",
                    "context_mismatch",
                    "Upstream envelope event_id differs from caller-selected event_id.",
                )

    # ── D02: Upstream Status Verification ─────────────────────────────────────
    checks_run.append("D02_upstream_status")
    if (
        a1_envelope.status != "validated"
        or a1_envelope.result is None
        or a2_envelope.status == "unresolved"
        or a2_envelope.error is not None
        or a3_envelope.status == "unresolved"
        or a3_envelope.error is not None
    ):
        return fatal(
            "preflight",
            "upstream_unresolved",
            "Upstream A1, A2, or A3 envelope is unresolved; safety approval is blocked.",
        )

    a1_result = a1_envelope.result
    is_group_c = isinstance(a1_result, GroupCResult)
    base = a1_result.base if is_group_c else a1_result
    canonical_event_id = base.event_id

    if (
        base.facts.recall_number != recall_number
        or base.snapshot_id != snapshot_id
        or (event_id is not None and canonical_event_id != event_id)
        or (a1_envelope.trace.event_id is not None and a1_envelope.trace.event_id != canonical_event_id)
        or (a2_envelope.event_id is not None and a2_envelope.event_id != canonical_event_id)
        or (a3_envelope.event_id is not None and a3_envelope.event_id != canonical_event_id)
    ):
        return fatal(
            "preflight",
            "context_mismatch",
            "Canonical A1 event_id or recall/snapshot differs from upstream envelopes.",
            canonical_ev=canonical_event_id,
        )

    ctx = dict(recall_number=recall_number, event_id=canonical_event_id, snapshot_id=snapshot_id)

    # ── D03: Authoritative FDA SQLite Audit ───────────────────────────────────
    checks_run.append("D03_fda_sqlite_audit")
    try:
        record = fda_store.lookup(recall_number, snapshot_id=snapshot_id, event_id=canonical_event_id)
    except (sqlite3.Error, OSError):
        return fatal("deterministic_checks", "fda_store_unavailable", "FDA SQLite lookup failed.", canonical_ev=canonical_event_id)
    except StoreError as exc:
        low = str(exc).lower()
        if "hash" in low or "manifest" in low or "counts" in low:
            return fatal("deterministic_checks", "fda_store_unavailable", "FDA SQLite integrity check failed.", canonical_ev=canonical_event_id)
        return fatal("deterministic_checks", "context_mismatch", "Selected recall/event could not be resolved in FDA SQLite.", canonical_ev=canonical_event_id)

    verified_evidence_ids: list[str] = []
    verified_passages: dict[str, dict[str, str]] = {}
    expected_evidence_ids: set[str] = set()
    sf_dump = base.source_fields.model_dump()

    for field_name in FIELDS:
        ev_id = f"EV-{recall_number}-{field_name.upper()}"
        expected_evidence_ids.add(ev_id)
        try:
            exact = fda_store.resolve(ev_id, **ctx)
        except (sqlite3.Error, OSError):
            return fatal("deterministic_checks", "fda_store_unavailable", "FDA SQLite passage resolution failed.", canonical_ev=canonical_event_id)
        except StoreError:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="fda_passage_unresolvable",
                message=f"Canonical FDA passage {ev_id} could not be resolved in SQLite.",
            )
            continue
        verified_evidence_ids.append(exact.evidence_id)
        verified_passages[exact.evidence_id] = {
            "evidence_id": exact.evidence_id,
            "field_name": exact.field_name,
            "original_text": exact.original_text,
        }
        sf = sf_dump[field_name]
        if (sf["original_text"], sf["evidence_id"], sf["point_id"]) != (
            exact.original_text,
            exact.evidence_id,
            exact.point_id,
        ):
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="a1_source_field_drift",
                message=f"A1 source_fields.{field_name} differs from authoritative FDA SQLite passage.",
                evidence_ids=[exact.evidence_id],
            )

    for meta_field in ("recalling_firm", "classification"):
        sf = sf_dump[meta_field]
        if sf["original_text"] != record.get(meta_field) or sf["evidence_id"] is not None or sf["point_id"] is not None:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="a1_metadata_drift",
                message=f"A1 metadata field {meta_field} differs from FDA SQLite or carries invented passage IDs.",
            )

    for fact_attr, record_key in (
        ("product_name", "product_description"),
        ("recalling_firm", "recalling_firm"),
        ("recall_reason", "reason_for_recall"),
        ("classification", "classification"),
    ):
        raw_val = record.get(record_key)
        allowed_vals = {raw_val} | ({None} if _is_unavailable(raw_val) else set())
        if getattr(base.facts, fact_attr) not in allowed_vals:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="a1_fact_drift",
                message=f"A1 fact {fact_attr} differs from authoritative FDA SQLite record.",
            )

    if set(base.facts.evidence_ids) != expected_evidence_ids:
        add_finding(
            severity="blocking",
            category="evidence_integrity",
            target_agent="a1",
            code="a1_evidence_set_mismatch",
            message="A1 facts.evidence_ids does not equal the canonical 4-passage FDA evidence set.",
            evidence_ids=verified_evidence_ids,
        )

    for ident in base.facts.identifiers:
        if not set(ident.evidence_ids) <= expected_evidence_ids:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="a1_identifier_bad_citation",
                message=f"A1 identifier {ident.value!r} cites unknown or cross-recall evidence IDs.",
            )
            continue
        try:
            validate_literal_identifier(fda_store, ident.value, ident.evidence_ids, **ctx)
        except (sqlite3.Error, OSError):
            return fatal("deterministic_checks", "fda_store_unavailable", "FDA SQLite read failed during identifier check.", canonical_ev=canonical_event_id)
        except CitationError:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a1",
                code="a1_ungrounded_identifier",
                message=f"A1 identifier {ident.value!r} is not literally supported in cited FDA SQLite passages.",
                evidence_ids=[e for e in ident.evidence_ids if e in verified_passages],
            )

    if is_group_c:
        if not base.facts.uncertainties:
            add_finding(
                severity="blocking",
                category="uncertainty_dropped",
                target_agent="a1",
                code="group_c_missing_uncertainty",
                message="Group C A1 result is missing mandatory human-review uncertainty.",
                fixable_by_revision=False,
            )
        for rel in a1_result.relations:
            try:
                passage = fda_store.resolve(rel.evidence_id, **ctx)
            except (sqlite3.Error, OSError):
                return fatal("deterministic_checks", "fda_store_unavailable", "FDA SQLite read failed during Group C relation check.", canonical_ev=canonical_event_id)
            except StoreError:
                add_finding(
                    severity="blocking",
                    category="evidence_integrity",
                    target_agent="a1",
                    code="group_c_bad_relation_citation",
                    message=f"Group C relation cites unresolvable evidence ID {rel.evidence_id!r}.",
                )
                continue
            if (
                rel.start < 0
                or rel.end > len(passage.original_text)
                or rel.start >= rel.end
                or passage.original_text[rel.start:rel.end] != rel.source_span
            ):
                add_finding(
                    severity="blocking",
                    category="evidence_integrity",
                    target_agent="a1",
                    code="group_c_span_mismatch",
                    message="Group C SourceRelation offsets or source_span differ from authoritative FDA SQLite text.",
                    evidence_ids=[passage.evidence_id],
                )
            for part in rel.parts:
                if part.role != "state" and part.value not in rel.source_span:
                    add_finding(
                        severity="blocking",
                        category="evidence_integrity",
                        target_agent="a1",
                        code="group_c_part_outside_span",
                        message=f"Group C relation value {part.value!r} is outside its cited source_span.",
                        evidence_ids=[passage.evidence_id],
                    )

    for finding in a2_envelope.findings:
        bad_a2_eids = [eid for eid in finding.a1_evidence_ids if eid not in verified_passages]
        if bad_a2_eids:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a2",
                code="a2_unknown_evidence_id",
                message=f"A2 finding {finding.item_id} cites unverified FDA evidence IDs.",
                item_ids=(finding.item_id,),
            )

    for rec in a3_envelope.recommendations:
        bad_a3_eids = [eid for eid in rec.cited_evidence_ids if eid not in verified_passages]
        if bad_a3_eids:
            add_finding(
                severity="blocking",
                category="evidence_integrity",
                target_agent="a3",
                code="a3_unknown_evidence_id",
                message=f"A3 recommendation {rec.recommendation_id} cites unverified or cross-recall FDA evidence IDs.",
                item_ids=rec.target_item_ids,
            )

    # ── D04: Authoritative Retailer Inventory SQLite Audit ────────────────────
    checks_run.append("D04_inventory_sqlite_audit")
    seen_a2_items: set[str] = set()
    for finding in a2_envelope.findings:
        if finding.item_id in seen_a2_items:
            add_finding(
                severity="blocking",
                category="sqlite_mismatch",
                target_agent="a2",
                code="a2_duplicate_item_id",
                message=f"A2 envelope contains duplicate item_id {finding.item_id}.",
                item_ids=(finding.item_id,),
            )
        seen_a2_items.add(finding.item_id)

    seen_rec_ids: set[str] = set()
    for rec in a3_envelope.recommendations:
        if rec.recommendation_id in seen_rec_ids:
            add_finding(
                severity="blocking",
                category="coverage_gap",
                target_agent="a3",
                code="a3_duplicate_recommendation_id",
                message=f"A3 envelope contains duplicate recommendation_id {rec.recommendation_id}.",
            )
        seen_rec_ids.add(rec.recommendation_id)

    referenced_item_ids = _unique_nonblank(
        [f.item_id for f in a2_envelope.findings]
        + [iid for rec in a3_envelope.recommendations for iid in rec.target_item_ids]
    )
    sql_rows: dict[str, object] = {}
    if referenced_item_ids:
        try:
            resolved_rows = inventory_store.resolve_candidate_ids(referenced_item_ids)
        except (InventoryStoreError, sqlite3.Error, OSError):
            return fatal(
                "deterministic_checks",
                "inventory_store_unavailable",
                "Retailer inventory SQLite read failed during item verification.",
                canonical_ev=canonical_event_id,
            )
        sql_rows = {row.item_id: row for row in resolved_rows}

    verified_item_ids = [iid for iid in referenced_item_ids if iid in sql_rows]
    # Preserve authoritative SQLite fields for Layer 2; NEVER expose synthetic_generation_note.
    verified_inventory_rows: dict[str, dict[str, object]] = {
        iid: {
            "inventory_set_id": row.inventory_set_id,
            "item_id": row.item_id,
            "retailer_id": row.retailer_id,
            "store_id": row.store_id,
            "product_label": row.product_label,
            "brand": row.brand,
            "upc": row.upc,
            "lot_code": row.lot_code,
            "package_size": row.package_size,
            "simulated_quantity": row.simulated_quantity,
            "quantity_unit": row.quantity_unit,
            "inventory_reference_date": row.inventory_reference_date,
        }
        for iid, row in sql_rows.items()
    }

    _SQLITE_COMPARE_COLS = (
        "inventory_set_id",
        "retailer_id",
        "store_id",
        "product_label",
        "brand",
        "upc",
        "lot_code",
        "package_size",
        "simulated_quantity",
        "quantity_unit",
        "inventory_reference_date",
    )
    for finding in a2_envelope.findings:
        row = sql_rows.get(finding.item_id)
        if row is None:
            add_finding(
                severity="blocking",
                category="sqlite_mismatch",
                target_agent="a2",
                code="a2_hallucinated_item_id",
                message=f"A2 finding references item_id {finding.item_id} which does not exist in inventory SQLite.",
                item_ids=(finding.item_id,),
            )
            continue
        drifted = [col for col in _SQLITE_COMPARE_COLS if getattr(finding, col) != getattr(row, col)]
        if drifted:
            add_finding(
                severity="blocking",
                category="sqlite_mismatch",
                target_agent="a2",
                code="a2_sqlite_attribute_drift",
                message=f"A2 finding {finding.item_id} differs from authoritative SQLite on: {', '.join(drifted)}.",
                item_ids=(finding.item_id,),
            )

    for rec in a3_envelope.recommendations:
        missing_in_sql = [iid for iid in rec.target_item_ids if iid not in sql_rows]
        if missing_in_sql:
            add_finding(
                severity="blocking",
                category="sqlite_mismatch",
                target_agent="a3",
                code="a3_hallucinated_item_id",
                message=f"A3 recommendation {rec.recommendation_id} targets unverified item IDs absent from SQLite.",
                item_ids=tuple(missing_in_sql),
            )
        if rec.store_ids:
            if not rec.target_item_ids:
                add_finding(
                    severity="blocking",
                    category="sqlite_mismatch",
                    target_agent="a3",
                    code="a3_ungrounded_store_ids",
                    message=f"A3 recommendation {rec.recommendation_id} specifies store_ids without target_item_ids.",
                )
            elif not missing_in_sql:
                expected_stores = {sql_rows[iid].store_id for iid in rec.target_item_ids}
                if set(rec.store_ids) != expected_stores:
                    add_finding(
                        severity="blocking",
                        category="sqlite_mismatch",
                        target_agent="a3",
                        code="a3_store_id_mismatch",
                        message=f"A3 recommendation {rec.recommendation_id} store_ids differ from authoritative SQLite store_ids.",
                        item_ids=rec.target_item_ids,
                    )

    # ── D05: Independent A2 Match-Invariant Re-Verification ───────────────────
    checks_run.append("D05_a2_match_invariants")
    if is_group_c:
        a1_lots = {
            part.value
            for rel in a1_result.relations
            if rel.kind != "date_range"
            for part in rel.parts
            if part.role in ("lot", "code")
        }
    else:
        a1_lots = {i.value for i in base.facts.identifiers if i.kind in ("lot", "batch")}
    a1_upcs = {
        digits
        for i in base.facts.identifiers
        if i.kind == "upc"
        if (digits := _normalize_upc_digits(i.value)) is not None
    }

    if a2_envelope.status == "no_match" and a2_envelope.findings:
        add_finding(
            severity="blocking",
            category="sqlite_mismatch",
            target_agent="a2",
            code="a2_no_match_nonempty_findings",
            message="A2 status is no_match but findings list is non-empty.",
        )

    for finding in a2_envelope.findings:
        row = sql_rows.get(finding.item_id)
        if row is None:
            continue
        if finding.lot_match == "matched" and (row.lot_code == "" or row.lot_code not in a1_lots):
            add_finding(
                severity="blocking",
                category="sqlite_mismatch",
                target_agent="a2",
                code="a2_unverified_lot_match",
                message=f"A2 claims lot_match='matched' for {finding.item_id}, but SQLite lot_code {row.lot_code!r} is not an exact A1 lot/batch.",
                item_ids=(finding.item_id,),
            )
        if finding.upc_match == "matched":
            inv_upc = _normalize_upc_digits(row.upc)
            if inv_upc is None or inv_upc not in a1_upcs:
                add_finding(
                    severity="blocking",
                    category="sqlite_mismatch",
                    target_agent="a2",
                    code="a2_unverified_upc_match",
                    message=f"A2 claims upc_match='matched' for {finding.item_id}, but SQLite UPC does not match any A1 UPC.",
                    item_ids=(finding.item_id,),
                )
        if finding.match_status == "exact":
            attrs = (
                finding.lot_match,
                finding.brand_match,
                finding.product_name_match,
                finding.package_size_match,
                finding.upc_match,
            )
            if (
                finding.lot_match != "matched"
                or finding.product_name_match != "matched"
                or "mismatched" in attrs
                or finding.requires_human_review
                or finding.a1_uncertainties
                or is_group_c
            ):
                add_finding(
                    severity="blocking",
                    category="sqlite_mismatch",
                    target_agent="a2",
                    code="a2_invalid_exact_claim",
                    message=f"A2 claims match_status='exact' for {finding.item_id} despite missing exact criteria or active uncertainty.",
                    item_ids=(finding.item_id,),
                )
        elif finding.match_status == "partial" and not finding.requires_human_review:
            add_finding(
                severity="blocking",
                category="uncertainty_dropped",
                target_agent="a2",
                code="a2_partial_missing_review",
                message=f"A2 partial finding {finding.item_id} must set requires_human_review=True.",
                item_ids=(finding.item_id,),
            )
        if row.simulated_quantity == 0:
            add_finding(
                severity="warning",
                category="action_inappropriate",
                target_agent="a3",
                code="zero_simulated_quantity",
                message=f"Matched inventory row {finding.item_id} has simulated_quantity=0; verify stock count before disposal claims.",
                item_ids=(finding.item_id,),
                fixable_by_revision=False,
            )

    # ── D06: Uncertainty Preservation ─────────────────────────────────────────
    checks_run.append("D06_uncertainty_preservation")
    upstream_needs_review = (
        is_group_c
        or bool(base.facts.uncertainties)
        or (base.facts.classification is None)
        or (a2_envelope.status == "partial")
        or a2_envelope.requires_human_review
        or any(f.requires_human_review for f in a2_envelope.findings)
    )
    if upstream_needs_review:
        if not (a3_envelope.requires_human_review or a3_envelope.status == "review_required"):
            add_finding(
                severity="blocking",
                category="uncertainty_dropped",
                target_agent="a3",
                code="a3_dropped_human_review",
                message="Upstream A1/A2 uncertainty, Group C relation, or partial match requires A3 to preserve human review.",
            )
        if a2_envelope.findings and any(r.action_type == "no_stock_action_required" for r in a3_envelope.recommendations):
            add_finding(
                severity="blocking",
                category="uncertainty_dropped",
                target_agent="a3",
                code="a3_premature_no_action_with_findings",
                message="A3 cannot issue no_stock_action_required when uncertain/partial inventory findings exist.",
            )

    # ── D07: Coverage & Targeting Rules ───────────────────────────────────────
    checks_run.append("D07_coverage_and_targeting")
    if not a3_envelope.recommendations:
        add_finding(
            severity="blocking",
            category="coverage_gap",
            target_agent="a3",
            code="a3_empty_recommendations",
            message="A3 must produce at least one explicit advisory recommendation (even on no_match).",
        )

    a2_by_id = {f.item_id: f for f in a2_envelope.findings}
    for rec in a3_envelope.recommendations:
        non_a2_targets = [iid for iid in rec.target_item_ids if iid not in a2_by_id]
        if non_a2_targets:
            add_finding(
                severity="blocking",
                category="coverage_gap",
                target_agent="a3",
                code="a3_targets_non_a2_item",
                message=f"A3 recommendation {rec.recommendation_id} targets item IDs not present in A2 findings.",
                item_ids=tuple(non_a2_targets),
            )

    if a2_envelope.status == "no_match":
        for rec in a3_envelope.recommendations:
            if rec.target_item_ids:
                add_finding(
                    severity="blocking",
                    category="coverage_gap",
                    target_agent="a3",
                    code="a3_no_match_targets_items",
                    message=f"A3 recommendation {rec.recommendation_id} cannot target inventory items when A2 status is no_match.",
                    item_ids=rec.target_item_ids,
                )
            if rec.action_type not in NO_MATCH_ACTIONS and rec.action_type not in FORBIDDEN_ACTIONS:
                add_finding(
                    severity="blocking",
                    category="action_inappropriate",
                    target_agent="a3",
                    code="a3_no_match_wrong_action",
                    message=f"A3 action_type {rec.action_type!r} is inappropriate when A2 status is no_match.",
                )
    else:
        exact_ids = [f.item_id for f in a2_envelope.findings if f.match_status == "exact"]
        partial_ids = [f.item_id for f in a2_envelope.findings if f.match_status == "partial"]

        for iid in exact_ids:
            covering = [r for r in a3_envelope.recommendations if iid in r.target_item_ids]
            if not any(r.action_type in PROTECTIVE_ACTIONS for r in covering):
                add_finding(
                    severity="blocking",
                    category="coverage_gap",
                    target_agent="a3",
                    code="a3_missing_exact_coverage",
                    message=f"Exact matched inventory item {iid} lacks protective advisory coverage (quarantine_hold or notify_store_manager).",
                    item_ids=(iid,),
                )
        for iid in partial_ids:
            covering = [r for r in a3_envelope.recommendations if iid in r.target_item_ids]
            if not any(r.action_type in VERIFICATION_ACTIONS for r in covering):
                add_finding(
                    severity="blocking",
                    category="coverage_gap",
                    target_agent="a3",
                    code="a3_partial_missing_verification",
                    message=f"Partial matched inventory item {iid} must be covered by verify_lot_manually or escalate_human_review.",
                    item_ids=(iid,),
                )

    # ── D08: Action Appropriateness & FDA Classification Proportionality ──────
    checks_run.append("D08_action_proportionality")
    classification = (base.facts.classification or "").strip()
    exact_id_set = {f.item_id for f in a2_envelope.findings if f.match_status == "exact"}

    for rec in a3_envelope.recommendations:
        if rec.action_type in FORBIDDEN_ACTIONS:
            add_finding(
                severity="blocking",
                category="prototype_boundary",
                target_agent="a3",
                code=f"forbidden_action_{rec.action_type}",
                message=f"A3 recommendation {rec.recommendation_id} uses prohibited action_type {rec.action_type!r}.",
                item_ids=rec.target_item_ids,
            )
        if not rec.requires_human_approval:
            add_finding(
                severity="blocking",
                category="prototype_boundary",
                target_agent="a3",
                code="a3_missing_human_approval_flag",
                message=f"A3 recommendation {rec.recommendation_id} must set requires_human_approval=True.",
                item_ids=rec.target_item_ids,
            )
        if not rec.is_advisory_only:
            add_finding(
                severity="blocking",
                category="prototype_boundary",
                target_agent="a3",
                code="a3_not_advisory_only",
                message=f"A3 recommendation {rec.recommendation_id} must set is_advisory_only=True.",
                item_ids=rec.target_item_ids,
            )
        if rec.action_type == "no_stock_action_required" and any(iid in exact_id_set for iid in rec.target_item_ids):
            add_finding(
                severity="blocking",
                category="action_inappropriate",
                target_agent="a3",
                code="a3_exact_match_downgraded",
                message=f"A3 recommendation {rec.recommendation_id} cannot issue no_stock_action_required for exact matched items.",
                item_ids=tuple(iid for iid in rec.target_item_ids if iid in exact_id_set),
            )
        if a2_envelope.status == "no_match" and rec.action_type == "no_stock_action_required" and rec.urgency not in ("low", "informational"):
            add_finding(
                severity="blocking",
                category="action_inappropriate",
                target_agent="a3",
                code="a3_no_match_excessive_urgency",
                message=f"A3 no_stock_action_required on no_match must use low or informational urgency, got {rec.urgency!r}.",
            )

    if exact_id_set and classification in ("Class I", "Class II"):
        required_urgencies = ("high",) if classification == "Class I" else ("high", "medium")
        for iid in sorted(exact_id_set):
            protective = [
                r for r in a3_envelope.recommendations
                if iid in r.target_item_ids and r.action_type in PROTECTIVE_ACTIONS
            ]
            if protective and not any(r.urgency in required_urgencies for r in protective):
                add_finding(
                    severity="blocking",
                    category="action_inappropriate",
                    target_agent="a3",
                    code="a3_urgency_below_classification",
                    message=f"{classification} exact match {iid} requires urgency in {required_urgencies}.",
                    item_ids=(iid,),
                )

    # ── D09: Prototype Disclaimer & Prohibited Execution Claims ───────────────
    checks_run.append("D09_prototype_boundary")
    disclaimer_ok = False
    disclaimer = a3_envelope.prototype_disclaimer
    if (
        isinstance(disclaimer, str)
        and disclaimer.strip()
        and _PROTOTYPE_MARKERS.search(disclaimer)
        and _ADVISORY_MARKERS.search(disclaimer)
    ):
        disclaimer_ok = True
    else:
        add_finding(
            severity="blocking",
            category="prototype_boundary",
            target_agent="a3",
            code="a3_missing_prototype_disclaimer",
            message="A3 must include a clear historical educational prototype / non-live advisory disclaimer.",
        )

    prohibited_claim_found = False
    for rec in a3_envelope.recommendations:
        combined = f"{rec.summary}\n{rec.rationale}"
        for claim_code, pattern in _PROHIBITED_CLAIMS:
            if pattern.search(combined):
                prohibited_claim_found = True
                add_finding(
                    severity="blocking",
                    category="prototype_boundary",
                    target_agent="a3",
                    code=claim_code,
                    message=f"A3 recommendation {rec.recommendation_id} contains prohibited execution or auto-clearance claim ({claim_code}).",
                    item_ids=rec.target_item_ids,
                )

    return DeterministicAuditOutcome(
        fatal_error=None,
        findings=findings,
        checks_run=checks_run,
        verified_evidence_ids=verified_evidence_ids,
        verified_item_ids=verified_item_ids,
        verified_passages=verified_passages,
        verified_inventory_rows=verified_inventory_rows,
        canonical_event_id=canonical_event_id,
        upstream_needs_review=upstream_needs_review,
        prototype_disclaimer_verified=disclaimer_ok and not prohibited_claim_found,
    )
