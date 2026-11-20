# A1 Group C offline source and citation gate — 19 November 2026

Group C comprises the six challenge recalls selected in the immutable A1
starter ZIP: `H-1388-2026`, `H-1361-2026`, `H-1396-2026`, `F-1420-2012`,
`F-0536-2021`, and `F-2413-2017`. The source reader now selects all 18
development recalls and their 72 passages by exact recall, event, and snapshot.

The Group C tests compare all six original FDA records and all 24 passage
objects with the ZIP members. They reject invented or truncated literal codes,
altered evidence, wrong events, snapshots, and cross-recall references. They
also preserve the original relationship text without repairing unusual values:
the Illinois/Texas codes, two lot/expiry pairs, `Unknown`, the use-by range,
and `1/10/2 018` inside the multi-lot source field.

Verification command: `.venv/bin/python -m pytest -q` — **634 passed in
1.17 seconds** after the source/citation expansion. The starter ZIP was read
directly, without extraction. No paid model calls were made for Group C.

The current A1 contract represents each identifier with a literal value,
citations, and one whole-field `scope_note`. It does not structurally encode
lot-to-expiry, lot-to-state, date-range, or package associations. In addition,
the current validator's explicit lot/batch completeness check is tailored to
plain labels and is not a general parser for the Group C patterns. Therefore
the Group C source gate is ready for review, but the interpreter CLI remains
limited to Group A+B. A contract decision and targeted semantic tests are
required before live Group C inference or downstream use.

These are development cases, not held-out accuracy measurements. No inventory
or held-out labels were accessed, and no proposed starter output schema or
v4.2 architecture was modified.

## Subsequent Phase C contract work

With Member 1's instruction to proceed, `group_c_contract.py` now defines a
separate provisional `0.2-group-c-provisional` envelope around the existing
`0.1-proposed` A1 result. Each relation records its type, exact evidence ID,
source character offsets, unchanged source span, and typed literal components.
For a state/code/date relation, the state comes from the enclosing source
heading and the span contains the local code/date pair.
This leaves Group A/B output and the starter's proposed schema intact.

The new validator checks caller-selected recall/event/snapshot, every base
source field and citation, exact relation offsets and component literals. For
the repeated `LOT ... EXP ...` syntax, it requires both source pairs and rejects
omission or swapped dates. Offline examples cover six Group C envelopes,
including `Unknown` as an unresolved case; adversarial tests cover forged
spans, values, roles and cross-recall evidence.

These examples are development fixtures, not independently approved semantic
labels. The general relation check establishes literal co-occurrence in a
source span, not the full meaning of every state, package or date association.
The `F-2413-2017` malformed date and cross-field package mapping still require
explicit human interpretation. Group C remains excluded from the paid A1
interpreter until a relationship-aware model output and review process exist.

## Offline Group C model adapter

`group_c_interpreter.py` now asks for identifiers, uncertainties and relationship
spans in a strict intermediate response. It builds event, snapshot, metadata,
four source fields, point IDs and scope notes locally from the frozen ZIP, then
validates the provisional result. One structural repair is allowed; semantic
validation failures stop without retry. The existing persistent USD ledger and
bounded request accounting are reused. The adapter has no paid CLI entry point.

The SDK tests use an in-process fake HTTP transport. They cover one assembled
result for each challenge recall, missing or swapped lot/date pairs, a forged
cross-recall evidence ID, an invented `Unknown` identifier, one structural
repair and timeout reservation retention. These tests demonstrate request and
validation behavior, not model extraction quality. Expanded development
examples now cover all seven state/code/date pairs, both `L.../SEP...` pairs,
and all seven multi-lot/code-date pairs. The validator requires those complete
mappings and rejects extra swapped pairings while preserving the literal
malformed date `1/10/2 018`. These syntax checks are not independent gold labels.

The `F-2413-2017` product field lists two sizes and UPCs, while its code field
lists lots and dates without an explicit package-to-lot assignment. Assigning
those lots to either package would be an inference; it remains unresolved.
Human review is still required before live testing or downstream integration.

## First controlled live pilot — unresolved

Two paid attempts were made for `H-1388-2026` using the same existing ledger,
`gpt-6-luna`, low reasoning, no SDK retries, and a local USD 0.05 cap. Neither
produced an accepted Group C result.

