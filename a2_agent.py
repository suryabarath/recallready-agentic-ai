"""A2 Inventory Investigation Agent and typed A2-to-A3 contracts.

Receives a validated A1RunEnvelope, extracts source-supported recall scope
for both 0.1-proposed (A1Result) and 0.2-group-c-provisional (GroupCResult),
queries authoritative read-only SQLite retailer inventory, and returns strict
InventoryFinding results without recommending recall actions or dispositions.
"""

from typing import Annotated, Literal, Self

from a1_run import A1RunEnvelope
from group_c_contract import GroupCResult
from inventory_match import (
    AttributeMatchStatus,
    InventoryMatch,
    MatchLevel,
    RecallInventoryScope,
    compare_recall_to_inventory,
    extract_explicit_brand_from_text,
    extract_package_sizes_from_text,
)
from inventory_store import (
    InventoryRow,
    InventorySchemaError,
    InventoryStore,
    InventoryStoreError,
)
from models import A1Result, EvidenceIDs, Nonblank, StrictModel
from pydantic import Field, model_validator


A2ErrorCode = Literal[
    "a1_unresolved",
    "a1_context_mismatch",
    "inventory_store_unavailable",
    "inventory_schema_invalid",
    "inventory_match_failed",
    "ambiguous_recall_scope",
]

A2Status = Literal["matched", "partial", "no_match", "unresolved"]


class A2Error(StrictModel):
    code: A2ErrorCode
    message: Nonblank
    automatic_retry_allowed: Literal[False] = False


class InventoryFinding(StrictModel):
    """Shared Pydantic InventoryFinding contract for the A2-to-A3 boundary.

    Contains only authoritative SQLite inventory attributes, deterministic
    match statuses, and A1 evidence references. Free-text LLM judgments and
    A3 stock disposition actions are forbidden.
    """

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank
    inventory_set_id: Nonblank
    item_id: Nonblank
    retailer_id: Nonblank
    store_id: Nonblank
    brand: str
    product_label: str
    package_size: str
    lot_code: str
    upc: str
    simulated_quantity: int = Field(ge=0)
    quantity_unit: Nonblank
    inventory_reference_date: Nonblank
    match_status: MatchLevel
    lot_match: AttributeMatchStatus
    brand_match: AttributeMatchStatus
    product_name_match: AttributeMatchStatus
    package_size_match: AttributeMatchStatus
    upc_match: AttributeMatchStatus
    reason_codes: tuple[Nonblank, ...] = Field(min_length=1)
    a1_evidence_ids: Annotated[EvidenceIDs, Field(min_length=1)]
    a1_identifier_values: tuple[Nonblank, ...] = ()
    a1_uncertainties: tuple[Nonblank, ...] = ()
    requires_human_review: bool

    @model_validator(mode="after")
    def validate_finding_invariants(self) -> Self:
        if not self.a1_evidence_ids:
            raise ValueError("InventoryFinding requires at least one A1 evidence_id")
        if self.match_status == "exact":
            if self.lot_match != "matched" or self.product_name_match != "matched":
                raise ValueError("Exact finding requires matched lot and product_name")
            if self.requires_human_review or self.a1_uncertainties:
                raise ValueError("Exact finding cannot carry unresolved A1 uncertainty or require review")
        if self.match_status == "partial" and not self.requires_human_review:
            raise ValueError("Partial finding must require human review")
        return self


class A2RunEnvelope(StrictModel):
    """Typed A2-to-A3 execution boundary."""

    case_id: Nonblank
    run_id: Nonblank
    recall_number: Nonblank
    snapshot_id: Nonblank
    event_id: Nonblank | None  # None only when A1 never resolved a canonical event
    status: A2Status
    findings: list[InventoryFinding] = Field(default_factory=list)
    error: A2Error | None = None
    requires_human_review: bool = False

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        if self.status == "unresolved":
            if self.error is None or self.findings:
                raise ValueError("Unresolved A2 envelope requires an error and no findings")
        else:
            if self.error is not None:
                raise ValueError("Resolved A2 status cannot carry an error")
        if self.status == "matched":
            if not self.findings or not any(f.match_status == "exact" for f in self.findings):
                raise ValueError("Matched A2 status requires at least one exact finding")
        elif self.status == "partial":
            if not self.findings or any(f.match_status == "exact" for f in self.findings):
                raise ValueError("Partial A2 status requires partial findings and no exact findings")
            if not self.requires_human_review:
                raise ValueError("Partial A2 status must require human review")
        elif self.status == "no_match":
            if self.findings:
                raise ValueError("no_match A2 status requires an empty findings list")
        return self


