# A1 explicit human-review workflow — 19 November 2026

## Implemented gate

The caller can now pass `--human-review-file` to the single-recall CLI. The
file is parsed with strict Pydantic types and checked against the selected
source before a budget reservation or paid request. Stale snapshots, other
recalls/events, altered source text, invented references, partial approved
values and blank reviewers fail preflight. Duplicate approvals fail as well.

`reviews.py` owns loading, source checking and local review application.
`docs/a1_member1_lot_approval.json` encodes Member 1's explicit decision for
F-0705-2025, event 96464, snapshot FDA-FOOD-2026-10-23-USER-SNAPSHOT.
It is an approved development decision, not independent evaluation ground
truth. No review examples or human decisions are sent to OpenAI.

After model generation, a matching complete proposed phrase with its exact
evidence citation may be promoted from `other` to `lot`, or retained as `lot`,
according to the explicit review. Missing/partial phrases and unsupported
identifier kinds are not filled or repaired. Normal final source validation
still runs with the scoped approval. API usage is accounted even if this
post-generation check fails; semantic failures do not trigger another attempt.

All original model uncertainty strings remain, prefixed as observations made
before human review. A separate note identifies the reviewer, approved phrase,
and original model kind. Thus human-assisted output is distinguishable from
unreviewed model extraction without changing the approved output schema. A
downstream consumer must inspect the review note; a typed `lot` does not imply
the model independently established its meaning.

F-1472-2024 retains its entire phrase as `other` and an uncertainty. No lot
approval file was created for it, and no expiry date is inferred. Omitting the
CLI review flag keeps the existing Option A behavior.

## Commands for later use

These commands are provided for reproducibility; they were not executed live
in this increment. Load credentials privately in the shell first. Keep the
same ledger to preserve the USD 1.00 local estimated budget history.

```bash
.venv/bin/python interpreter.py --recall F-0705-2025 --allow-paid-call --budget-usd 1.00 --ledger runtime/a1_usage.sqlite --human-review-file docs/a1_member1_lot_approval.json
.venv/bin/python interpreter.py --recall F-1472-2024 --allow-paid-call --budget-usd 1.00 --ledger runtime/a1_usage.sqlite
```

An invalid review for the selected case is rejected, rather than silently
ignored. Select only a review file whose entries all belong to that case.
Review-file integrity checks do not authenticate the reviewer or verify the
manufacturer's meaning. The local user/calling application is responsible for
authorizing and protecting these records. This is not a deployed review UI,
access-control system or electronic-signature service.

## Executed verification

- `.venv/bin/python -m pytest -q`: **507 passed in 1.15 seconds**.
- Sixteen new offline SDK/CLI checks cover review application, context/source
  mismatches, partial approvals, missing/model-altered values and malformed
  review files. The existing tests retain default ambiguity enforcement and
  F-1472-2024 whole-phrase preservation. Fake HTTP responses test application
  behavior, not live model accuracy; real source/citation validation is used.
- A separate historical F-0705-2025 result was reviewed offline and validated:
  `runtime/group_a_live_uy5d58w2/F-0705-2025.human_reviewed.json`. Its metadata
  labels it as human review of a historical output, not a new inference. The
  original artifact was preserved, and source text/citation remained exact.
- No new OpenAI request, model change, collection write, source-store migration,
  CSV export, Group B/C inference, inventory or held-out-label access occurred.

The full 18-case development goal and the proposed 48-case capstone evaluation
remain later gates. This increment finishes review wiring for the current six
Group A recalls only. Wider source access and reference-answer review should be
separately scoped before expanding. Citation passes must not be reported as
semantic accuracy, and reviewed development decisions must not be scored as
independent model successes.

## Next gate and limits

Inspect the reviewed historical output, then approve a targeted live rerun if
needed. Both the new prompt's live behavior and review application with a newly
generated response remain unverified. General identifier-boundary recognition
and package interpretation remain limited, as recorded in the Option A review.

Subsequent verification: the authorized two-case live rerun succeeded. See
`A1_REVIEW_LIVE_RESULTS_2026-11-19.md` for final values, review distinction,
token usage and saved artifacts. Earlier verification statements above describe
the implementation gate before those calls.

## Self-report

Verified offline SDK/CLI tests and one source-validated review of historical
output. No skipped tests, stubs replacing source checks, output hardcoding, or
schema/dependency changes. The saved approval is explicit user review data;
generated values are still required to appear in canonical source evidence.
Confidence: high for this scoped workflow, limited for new live model behavior
and broad FDA semantic generality.
