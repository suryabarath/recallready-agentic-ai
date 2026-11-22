# Human lot review — 19 November 2026

Reviewer: Member 1 (project architect), explicitly approved in conversation.
Recall: `F-0705-2025`; event: `96464`;
snapshot: `FDA-FOOD-2026-10-23-USER-SNAPSHOT`.
Evidence ID: `EV-F-0705-2025-CODE_INFO`.
Exact source text: `Lot: 04162026 BC 6937218914734`.

Decision: treat `04162026 BC 6937218914734` as **one confirmed lot
identifier** for this recall. This is a human interpretation of the frozen
source, not an assertion that `BC` means barcode, batch code, or UPC. It does
not extend to another recall, snapshot, event, evidence passage, or substring.

The general Option A rule remains active. A trusted caller may pass a
`HumanLotApproval` with this exact context to `validate_result`; without it,
the combined phrase is rejected as a confirmed lot. The historical live model
response classified this entire phrase as a lot before this review. This
record does not rerun the model or revise that historical output.

Workflow update: `docs/a1_member1_lot_approval.json` now records this decision
for explicit CLI use with `--human-review-file`. See
`A1_REVIEW_WORKFLOW_2026-11-19.md` for behavior, tests and a separately saved
offline review of the historical output. No new inference was performed.

For `F-1472-2024`, Member 1 subsequently approved preserving the complete
literal phrase `06-04-24 08/04/2024` from source text
`LOT # 06-04-24 08/04/2024` (event `94806`, evidence
`EV-F-1472-2024-CODE_INFO`). Its representation remains `other` with an
uncertainty. This approval does **not** classify the entire phrase as a confirmed
lot or classify `08/04/2024` as an expiry date. No separate override is needed:
the existing Option A example and validator already preserve the whole phrase.
Additional official manufacturer context, if found, should be recorded
separately with source links and snapshot information.
