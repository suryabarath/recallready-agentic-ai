"""Offline source validation for the M1-approved A1 output contract.

No extraction, inference, normalization, inventory decisions, or repair loop.
Passing these checks does not establish semantic completeness or accuracy.
"""

import re
from dataclasses import dataclass

from citations import CitationError, validate_citation, validate_literal_identifier
from models import A1Result
from source import Evidence, FIELDS, Source, SourceError


class ContractError(ValueError):
    """A well-shaped result conflicts with the selected source or review policy."""

    def __init__(self, message: str, *, rule: str = "source_contract_failed"):
        super().__init__(message)
        self.rule = rule


@dataclass(frozen=True)
class HumanLotApproval:
    recall_number: str
    event_id: str
    snapshot_id: str
    evidence_id: str
    original_text: str
    value: str
    reviewer: str


_FACT_FIELDS = {
    "product_name": "product_description", "recalling_firm": "recalling_firm",
    "recall_reason": "reason_for_recall", "classification": "classification",
}
# Explicit label support is a conservative gate, not a general FDA interpreter.
_LABELS = {
    "lot": r"lot(?:\s+(?:number|no\.?))?",
    "batch": r"batch(?:\s+(?:number|no\.?))?",
    "upc": r"upc(?:\s+code)?",
    "sku": r"sku",
    "expiry_date": r"(?:exp(?:\.|iry|iration)?(?:\s+date)?|expires)",
    "use_by_date": r"use[\s-]+by",
    "best_by_date": r"best[\s-]+by",
    "date_range": r"date[\s-]+range",
}
_SCOPE_LABEL = re.compile(
    r"\b(?:lot(?:\s+(?:number|no\.?))?|batch(?:\s+(?:number|no\.?))?|"
    r"upc(?:\s+code)?|sku|exp(?:\.|iry|iration)?(?:\s+date)?|expires|"
    r"best[\s-]+by|use[\s-]+by|sell[\s-]+by)\s*[:#]?\s*",
    re.IGNORECASE,
)
_DATE_SHAPE = re.compile(r"(?<!\w)\d{1,4}[-/]\d{1,2}[-/]\d{2,4}(?!\w)")
_EXPLICIT_CODE = re.compile(
    r"\b(?P<kind>lot(?:\s+(?:number|no\.?))?|batch(?:\s+(?:number|no\.?))?)"
    r"\s*[:#]?\s*(?P<value>[^\s,;\"]+)", re.IGNORECASE,
)
_PRODUCT_UPC = re.compile(r"\bUPC(?:\s+Code)?\s*[:#]?\s*(\d(?:[\d -]*\d)?)\b", re.I)
_PRODUCT_ITEM = re.compile(r"\bItem\s*#\s*(\d+)\b", re.I)


def require_labeled_product_identifiers(record: dict, identifiers: list,
                                        recall_number: str) -> None:
    """Require exact labeled UPC/item literals, without inferring package links."""
    product = record.get("product_description") or ""
    evidence_id = f"EV-{recall_number}-PRODUCT_DESCRIPTION"
    for kind, pattern in (("upc", _PRODUCT_UPC), ("other", _PRODUCT_ITEM)):
        for match in pattern.finditer(product):
            value = match.group(1)
            if not any(i.kind == kind and i.value == value
                       and evidence_id in i.evidence_ids for i in identifiers):
                raise ContractError(f"Explicit product {kind} {value!r} is missing from identifiers")


def _ambiguous_lot_segment(text: str, value: str) -> str | None:
    """Conservatively flag a lot span with an unexplained second code/date.

    Labels for known neighboring fields end a span. BC is not treated as a
    trusted barcode/batch label; its meaning and the preceding boundary are
    unresolved. This is a narrow safety gate, not a full code parser.
    """
    labels = list(_SCOPE_LABEL.finditer(text))
    for index, label in enumerate(labels):
        if not re.fullmatch(_LABELS["lot"], label.group().strip(" :#\t\r\n"), re.I):
            continue
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        segment = text[label.end():end]
        if value not in segment:
            continue
        dates = list(_DATE_SHAPE.finditer(segment))
        has_unlabeled_date_neighbor = any(
            segment[:date.start()].strip(" \t\r\n\";,.()") or
            segment[date.end():].strip(" \t\r\n\";,.()")
            for date in dates
        )
        if re.search(r"\bBC\b", segment, re.I) or has_unlabeled_date_neighbor or len(dates) > 1:
            return segment.strip()
    return None


def _unavailable(text: str | None) -> bool:
    return text is None or text.strip().casefold() in {"", "unknown", "no codes", "no code", "n/a"}


