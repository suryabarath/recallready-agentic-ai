"""Explicit caller-supplied human reviews; never model prompt material."""
from copy import deepcopy
import json
from pathlib import Path

from models import Nonblank, StrictModel
from source import Source
from citations import validate_literal_identifier
from validation import ContractError, HumanLotApproval, _ambiguous_lot_segment


class LotReview(StrictModel):
    recall_number: Nonblank
    event_id: Nonblank
    snapshot_id: Nonblank
    evidence_id: Nonblank
    original_text: Nonblank
    value: Nonblank
    reviewer: Nonblank


class ReviewFile(StrictModel):
    approved_lots: list[LotReview]


def load_reviews(path: Path) -> tuple[HumanLotApproval, ...]:
    parsed = ReviewFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return tuple(HumanLotApproval(**r.model_dump()) for r in parsed.approved_lots)


def check_reviews(approvals: tuple[HumanLotApproval, ...], source: Source, **ctx) -> None:
    """Reject stale/cross-case reviews before any paid request.

    Provenance checks do not authenticate the reviewer. The local caller owns
    the review file and is responsible for supplying only authorized decisions.
    """
    seen = set()
    for approval in approvals:
        if not isinstance(approval, HumanLotApproval):
            raise ContractError("Expected an explicit human lot approval")
        # Apply the same strict string/extra-field validation to Python callers.
        LotReview.model_validate(vars(approval))
        if (approval.recall_number, approval.event_id, approval.snapshot_id) != (
            ctx['recall_number'], ctx['event_id'], ctx['snapshot_id']
        ):
            raise ContractError("Human review differs from caller-selected context")
        passage = source.resolve(approval.evidence_id, **ctx)
        if passage.field_name != 'code_info' or passage.original_text != approval.original_text:
            raise ContractError("Human review source text or field mismatch")
        validate_literal_identifier(source, approval.value, [approval.evidence_id], **ctx)
        if _ambiguous_lot_segment(passage.original_text, approval.value) != approval.value:
            raise ContractError("Human review must approve the complete ambiguous lot span")
        key = (approval.evidence_id, approval.value)
        if key in seen:
            raise ContractError("Duplicate human lot approval")
        seen.add(key)


def apply_reviews(payload: dict, approvals: tuple[HumanLotApproval, ...]) -> dict:
    """Promote an already proposed exact full phrase, never insert missing codes.

    Caller must check review context first and validate the final result after.
    Preserve model observations, explicitly labeled as preceding human review.
    """
    result = deepcopy(payload)
    notes = []
    for approval in approvals:
        matches = [i for i in result['facts']['identifiers']
                   if i['value'] == approval.value
                   and approval.evidence_id in i['evidence_ids']
                   and i['kind'] in ('other', 'lot')]
        if len(matches) != 1:
            raise ContractError("Human review needs exactly one matching model phrase and citation")
        identifier = matches[0]
        previous_kind = identifier['kind']
        identifier['kind'] = 'lot'
        notes.append(f"Human review by {approval.reviewer}: {approval.value!r} is approved "
                     f"as one lot (model kind before review: {previous_kind}). This approval "
                     "does not establish a separate date or code meaning.")
    if notes:
        result['facts']['uncertainties'] = [
            "Model observation before human review: " + text
            for text in result['facts']['uncertainties']
        ] + notes
    return result
