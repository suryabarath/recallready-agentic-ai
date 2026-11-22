# RecallReady A1 — six-recall live development review

Recorded 18 November 2026. Audience: M1–M6 and final-submission authors.
Status: six live runs completed; deterministic validation passed; semantic
review issues remain open. This is an engineering review, not independent human
sign-off or a held-out accuracy evaluation.

Historical status note: these results were validated under the pre-19-November
rule. The subsequently approved Option A gate now rejects the two combined-lot
outputs for F-1472-2024 and F-0705-2025. See
`A1_OPTION_A_POLICY_2026-11-19.md`; the live table below remains an accurate
record of what happened at the time, not a claim that those two pass today.

## Configuration and preserved evidence

The unchanged `interpreter.py` used `gpt-6-luna`, low reasoning, default service
tier, `store=False`, 4,000 maximum output tokens and disabled SDK retries.
It sent only four canonical FDA evidence objects for each selected recall.
No review examples, inventory, held-out labels, Qdrant retrieval or other agents
were used. The same `runtime/a1_usage.sqlite` ledger and USD 1.00 estimated
ceiling covered all six calls. No code, prompt, schema or validator was adjusted
between these runs. Model behavior may vary on a later invocation.

The archive was read directly without extraction. Snapshot:
`FDA-FOOD-2026-10-23-USER-SNAPSHOT`. Its unchanged SHA-256 is
`b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.

The first recall's complete result is in the execution transcript; its usage is
in ledger call 1. The five subsequent runs were saved under:
`runtime/group_a_live_uy5d58w2/`. Each has `<recall>.stdout.txt` and
`<recall>.json`; `index.json` contains the five results, exit codes, measured
subprocess durations, timestamp and cumulative usage snapshots. Runtime files
are Git-ignored local artifacts, so this document preserves the review findings
for teammates without assuming they have those files. Copy the local artifacts
separately when assembling an authorized submission bundle; exclude `.env`.

## Measured outcomes

| Recall / event | Local validation | Input / output tokens | Reasoning tokens (within output) | Estimated USD | CLI duration, seconds |
| --- | --- | --- | --- | --- | --- |
| H-0011-2027 / 99686 | Passed, exit 0 | 855 / 110 | 0 | 0.000141 | Not measured |
| F-1542-2023 / 92944 | Passed, exit 0 | 781 / 78 | 0 | 0.000118 | 4.585 |
| F-1472-2024 / 94806 | Passed, exit 0 | 812 / 276 | 179 | 0.000220 | 4.808 |
| H-0579-2025 / 97487 | Passed, exit 0 | 845 / 204 | 63 | 0.000187 | 3.898 |
| F-0705-2025 / 96464 | Passed, exit 0 | 827 / 264 | 162 | 0.000215 | 4.706 |
| F-0324-2023 / 91439 | Passed, exit 0 | 827 / 242 | 108 | 0.000204 | 3.964 |
| Total | Six completed responses | 4,947 / 1,174 | 512 | 0.001085 | Not a six-case latency measurement |

Exactly six settled ledger entries were observed, one per recall. No structural
repair, automatic retry, transport error or unresolved CLI error occurred.
Durations include Python startup, local validation and networking; they are not
isolated server latency. Costs use the adapter's configured rates, rounded up
per call to microdollars; no provider invoice was inspected. Reasoning is already
included in output usage and is not charged again.

## Review against original passages

| Recall | Actual returned identifiers | Engineering assessment / open issue |
| --- | --- | --- |
| H-0011-2027 | UPC `850041392103`; lot `26078`; best-by `09/15/2026` | Literal values and labels supported. Model uncertainties were empty. Source mixes `10ct`, `5 count carton`, and five packages of two donuts. Reviewer note required: counting units/package relationship unresolved; do not infer a package match. |
| F-1542-2023 | UPC `5803100115`; lot `060723` | Leading zero retained. Source UPC retained literally without padding or length correction. No unsupported date generated. |
| F-1472-2024 | Kind `lot`, value `06-04-24 08/04/2024` | Entire phrase retained. Model explicitly says the second component may be part of the lot or a separate date. Combined phrase must remain unresolved before exact lot/date matching. Development example used `other`; this is a semantic policy difference, not an independently scored error. |
| H-0579-2025 | Lot `25223M`; SKU `24682-05020`; `other` `499-6100` | Lot, SKU and consecutive-count value separated; uncertainty explains the enum has no dedicated count-code kind. Range is not expanded. |
| F-0705-2025 | Kind `lot`, value `04162026 BC 6937218914734` | Leading zero and original combined text retained. Model reports component boundaries/BC meaning as uncertain and makes no UPC claim. However it does not isolate lot `04162026` and BC value `6937218914734`, unlike the development example. Whole-phrase lot classification remains unresolved and must not be used as an authoritative exact lot. |
| F-0324-2023 | Lot `336`; UPC `17442 30012`; `other` `Jan 06 2023` | UPC space retained. Sell-by meaning explicitly explained in uncertainty; no expiry/use-by assertion made. Source also mixes `5lb` with `12 packages of 4 oz`; model gives no package-count uncertainty. Preserve wording and review packaging separately. |

These are source comparisons by the implementation assistant. The development
examples were not sent to the model and are not independent gold labels. The
first and last packaging notes are reviewer observations, not model-generated
uncertainties and not alterations to the saved model outputs.

## What the checks establish

The five newly saved results were loaded from disk and passed again through
`validate_result` with caller-selected recall/event/snapshot context. Six exact
source lookups and all 24 canonical passages were separately resolved and checked
with `validate_citation`. First-run validation of the original pilot remains
recorded in the earlier verification report; its full result was not saved as a
separate JSON artifact and was not reconstructed or rerun here.

The full offline command `.venv/bin/python -m pytest -q` completed with
**475 passed in 0.94 seconds**. Existing tests for invented/cross-context IDs,
altered text, unsupported literal values and lost leading zeros remain unchanged.
No tests were skipped or weakened. The source ZIP checksum was checked again.

Six validation passes demonstrate connectivity, typed output and exact-source
provenance in these development runs. They do not establish identifier boundary
correctness, adequate uncertainty, complete associations or general accuracy.
The current label check accepts any supported literal phrase directly after a
label; it does not prove where that identifier ends. The F-0705-2025 result
demonstrates that limitation despite passing deterministic checks.

## Recommended next implementation gate

Before routing A1 outputs to exact inventory comparison, M1/M2 should freeze how
ambiguous combined codes are represented. Recommended policy: retain the whole
source phrase, require an uncertainty, and prevent ambiguous `lot` phrases from
being treated as a verified single lot. Do not guess a date boundary or convert
BC to UPC. Keep package-unit ambiguity visible for human review.

After that policy is agreed, implement general boundary/uncertainty checks with
offline adversarial cases, keep the approved schema compatible, run pytest, and
perform only a small explicitly scoped rerun. Do not hardcode these six outputs
or tune against held-out events. Further paid calls, Group B/C, vector retrieval
and downstream routing were not performed in this increment.

Suggested final-report wording:

> Six historical FDA development recalls completed live A1 inference, each
> passing deterministic contract and source-citation validation. Reported usage
> was 4,947 input and 1,174 output tokens, with an estimated aggregate cost of
> USD 0.001085. Review identified unresolved identifier boundaries and packaging
> uncertainty, so validation pass counts are not reported as semantic accuracy.

## Self-report

Verified: five new live CLI runs, saved-output revalidation, six exact lookups,
24 passage checks, six settled ledger entries, pytest and original ZIP hash.
Not verified: independent human approval, held-out accuracy, real invoice,
provider-side retention, repeated-run stability or full agent integration.
No source-code changes, test shortcuts, stubs or skipped tests. No scope
deviations. Confidence is high for measured execution/provenance and limited for
semantic completeness; identifier boundaries are the main remaining risk.
