# A1 targeted live review verification — 19 November 2026

Two authorized live reruns completed after the Option A and explicit human
review workflow changes. Both exited 0, with one response each and no structural
repair or automatic retry. Model: `gpt-6-luna`; low reasoning; default service
tier; `store=False`; maximum output 4,000 tokens. Budget ledger:
`runtime/a1_usage.sqlite`, same USD 1.00 local estimated ceiling as earlier runs.

## Results and review distinction

| Recall | Model proposal | Final validated output | Assessment |
| --- | --- | --- | --- |
| F-0705-2025 | `other`: `04162026 BC 6937218914734` | `lot`: the same entire phrase, explicitly approved by Member 1 | Local review applied after inference; model observations retained with a before-review label. No BC-to-UPC assertion. |
| F-1472-2024 | `other`: `06-04-24 08/04/2024` | Same `other` phrase with uncertainty | Whole phrase preserved; no lot assertion or expiry inferred; no human lot approval supplied. |

F-0705-2025 original model observation:

> The labeled lot code contains BC and a date-like sequence; the evidence does not distinguish the boundaries or establish whether the final number is a separate identifier.

The phrase contains no explicit expiry label. This model observation is retained
as generated text, not independent evidence that a date exists. The final review
note states:

> Human review by Member 1: '04162026 BC 6937218914734' is approved as one lot (model kind before review: other). This approval does not establish a separate date or code meaning.

F-1472-2024 model uncertainty:

> The LOT # field contains two date-like parts without distinct labels, so their boundaries and relationship are ambiguous; the phrase is preserved as other rather than interpreted as a lot or date.

These observations verify the scoped workflow. The human-assisted F-0705-2025
result must not be scored as an independent model identification of a lot.
No manufacturer confirmation or population-level accuracy is established.

## Measured usage

| Recall | Ledger call | Input tokens | Output tokens | Reasoning tokens, included in output | Estimated USD | CLI wall seconds |
| --- | --- | --- | --- | --- | --- | --- |
| F-0705-2025 | 7 | 864 | 162 | 73 | 0.000168 | 7.583 |
| F-1472-2024 | 8 | 849 | 290 | 193 | 0.000230 | 4.916 |
| Total, these runs | 2 calls | 1,713 | 452 | 266 | 0.000398 | 12.499 |

Cumulative ledger: eight settled calls, estimated **USD 0.001483**, including
the six original pilot calls. Figures are rounded up per call to microdollars
using the configured rates; invoice, tax, credit application and currency
conversion were not verified. Reasoning is not charged twice. Durations include
local process startup, validation and network time, not isolated model latency.

Response IDs:

- F-0705-2025: `resp_045f231745bcee33016afe9232338887d089d414a1911a10d2`.
- F-1472-2024: `resp_0fa1e715fab6a9eb016afe9237127c87d09defa9ed4b8664ce`.

## Artifacts, checks and reproducibility

Local artifacts: `runtime/review_live_4wp2lde5/`. Each recall has a raw CLI
stdout file and a structured run JSON containing the final result, cumulative
usage snapshot, exit code and duration. `index.json` records completion at
`2026-11-19T06:07:55.313522+00:00`. These runtime files are Git-ignored; share
them separately if needed. No previous artifact was overwritten. The CLI does
not save a separate raw intermediate model response; its original kind and
uncertainty are retained in the final review notes for the reviewed case.

Executed commands, after loading the key privately:

```bash
.venv/bin/python interpreter.py --recall F-0705-2025 --allow-paid-call --budget-usd 1.00 --ledger runtime/a1_usage.sqlite --human-review-file docs/a1_member1_lot_approval.json
.venv/bin/python interpreter.py --recall F-1472-2024 --allow-paid-call --budget-usd 1.00 --ledger runtime/a1_usage.sqlite
```

Both saved results passed an additional offline `validate_result` check with
trusted source context. F-0705-2025 was also checked without the approval and
correctly rejected. F-1472-2024 was checked for an unchanged complete `other`
value. Neither final result contains an `expiry_date` identifier. Source text,
leading zero, evidence IDs, event and snapshot remain intact. The starter ZIP
SHA-256 remains
`b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.

The most recent offline suite remains **507 passed in 1.15 seconds** from the
preceding workflow implementation. No source code changed in this rerun, so
pytest was not repeated. No inventory, held-out labels, Qdrant or extra agents
were accessed. Group B/C and the full four-agent app remain unverified.

## Self-report

Verified: two real calls, saved-output revalidation, negative approval gate,
usage ledger and original archive hash. No retries, skipped tests or source
changes. Remaining limits: broader semantic accuracy, repeated-run stability,
manufacturer meaning and actual invoiced charge. Confidence is high for these
two observed outcomes, limited for generalization beyond the tested cases.