def validate_result(payload: object, source: Source, *, recall_number: str,
                    event_id: str, snapshot_id: str,
                    approved_lots: tuple[HumanLotApproval, ...] = ()) -> A1Result:
    """Validate against caller-selected IDs, never the result's own selection.

    Raises Pydantic ValidationError for structure/types and ContractError for
    source/policy failures. No fallback success or automatic correction occurs.
    Call on the final payload before handoff; model construction alone checks
    only shape. Unknown meanings remain explicit uncertainties for human review.
    """
    result = A1Result.model_validate(payload)
    ctx = dict(recall_number=recall_number, event_id=event_id, snapshot_id=snapshot_id)
    if (result.facts.recall_number, result.event_id, result.snapshot_id) != (
        recall_number, event_id, snapshot_id
    ):
        raise ContractError("Result differs from caller-selected recall/event/snapshot")
    try:
        record = source.lookup(**ctx)
        # Lookup can discover events; validation must require the exact event.
        if record["event_id"] != event_id:
            raise ContractError("Selected event is not the exact source event")
        fields = result.source_fields.model_dump()
        expected_ids = set()
        for name, field in fields.items():
            if field["original_text"] != record.get(name):
                raise ContractError(f"Source text mismatch: {name}")
            if name in FIELDS:
                if field["evidence_id"] is None or field["point_id"] is None:
                    raise ContractError(f"Missing packaged passage provenance: {name}")
                validate_citation(source, Evidence(field_name=name, **ctx, **field), **ctx)
                expected_ids.add(field["evidence_id"])
            elif field["evidence_id"] is not None or field["point_id"] is not None:
                raise ContractError(f"Metadata cannot have invented passage IDs: {name}")
        facts = result.facts
        for output, canonical in _FACT_FIELDS.items():
            text = record.get(canonical)
            expected = None if _unavailable(text) else text
            if getattr(facts, output) != expected:
                raise ContractError(f"Fact differs from canonical source: {output}")
        if set(facts.evidence_ids) != expected_ids:
            raise ContractError("Facts evidence list must equal canonical source-field evidence IDs")

        review_required = not facts.identifiers or _unavailable(record.get("code_info"))
        review_required |= any(_unavailable(record.get(f)) for f in _FACT_FIELDS.values())
        for identifier in facts.identifiers:
            if not set(identifier.evidence_ids) <= set(facts.evidence_ids):
                raise ContractError("Identifier evidence missing from facts evidence list")
            passages = validate_literal_identifier(
                source, identifier.value, identifier.evidence_ids, **ctx
            )
            if any(_unavailable(p.original_text) for p in passages):
                raise ContractError("Unknown/empty source cannot be an identifier")
            if identifier.scope_note not in {p.original_text for p in passages}:
                raise ContractError("Scope note must preserve a cited source field exactly")
            ambiguous = [
                _ambiguous_lot_segment(p.original_text, identifier.value)
                for p in passages if p.field_name == "code_info"
            ]
            if identifier.kind == "lot" and any(span is not None for span in ambiguous):
                reviewed = any(
                    isinstance(a, HumanLotApproval)
                    and (a.recall_number, a.event_id, a.snapshot_id) ==
                    (recall_number, event_id, snapshot_id)
                    and a.value == identifier.value
                    and a.reviewer.strip()
                    and any(p.field_name == "code_info" and p.evidence_id == a.evidence_id
                            and p.original_text == a.original_text for p in passages)
                    and a.value in ambiguous
                    for a in approved_lots
                )
                if not reviewed:
                    raise ContractError("Ambiguous combined code cannot be a confirmed lot; use other and uncertainty",
                                        rule="ambiguous_lot_requires_review")
            if identifier.kind == "other" and any(
                span is not None and identifier.value != span for span in ambiguous
            ):
                raise ContractError("Unresolved combined code must preserve the complete literal span",
                                    rule="ambiguous_span_incomplete")
            if identifier.kind == "other":
                review_required = True
            else:
                # Label matching ignores label case only; identifier values stay literal.
                pattern = (r"\b(?i:" + _LABELS[identifier.kind] + r")\s*[:#]?\s*"
                           + re.escape(identifier.value) + r"(?![\w/\-]|\.\w)")
                if not any(re.search(pattern, p.original_text) for p in passages):
                    raise ContractError("Identifier kind lacks explicit source-label support; use other and uncertainty",
                                        rule="identifier_label_unsupported")
        # A valid citation on one identifier cannot conceal a second, clearly
        # labeled lot or batch in the same code field. Ambiguous combined spans
        # retain the complete phrase under the existing review policy.
        for match in _EXPLICIT_CODE.finditer(record.get("code_info") or ""):
            kind = "lot" if match.group("kind").lower().startswith("lot") else "batch"
            value = match.group("value")
            ambiguous_span = (
                _ambiguous_lot_segment(record["code_info"], value)
                if kind == "lot" else None
            )
            if ambiguous_span is not None:
                covered = any(
                    i.value == ambiguous_span and i.kind in ("other", "lot")
                    and f"EV-{recall_number}-CODE_INFO" in i.evidence_ids
                    for i in facts.identifiers
                )
            else:
                covered = any(
                    i.kind == kind and i.value == value
                    and f"EV-{recall_number}-CODE_INFO" in i.evidence_ids
                    for i in facts.identifiers
                )
            if not covered:
                raise ContractError(f"Explicit {kind} in source is missing from identifiers",
                                    rule="required_identifier_missing")
        require_labeled_product_identifiers(record, facts.identifiers, recall_number)
        if review_required and not facts.uncertainties:
            raise ContractError("Missing or unresolved facts/identifier meanings require an uncertainty",
                                rule="uncertainty_required")
    except (SourceError, CitationError) as exc:
        raise ContractError(str(exc)) from exc
    return result
