"""Provisional Group C relationship envelope; A/B contract remains unchanged."""

import re
from typing import Literal

from pydantic import Field

from citations import CitationError, validate_citation, validate_literal_identifier
from models import A1Result, Nonblank, StrictModel
from source import Evidence, FIELDS, GROUP_C, Source, SourceError
from validation import ContractError, _unavailable, require_labeled_product_identifiers


class RelationPart(StrictModel):
    role: Literal["lot", "code", "date", "state", "package", "range_start", "range_end"]
    value: Nonblank


class SourceRelation(StrictModel):
    kind: Literal["lot_date", "state_code_date", "code_date", "date_range", "package_code_date"]
    evidence_id: Nonblank
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    source_span: Nonblank
    parts: list[RelationPart] = Field(min_length=2)


class GroupCResult(StrictModel):
    contract_version: Literal["0.2-group-c-provisional"]
    base: A1Result
    relations: list[SourceRelation]


_ROLES = {
    "lot_date": {"lot", "date"},
    "state_code_date": {"state", "code", "date"},
    "code_date": {"code", "date"},
    "date_range": {"range_start", "range_end"},
    "package_code_date": {"package", "code", "date"},
}
_KEY_ROLES = {
    "lot_date": ("lot", "date"),
    "state_code_date": ("state", "code", "date"),
    "code_date": ("code", "date"),
    "date_range": ("range_start", "range_end"),
    "package_code_date": ("package", "code", "date"),
}
_LABELED_LOT_DATE = re.compile(
    r"\bLOT\s+(?P<lot>[A-Za-z0-9]+)\s+EXP\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\b",
    re.IGNORECASE,
)