- Ledger call 15: 1,036 input and 548 output tokens; estimated USD 0.000378.
  The response failed semantic validation. The first adapter version did not
  expose the specific validation error, and raw model output was not retained.
- Between attempts, the adapter was changed to calculate source offsets
  locally from the model's exact quoted span, removing model-generated offsets.
  The full offline suite passed: 669 tests.
- Ledger call 16: 1,017 input and 396 output tokens; estimated USD 0.000300.
  Exact error: `Group C requires explicit human-review uncertainty`. The model
  did not supply a nonempty uncertainty list. No accepted output was returned.

Combined estimated usage is USD 0.000678, not a verified invoice amount. Work
stopped after the second failed attempt under the project working agreement.
The best current hypothesis is a prompt/contract mismatch: the validator
requires an uncertainty on every Group C result, while the prompt only asks
for one when meaning or associations need human review. A future change should
make that requirement explicit or add a trusted, clearly labeled human-review
status outside the model response. The first response's exact failure remains
unknown because the proposal was not saved. No Group C live accuracy claim is
supported by these attempts.

## Focused correction and controlled pilot

The model prompt now explicitly requires a human-review uncertainty on every
Group C response. The adapter can write a caller-selected, owner-only local
diagnostic file containing a rejected parsed proposal, response ID and exact
validation reason; it does not write a key or full request. Offline tests check
the prompt, file permissions, content, rejection behavior and successful paths.
The full suite passed **669 tests** before the next live call.

One additional paid attempt for `H-1388-2026` succeeded (ledger call 17).
The model returned `00000ZRAA1` paired with `08/15/2026` and `00000ZUAD2`
paired with `08/18/2026`; exact source spans were character offsets 0–30 and
31–61 in `code_info`. The result cited matching FDA evidence, kept leading
zeros, and included the required human-review uncertainty. Reported usage was
1,041 input tokens and 536 output tokens (including 96 reasoning tokens); local
estimated charge USD 0.000373. No rejection diagnostic was created. The full
result was printed during the run but was not saved as a separate output file.

This is one validated development case, pending Member 1 semantic review. No
other Group C live case has been run. It does not establish accuracy for the
state, multi-lot, range or Unknown challenge patterns.

Member 1 subsequently inspected the `H-1388-2026` source phrase and confirmed
both reported lot-to-expiry pairings as good. This is case-specific human
semantic review of the development result, not an independent accuracy score.

## First state-specific pilot — rejected, diagnosed

One paid call was made for `H-1361-2026` (ledger call 18). It used 1,178 input
and 1,023 output tokens; local estimated charge USD 0.000630. The adapter
rejected the output with `Relationship source span is missing or nonunique`.
The parsed proposal and reason were saved in the owner-only local file
`runtime/group_c_h1361_attempt1_rejected.json`. No successful result was
returned; the redirected stdout artifact is empty.

The diagnostic shows all seven code/date values in the proposal, but it
repeats `Illinois:` or `Texas:` in later pair spans even though the source
prints each state heading once. It also labels the state-specific codes as
lots, which the FDA field does not explicitly do. These are unsupported
source claims, so the rejected result was not promoted to a validated run.

The offline contract now checks a code/date span against the nearest preceding
state heading, and rejects `lot` labels for this source's unlabeled state
codes. The prompt describes this representation explicitly. The full suite
passed **670 tests** after the correction. No second state-specific paid call
was made; model performance on the corrected request remains unverified.

## State-specific retry — validated, pending human review

After Member 1 authorized the next controlled step, one retry of
`H-1361-2026` succeeded (ledger call 19). Its full output is saved in
`runtime/group_c_h1361_attempt2.stdout.txt`; no rejection diagnostic was
created. The result was independently reloaded from that file and passed
`validate_group_c_result` against event `99611` and the frozen snapshot.

All seven source pairings were preserved:

| State | Code | Date text |
| --- | --- | --- |
| Illinois | `TFIC207` | `8/7/2026` |
| Illinois | `TFIC209` | `8/9/2026` |
| Illinois | `TFIC211` | `8/11/2026` |
| Texas | `TFTX209` | `8/9/2026` |
| Texas | `TFTX211` | `8/11/2026` |
| Texas | `TFTX213U11` | `8/13/2026` |
| Texas | `TFTX216` | `8/16/2026` |