def _extract_a1_scope(
    envelope: A1RunEnvelope,
    *,
    case_id: str,
    run_id: str | None,
    recall_number: str | None,
    snapshot_id: str | None,
    event_id: str | None,
) -> tuple[RecallInventoryScope | None, A2Error | None, tuple[str, str, str, str]]:
    """Validate context against A1RunEnvelope and extract deterministic scope."""
    eff_run_id = run_id if run_id is not None else envelope.run_id
    eff_recall = recall_number if recall_number is not None else envelope.trace.recall_number
    eff_snapshot = snapshot_id if snapshot_id is not None else envelope.trace.snapshot_id
    eff_event = event_id if event_id is not None else envelope.trace.event_id

    if (
        (run_id is not None and run_id != envelope.run_id)
        or (recall_number is not None and recall_number != envelope.trace.recall_number)
        or (snapshot_id is not None and snapshot_id != envelope.trace.snapshot_id)
        or (
            event_id is not None
            and envelope.trace.event_id is not None
            and event_id != envelope.trace.event_id
        )
    ):
        return (
            None,
            A2Error(
                code="a1_context_mismatch",
                message="Caller context differs from A1 envelope trace identity.",
            ),
            (eff_run_id, eff_recall, eff_snapshot, eff_event),
        )

    if envelope.status != "validated" or envelope.result is None:
        return (
            None,
            A2Error(
                code="a1_unresolved",
                message="A1 status is unresolved or result is absent; inventory check skipped.",
            ),
            (eff_run_id, eff_recall, eff_snapshot, eff_event),
        )

    result = envelope.result
    base: A1Result = result.base if isinstance(result, GroupCResult) else result
    eff_event = base.event_id

    if (
        base.facts.recall_number != envelope.trace.recall_number
        or base.snapshot_id != envelope.trace.snapshot_id
        or (envelope.trace.event_id is not None and base.event_id != envelope.trace.event_id)
        or (recall_number is not None and base.facts.recall_number != recall_number)
        or (snapshot_id is not None and base.snapshot_id != snapshot_id)
        or (event_id is not None and base.event_id != event_id)
    ):
        return (
            None,
            A2Error(
                code="a1_context_mismatch",
                message="A1 result facts differ from envelope trace or caller context.",
            ),
            (eff_run_id, eff_recall, eff_snapshot, eff_event),
        )

    lots: list[str] = []
    upcs: list[str] = []
    skus: list[str] = []
    pkgs: list[str] = list(extract_package_sizes_from_text(base.facts.product_name))
    ambiguous_pkg_lot = False

    is_group_c = isinstance(result, GroupCResult)
    notes: list[tuple[str, str]] = []
    for ident in base.facts.identifiers:
        if ident.kind in ("lot", "batch"):
            # Group C lots/codes come only from explicit source relations;
            # the flat identifier list is never used to widen them.
            if is_group_c:
                continue
            if ident.value not in lots:
                lots.append(ident.value)
                if ident.kind == "batch":
                    # Inventory has a single lot_code column; A1 "batch" values
                    # are compared against it (needs M1 confirmation) and flagged.
                    notes.append((ident.value, f"lot_source:batch_identifier:{ident.value}"))
        elif ident.kind == "upc":
            if ident.value not in upcs:
                upcs.append(ident.value)
        elif ident.kind == "sku":
            if ident.value not in skus:
                skus.append(ident.value)

    if isinstance(result, GroupCResult):
        # Extract explicit lot/date or package relationships without flattening or guessing
        for rel in result.relations:
            roles = {part.role: part.value for part in rel.parts}
            if rel.kind == "date_range":
                continue  # a date range carries no lot/code to compare
            key = roles.get("lot") or roles.get("code")
            if key is not None:
                if key not in lots:
                    lots.append(key)
                state = f"{roles['state']}:" if "state" in roles else ""
                notes.append((key, f"lot_source:relation:{rel.kind}:{state}{key}|{roles.get('date')}"))
            if rel.kind == "package_code_date" and "package" in roles and roles["package"] not in pkgs:
                pkgs.append(roles["package"])
        # Multiple sizes and multiple lots without an explicit package<->code
        # relation cannot be paired; never guess the association.
        has_pkg_relation = any(r.kind == "package_code_date" for r in result.relations)
        if len(pkgs) > 1 and len(lots) > 1 and not has_pkg_relation:
            ambiguous_pkg_lot = True

    brand = extract_explicit_brand_from_text(base.facts.product_name)

    scope = RecallInventoryScope(
        recall_number=base.facts.recall_number,
        snapshot_id=base.snapshot_id,
        event_id=base.event_id,
        product_name=base.facts.product_name,
        brand=brand,
        lot_numbers=tuple(lots),
        package_sizes=tuple(pkgs),
        upcs=tuple(upcs),
        skus=tuple(skus),
        uncertainties=tuple(base.facts.uncertainties),
        evidence_ids=tuple(base.facts.evidence_ids),
        has_ambiguous_package_lot_relation=ambiguous_pkg_lot,
        source_notes=tuple(notes),
    )
    return (scope, None, (eff_run_id, eff_recall, eff_snapshot, eff_event))