def _required_pair_keys(recall_number: str, text: str) -> set[tuple]:
    """Literal, snapshot-specific syntax checks; no date normalization."""
    pairs = set()
    if recall_number == "H-1388-2026":
        for match in _LABELED_LOT_DATE.finditer(text):
            pairs.add(("lot_date", match.group("lot"), match.group("date")))
    elif recall_number == "H-1361-2026":
        sections = list(re.finditer(r"\b(Illinois|Texas):\s*", text))
        for index, section in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            for match in re.finditer(r"\b(TF(?:IC|TX)[A-Z0-9]+),\s*(\d{1,2}/\d{1,2}/\d{4})", text[section.end():end]):
                pairs.add(("state_code_date", section.group(1), match.group(1), match.group(2)))
    elif recall_number == "H-1396-2026":
        for match in re.finditer(r"\b(L\d{4}C)\s+(SEP\s+\d{1,2}\s+\d{4})\b", text):
            pairs.add(("code_date", match.group(1), match.group(2)))
    elif recall_number == "F-0536-2021":
        for match in re.finditer(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+thru\s+Use By:\s+(\d{1,2}/\d{1,2}/\d{4})", text):
            pairs.add(("date_range", match.group(1), match.group(2)))
    elif recall_number == "F-2413-2017":
        for match in re.finditer(r"\b(\d{4})\s*/\s*(\d{1,2}/\d{1,2}/(?:\d\s+\d{3}|\d{4}))", text):
            pairs.add(("lot_date", match.group(1), match.group(2)))
    return pairs


def validate_group_c_result(payload: object, source: Source, *, recall_number: str,
                            event_id: str, snapshot_id: str) -> GroupCResult:
    """Validate exact provenance and literal co-occurrence; no semantic inference.

    Offsets bind a relationship to one exact passage span. This cannot prove
    that a model interpreted an ambiguous span correctly, so human review is
    still required before downstream use.
    """
    result = GroupCResult.model_validate(payload)
    if recall_number not in GROUP_C:
        raise ContractError("Group C relationship envelope requires a Group C recall")
    ctx = dict(recall_number=recall_number, event_id=event_id, snapshot_id=snapshot_id)
    base = result.base
    try:
        record = source.lookup(**ctx)
        if (base.facts.recall_number, base.event_id, base.snapshot_id) != (
            recall_number, event_id, snapshot_id
        ):
            raise ContractError("Base selection differs from caller context")
        fields = base.source_fields.model_dump()
        for field, item in fields.items():
            if item["original_text"] != record.get(field):
                raise ContractError("Base source text differs from canonical record")
            if field in FIELDS:
                validate_citation(source, Evidence(field_name=field, **ctx, **item), **ctx)
            elif item["evidence_id"] is not None or item["point_id"] is not None:
                raise ContractError("Metadata cannot cite invented passage IDs")
        if set(base.facts.evidence_ids) != {
            f"EV-{recall_number}-{field.upper()}" for field in FIELDS
        }:
            raise ContractError("Base evidence list differs from canonical passages")
        for fact, field in (("product_name", "product_description"),
                            ("recalling_firm", "recalling_firm"),
                            ("recall_reason", "reason_for_recall"),
                            ("classification", "classification")):
            if getattr(base.facts, fact) != record.get(field):
                raise ContractError("Base fact differs from canonical record")
        for identifier in base.facts.identifiers:
            if not set(identifier.evidence_ids) <= set(base.facts.evidence_ids):
                raise ContractError("Base identifier cites unrelated evidence")
            validate_literal_identifier(source, identifier.value, identifier.evidence_ids, **ctx)
            if any(_unavailable(source.resolve(eid, **ctx).original_text)
                   for eid in identifier.evidence_ids):
                raise ContractError("Unknown source text cannot be an identifier")
            if recall_number == "H-1361-2026" and identifier.kind == "lot":
                raise ContractError("State-specific source codes are not explicitly labeled lots")
            if recall_number == "H-1396-2026" and identifier.kind == "best_by_date":
                label = re.compile(
                    r"\bBEST\s+if\s+Used\s+By:\s*" + re.escape(identifier.value)
                    + r"(?![\w/\-])", re.IGNORECASE,
                )
                if not any(label.search(source.resolve(eid, **ctx).original_text)
                           for eid in identifier.evidence_ids):
                    raise ContractError("Best-by date lacks an explicit adjacent source label")
            if identifier.scope_note not in {
                source.resolve(eid, **ctx).original_text for eid in identifier.evidence_ids
            }:
                raise ContractError("Base identifier scope differs from source text")
        require_labeled_product_identifiers(record, base.facts.identifiers, recall_number)
    except (SourceError, CitationError) as exc:
        raise ContractError(str(exc)) from exc
    if not base.facts.uncertainties:
        raise ContractError("Group C requires explicit human-review uncertainty")
    if not result.relations and recall_number != "F-1420-2012":
        raise ContractError("Group C relationship information requires review")
    seen = set()
    for relation in result.relations:
        try:
            passage = source.resolve(relation.evidence_id, **ctx)
        except SourceError as exc:
            raise ContractError(str(exc)) from exc
        if passage.field_name not in ("code_info", "product_description"):
            raise ContractError("Relationship requires a product or code passage")
        if relation.end > len(passage.original_text) or relation.start >= relation.end:
            raise ContractError("Relationship offsets exceed source text")
        if passage.original_text[relation.start:relation.end] != relation.source_span:
            raise ContractError("Relationship span differs from exact source text")
        if {part.role for part in relation.parts} != _ROLES[relation.kind]:
            raise ContractError("Relationship roles do not match its kind")
        if len({part.role for part in relation.parts}) != len(relation.parts):
            raise ContractError("Duplicate relationship role")
        if relation.kind == "state_code_date":
            headings = list(re.finditer(r"\b(Illinois|Texas):", passage.original_text))
            preceding = [heading for heading in headings if heading.end() <= relation.start]
            state = next(part.value for part in relation.parts if part.role == "state")
            if not preceding or preceding[-1].group(1) != state:
                raise ContractError("State does not match the source section heading")
        key = (relation.evidence_id, relation.start, relation.end, relation.kind)
        if key in seen:
            raise ContractError("Duplicate relationship")
        seen.add(key)
        for part in relation.parts:
            if part.role != "state" and part.value not in relation.source_span:
                raise ContractError("Relationship value is outside its source span")
            try:
                validate_literal_identifier(source, part.value, [relation.evidence_id], **ctx)
            except CitationError as exc:
                raise ContractError(str(exc)) from exc
            if _unavailable(passage.original_text) or _unavailable(part.value):
                raise ContractError("Unknown source text cannot support a relationship")
    # Every selected challenge syntax must preserve all source pairs, including
    # its state and the unusual split-year spelling. Extra pairings are rejected.
    code_text = record.get("code_info") or ""
    for match in _LABELED_LOT_DATE.finditer(code_text):
        expected = (match.start(), match.end(), match.group("lot"), match.group("date"))
        if not any(
            relation.kind == "lot_date"
            and relation.evidence_id == f"EV-{recall_number}-CODE_INFO"
            and (relation.start, relation.end) == expected[:2]
            and {(part.role, part.value) for part in relation.parts} == {
                ("lot", expected[2]), ("date", expected[3])
            }
            for relation in result.relations
        ):
            raise ContractError("Explicit lot/date pair is missing or altered")
    required = _required_pair_keys(recall_number, code_text)
    observed = {
        (relation.kind, *(next(part.value for part in relation.parts if part.role == role)
                          for role in _KEY_ROLES[relation.kind]))
        for relation in result.relations
    }
    if observed != required:
        raise ContractError("Group C relationships omit or alter source pairings")
    return result