The model used `other` for state-specific codes and unlabeled dates rather
than asserting that they are lots or expiry dates. It explicitly stated that
the source does not define the codes' meaning or the dates' meaning, and
retained the required human-review uncertainty. A product UPC was also cited
from the product-description passage. Reported usage: 1,241 input tokens,
1,089 output tokens (140 reasoning tokens within output), local estimated
USD 0.000669. This is a validated development output; it is not a held-out
accuracy result.

Member 1 subsequently reviewed and approved the seven state/code/date
pairings for `H-1361-2026`. This approval concerns their literal pairing and
state scope in the source. The source still does not establish that the codes
are lots or the dates are expiry dates; those meanings remain unresolved.

## H-1396-2026 controlled live case — not accepted after source review

One paid call returned both literal code/date pairs:
`L6080C` with `SEP 20 2027`, and `L6079C` with `SEP 19 2027`.
The full response remains at `runtime/group_c_h1396_attempt1.stdout.txt`.
Ledger call 20 recorded 1,136 input and 496 output tokens, local estimated
USD 0.000362. The response initially passed the provisional validator, but
subsequent source review found an unsupported identifier kind: it called
`SEP 19 2027` a `best_by_date`. The product description labels only
`SEP 20 2027` with `BEST if Used By`; the second date occurs only in the
unlabeled `code_info` sequence. The response is therefore **not accepted**
as a validated semantic result despite its correct literal pairings.

The Group C validator now requires an adjacent explicit source label before
asserting `best_by_date` for this recall, and the prompt instructs the model
to preserve unlabeled date literals without assigning a date type. The saved
response was rechecked and now raises `ContractError: Best-by date lacks an
explicit adjacent source label`. A regression test was added; the full suite
passed **671 tests**. No second paid call was made for this recall.

## H-1396-2026 corrected live retry — validated, pending human review

After Member 1 authorized one retry, the corrected output passed the Group C
validator (ledger call 21). Its full output was saved at
`runtime/group_c_h1396_attempt2.stdout.txt`, reloaded, and validated against
event `99853` and the frozen source. The result preserved both literal pairs:
`L6080C` with `SEP 20 2027`, and `L6079C` with `SEP 19 2027`.

The product-description field explicitly says `BEST if Used By: SEP 20 2027`
and supplies UPC `194346442706`, so the model cited that passage for the
best-by value and UPC. It kept `SEP 19 2027` as `other`, without asserting a
best-by or expiry meaning, and included an uncertainty about unlabeled dates
in `code_info`. The codes were also kept as `other` rather than assumed lots.
Reported usage: 1,179 input tokens, 577 output tokens (228 reasoning tokens
within output); local estimated USD 0.000407. This is one validated development
result pending Member 1 semantic review, not a held-out accuracy result.

Member 1 subsequently reviewed and approved the two literal code/date pairings
for `H-1396-2026`: `L6080C` with `SEP 20 2027`, and `L6079C` with `SEP 19
2027`. The review also accepts that only `SEP 20 2027` has the explicit
`BEST if Used By` label; `SEP 19 2027` remains untyped because its meaning is
not specified by the cited source text.

## F-1420-2012 controlled live case — validated, pending human review

After Member 1 authorized one controlled call, the `F-1420-2012` result passed
the Group C validator (ledger call 22). Its full output was saved at
`runtime/group_c_f1420_attempt1.stdout.txt`, reloaded, and independently
validated against event `57449` and the frozen snapshot. The source has
`code_info: "Unknown"` and `distribution_pattern: "Unknown"`. The result
preserved those exact source fields, returned zero identifiers and zero
relationships, and stated that no code or date is provided. No rejection
diagnostic was created.

Reported usage was 1,106 input tokens and 86 output tokens (35 reasoning
tokens within output); local estimated charge USD 0.000154. This is a
validated development output, pending Member 1 semantic review. It does not
establish held-out accuracy or resolve the unknown source values.

Member 1 subsequently reviewed the source and confirmed that no code or date
identifier is visible for `F-1420-2012`. The zero-identifier, zero-relationship
result is accepted for this development record; the source's `Unknown` values
remain unchanged.

## F-0536-2021 controlled live case — validated, pending human review

