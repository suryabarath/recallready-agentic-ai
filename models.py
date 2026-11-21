"""M1-approved Task 02B shape. Use validate_result for source validation."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Expected a nonblank string")
    return value  # Never normalize source strings.


def _unique(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate evidence IDs")
    return values


Nonblank = Annotated[str, Field(min_length=1, pattern=r"\S"), AfterValidator(_nonblank)]
EvidenceIDs = Annotated[
    list[Nonblank], Field(json_schema_extra={"uniqueItems": True}), AfterValidator(_unique)
]
IdentifierKind = Literal[
    "lot", "batch", "upc", "sku", "expiry_date", "use_by_date",
    "best_by_date", "date_range", "other",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class Identifier(StrictModel):
    kind: IdentifierKind
    value: Nonblank
    scope_note: str | None
    evidence_ids: Annotated[EvidenceIDs, Field(min_length=1)]


class Facts(StrictModel):
    recall_number: Nonblank
    product_name: str | None
    recalling_firm: str | None
    recall_reason: str | None
    classification: str | None
    identifiers: list[Identifier]
    uncertainties: list[Nonblank]
    evidence_ids: EvidenceIDs


class SourceField(StrictModel):
    original_text: str | None
    evidence_id: Nonblank | None
    point_id: Nonblank | None

    @model_validator(mode="after")
    def paired_references(self) -> Self:
        if (self.evidence_id is None) != (self.point_id is None):
            raise ValueError("Evidence and point IDs must both be present or both null")
        if self.point_id is not None:
            UUID(self.point_id)  # Validate without converting or rewriting the string.
        if self.original_text is None and self.evidence_id is not None:
            raise ValueError("Missing source text cannot carry passage IDs")
        return self


class SourceFields(StrictModel):
    product_description: SourceField
    code_info: SourceField
    reason_for_recall: SourceField
    distribution_pattern: SourceField
    recalling_firm: SourceField
    classification: SourceField


class A1Result(StrictModel):
    # Retain the exact version literal approved in the proposal and examples.
    contract_version: Literal["0.1-proposed"]
    snapshot_id: Nonblank
    event_id: Nonblank
    facts: Facts
    source_fields: SourceFields