def _build_finding(
    scope: RecallInventoryScope,
    row: InventoryRow,
    match: InventoryMatch,
    *,
    case_id: str,
    run_id: str,
) -> InventoryFinding:
    ident_values: list[str] = []
    for val in (*scope.lot_numbers, *scope.upcs, *scope.skus):
        if val and val not in ident_values:
            ident_values.append(val)

    effective_uncertainties = scope.uncertainties
    matched_lot = match.diagnostics.matched_lot_value
    provenance = tuple(text for key, text in scope.source_notes if key == matched_lot)
    reason_codes = match.diagnostics.reason_codes + provenance
    requires_review = (
        match.match_status != "exact"
        or bool(effective_uncertainties)
        or scope.has_ambiguous_package_lot_relation
    )
    effective_status: MatchLevel = (
        "partial" if (match.match_status == "exact" and requires_review) else match.match_status
    )

    return InventoryFinding(
        case_id=case_id,
        run_id=run_id,
        recall_number=scope.recall_number,
        snapshot_id=scope.snapshot_id,
        event_id=scope.event_id,
        inventory_set_id=row.inventory_set_id,
        item_id=row.item_id,
        retailer_id=row.retailer_id,
        store_id=row.store_id,
        brand=row.brand,
        product_label=row.product_label,
        package_size=row.package_size,
        lot_code=row.lot_code,
        upc=row.upc,
        simulated_quantity=row.simulated_quantity,
        quantity_unit=row.quantity_unit,
        inventory_reference_date=row.inventory_reference_date,
        match_status=effective_status,
        lot_match=match.lot,
        brand_match=match.brand,
        product_name_match=match.product_name,
        package_size_match=match.package_size,
        upc_match=match.upc,
        reason_codes=reason_codes,
        a1_evidence_ids=list(scope.evidence_ids),
        a1_identifier_values=tuple(ident_values),
        a1_uncertainties=effective_uncertainties,
        requires_human_review=requires_review,
    )