One authorized paid call returned the two exact `Use By` dates from
`code_info`: `04/20/2021` as the range start and `05/04/2021` as the range
end, joined by the source's `thru` wording. The full response is saved at
`runtime/group_c_f0536_attempt1.stdout.txt`. It was reloaded and passed
`validate_group_c_result` for event `87836` and the frozen snapshot. No
rejection diagnostic was created.

Ledger call 23 recorded 1,158 input and 333 output tokens (118 reasoning
tokens within output); local estimated charge USD 0.000283. The model did not
extract `Item # 81068` or UPC `7 95631 81068 4` from the product description.
The validator does not require every product identifier, so this omission is
an extraction limitation despite the passing source validation. The date
range interpretation and omitted identifiers await Member 1 review.

Later completeness audit: the Group C validator now requires both the
explicit `Item # 81068` and UPC `7 95631 81068 4` from the product passage.
The saved first live result would fail this stronger rule. Its approved date
range remains a reviewed source observation, not a complete accepted A1 output.

Member 1 confirmed that `04/20/2021` through `05/04/2021` is the intended
Use By date range. The item number and UPC remain documented as an extraction
omission for this live attempt.

## F-0536-2021 controlled retry — complete under revised source rule

After the labeled product-identifier rule was added, one authorized paid retry
passed the Group C validator (ledger call 25). The full result is saved at
`runtime/group_c_f0536_attempt2.stdout.txt`; it was reloaded and independently
validated for event `87836` and the frozen snapshot. It includes UPC
`7 95631 81068 4` and Item # `81068`, each citing the product-description
passage, plus `04/20/2021` and `05/04/2021` as the `Use By` range endpoints
citing `code_info`. The item number uses the approved schema's `other` kind
and an explicit uncertainty. No rejection diagnostic was created.

Reported usage was 1,189 input and 449 output tokens (190 reasoning tokens
within output); local estimated charge USD 0.000344. Member 1 had already
approved the literal date range; the newly extracted product identifiers
remain available for final human review. This is a development result, not
held-out accuracy evidence.

Member 1 subsequently confirmed the newly included Item # `81068` and UPC
`7 95631 81068 4` against the product description. The corrected development
result is accepted for its literal identifiers and date range. The item-number
kind remains `other` under the unchanged approved A1 schema.

## F-2413-2017 first controlled live case — rejected by relation kind

One authorized paid call was made for event `77557` (ledger call 24). The
adapter rejected it with `Group C relationships omit or alter source pairings`.
The parsed proposal and exact error are saved in the owner-only diagnostic
`runtime/group_c_f2413_attempt1_rejected.json`; the stdout file is empty
because the adapter returned no accepted result. Usage was 1,255 input and
1,141 output tokens (145 reasoning tokens within output), local estimated
USD 0.000696.

The proposal included both literal product UPCs and all seven visible lot/date
pairs. It preserved the malformed source date `1/10/2 018` exactly and made
no package-to-lot assignment. The rejection is a provisional contract mismatch:
the snapshot-specific completeness check requires relation kind `code_date`,
while the proposal used `lot_date`, consistent with the source heading `Lot
Code / Best By Date`. This first output is not accepted. The relation-kind
rule and its tests need review before a further paid call or promotion of the
saved proposal.

## F-2413-2017 offline contract correction — source-valid, pending human review

The completeness rule and development fixtures now require `lot_date` for
this recall, because the source explicitly calls the values `Lot Code` and
`Best By Date`. A regression test rejects recasting one of these pairs as
an unlabeled `code_date`. The full suite passed **672 tests**.

The exact saved proposal from ledger call 24 was rebuilt with canonical
metadata and character offsets from the frozen source, then passed
`validate_group_c_result` offline: seven lot/date relations and 16 identifier
entries, including two UPCs. The two pairs under `Mini's Lot Code / Best By
Date` remain in their source sequence. The malformed `1/10/2 018` remains
literal. This is a source-valid development result awaiting Member 1 semantic
review; no additional API call was made. The source does not explicitly map
the five earlier pairs to a particular package size or UPC, so no such
assignment is asserted.

Member 1 subsequently reviewed and confirmed the literal values in this
record, including the two pairs under `Mini's Lot Code / Best By Date` and
the exact source spelling `1/10/2 018`. This accepts the seven source
pairings and both UPC literals for the development record. It does not
interpret the malformed date as a normalized calendar date or assign the
other lots to a package size or UPC.
