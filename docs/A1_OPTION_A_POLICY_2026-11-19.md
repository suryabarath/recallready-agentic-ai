# A1 ambiguous-code policy — 19 November 2026

Status: Option A approved by Member 1. This document records the implemented
Group A offline gate, not a claim that all FDA identifier boundaries can be
inferred automatically.

## Decision and resulting behavior

When a lot span includes an unexplained `BC` marker or an unlabeled adjacent
date-like value, the span remains unresolved. The A1 interpreter is instructed
to propose the complete literal phrase as `other` with an uncertainty. The
validator rejects a `lot` claim from that ambiguous span, even if a substring
or the full phrase appears literally after the Lot label. An unresolved result
must not be used downstream as a confirmed lot or exact inventory match.

The same rule applies to a lot span with two date-like parts lacking separate
labels. A distinct `EXP`, `BEST BY`, `SELL BY`, `UPC`, `SKU`, or next `LOT` label
ends the preceding span. Clear values remain eligible for the existing exact
literal and citation checks. The original FDA text, snapshot, evidence IDs and
starter ZIP are unchanged. The approved Pydantic output shape is unchanged.

Examples from the development set:

| Source `code_info` | Allowed unresolved representation | Confirmed-lot claim rejected |
| --- | --- | --- |
| `LOT # 06-04-24 08/04/2024` | `other`: `06-04-24 08/04/2024`; uncertainty | `lot`: full phrase or `06-04-24` |
| `Lot: 04162026 BC 6937218914734` | `other`: `04162026 BC 6937218914734`; uncertainty | `lot`: full phrase or `04162026` |

The `BC` suffix is not asserted to be a UPC. The second date-like part is not
asserted to be an expiry. Both remain visible in exact source evidence. The
earlier F-0705-2025 development review candidate proposed a split lot and
`other` code; it has been revised as a candidate to reflect the approved
conservative policy. It was never a human-approved gold label.

## Verification and limits

`.venv/bin/python -m pytest -q`: **490 passed in 1.04 seconds**. New negative
tests cover whole and partial ambiguous lots, partial `other` spans, BC-as-UPC, and SDK handling of a
semantic failure without a paid repair. Synthetic positive tests confirm that
distinctly labeled lot/expiry pairs and a single date-shaped lot remain valid;
synthetic negative tests cover an unlabeled neighboring date and BC marker.
All previous provenance, literal, leading-zero and shape checks remain.

The five saved live outputs were revalidated offline against the updated rule:
three passed; F-1472-2024 and F-0705-2025 now require review. These were
historical outputs generated before the policy change. The first live result
was not saved as a separate artifact and was not revalidated here. No new
OpenAI call was made, so the six-run usage total remains a historical measure,
not a result for the new policy. The starter ZIP SHA-256 remains
`b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.

The boundary check is a conservative pattern-based gate. It does not establish
all lot/date/package associations or detect every ambiguous phrase. For spans
the gate recognizes, `other` must include the entire literal span; human review
remains required. No Group B/C, inventory, held-out labels,
Qdrant, or A2 routing were used. Package-unit ambiguity identified in the
earlier live review remains open.

## Data-format role approved by Member 1

CSV may be used as a supplementary review/export format. It is not the
authoritative evidence source. The frozen FDA JSON and original starter ZIP
remain preserved; SQLite is the planned exact runtime store under v4.2. No
new CSV layout/export or SQLite migration was implemented in this gate.
Spreadsheet imports must treat codes and IDs as text, especially leading-zero
lots; any future review export should carry source IDs and review status and
be round-tripped against canonical source text before use.

Next gate: human review of the two rejected historical interpretations and
agreement on a review/export layout if CSV is needed. Any paid rerun should be
separately scoped and recorded; do not overwrite historical observations.

Subsequent review: Member 1 approved the full F-0705-2025 phrase as one lot.
See `A1_HUMAN_LOT_REVIEW_2026-11-19.md`. Validation accepts that exact
combination only when a trusted caller passes the corresponding
`HumanLotApproval`; the default Option A check is unchanged. F-1472-2024
remains unresolved. The later offline suite passed 491 tests in 1.02 seconds.

## Self-report

Verified: offline suite, saved-result revalidation, unchanged starter hash.
Not verified: new live model behavior, full-dataset generality, human approval
of identifier semantics, or actual billing. No skipped tests, mocks of source
validation, or schema changes. Confidence: high for the specified conservative
gate; remaining risk is ambiguous patterns outside its limited recognition.