def run_a2(
    inventory_store: InventoryStore,
    envelope: A1RunEnvelope,
    *,
    case_id: str = "CASE-DEFAULT",
    run_id: str | None = None,
    recall_number: str | None = None,
    snapshot_id: str | None = None,
    event_id: str | None = None,
    candidate_item_ids: tuple[str, ...] | None = None,
    allow_group_c_or_uncertain: bool = False,
) -> A2RunEnvelope:
    """Execute A2 inventory investigation against authoritative read-only SQLite store.

    Preserves A1RunEnvelope identity without copying A1 facts into an editable model.
    Enforces attribute policy from Section 2.2:
    - A1 unresolved or context mismatch -> unresolved A2Error
    - No identifiers and no package information -> unresolved ambiguous_recall_scope
    - Lot unknown -> never returns exact match; returns partial or unresolved ambiguous_recall_scope
    - Group C or A1 uncertainty -> stops with ambiguous_recall_scope unless allow_group_c_or_uncertain
      is enabled (which preserves uncertainty on partial/review-required findings).
    """
    if not isinstance(envelope, A1RunEnvelope):
        raise TypeError("run_a2 requires a validated A1RunEnvelope instance")

    scope, error, (eff_run_id, eff_recall, eff_snapshot, eff_event) = _extract_a1_scope(
        envelope,
        case_id=case_id,
        run_id=run_id,
        recall_number=recall_number,
        snapshot_id=snapshot_id,
        event_id=event_id,
    )
    if error is not None or scope is None:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=error,
            requires_human_review=True,
        )

    # Duck-typed read-only store (real InventoryStore or a test double).
    if inventory_store is None or not hasattr(inventory_store, "find_inventory_candidates"):
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="inventory_store_unavailable",
                message="Authoritative SQLite inventory store is unavailable.",
            ),
            requires_human_review=True,
        )

    if inventory_store.snapshot_id != scope.snapshot_id:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="a1_context_mismatch",
                message="Inventory store snapshot_id differs from A1 envelope snapshot_id.",
            ),
            requires_human_review=True,
        )

    result = envelope.result
    is_group_c = isinstance(result, GroupCResult)
    has_uncertainty = bool(scope.uncertainties) or is_group_c

    if has_uncertainty and not allow_group_c_or_uncertain:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="ambiguous_recall_scope",
                message="A1 result carries uncertainties or Group C relations requiring human review before A2.",
            ),
            requires_human_review=True,
        )

    if scope.has_ambiguous_package_lot_relation:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="ambiguous_recall_scope",
                message="Group C package-to-lot association is ambiguous and cannot be flattened or guessed.",
            ),
            requires_human_review=True,
        )

    has_any_identifier = bool(scope.lot_numbers or scope.upcs or scope.skus)
    if not has_any_identifier and not scope.package_sizes:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="ambiguous_recall_scope",
                message="Recall scope has no identifiers and no package information.",
            ),
            requires_human_review=True,
        )

    if not scope.lot_numbers:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="ambiguous_recall_scope",
                message="Recall lot is unknown; refusing to broaden search to brand/product/package alone.",
            ),
            requires_human_review=True,
        )

    try:
        candidates = inventory_store.find_inventory_candidates(
            brand=scope.brand,
            product_name=scope.product_name,
            lot_numbers=scope.lot_numbers,
            package_sizes=scope.package_sizes,
            upcs=scope.upcs,
            candidate_item_ids=candidate_item_ids,
        )
    except InventorySchemaError:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="inventory_schema_invalid",
                message="Inventory store schema failed validation during candidate lookup.",
            ),
            requires_human_review=True,
        )
    except InventoryStoreError:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="inventory_store_unavailable",
                message="Inventory store read failed during candidate lookup.",
            ),
            requires_human_review=True,
        )

    exact_findings: list[InventoryFinding] = []
    partial_findings: list[InventoryFinding] = []

    try:
        for row in candidates:
            match = compare_recall_to_inventory(scope, row)
            if match.match_status == "no_match":
                continue
            finding = _build_finding(
                scope,
                row,
                match,
                case_id=case_id,
                run_id=eff_run_id,
            )
            if finding.match_status == "exact":
                exact_findings.append(finding)
            elif finding.match_status == "partial":
                partial_findings.append(finding)
    except Exception:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="unresolved",
            error=A2Error(
                code="inventory_match_failed",
                message="Deterministic inventory comparison failed unexpectedly.",
            ),
            requires_human_review=True,
        )

    if exact_findings:
        all_findings = exact_findings + partial_findings
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="matched",
            findings=all_findings,
            requires_human_review=any(f.requires_human_review for f in all_findings),
        )

    if partial_findings:
        return A2RunEnvelope(
            case_id=case_id,
            run_id=eff_run_id,
            recall_number=eff_recall,
            snapshot_id=eff_snapshot,
            event_id=eff_event,
            status="partial",
            findings=partial_findings,
            requires_human_review=True,
        )

    return A2RunEnvelope(
        case_id=case_id,
        run_id=eff_run_id,
        recall_number=eff_recall,
        snapshot_id=eff_snapshot,
        event_id=eff_event,
        status="no_match",
        findings=[],
        requires_human_review=False,
    )
