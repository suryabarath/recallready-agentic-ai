# Combined A1 Group C live pilot

Member 1 authorized one combined Group C live pilot for `H-1388-2026`.
The existing service, model, prompts, budget controls and schemas were used.
Qdrant was read only. Inventory and held-out labels were not accessed.

## Actual results

| Measure | Result |
| --- | --- |
| Started / completed UTC | 2026-11-19T15:35:44.131919+00:00 / 2026-11-19T15:35:51.059169+00:00 |
| Recall / event | `H-1388-2026` / `99841` |
| Snapshot | `FDA-FOOD-2026-10-23-USER-SNAPSHOT` |
| Collection | `recallready_fda_food_a1_v1` |
| Embedding / interpretation models | `sentence-transformers/all-minilm-l6-v2` / `gpt-6-luna` |
| Retrieved and source-verified passages | 4/4 |
| Validated contract | `0.2-group-c-provisional` with unchanged `0.1-proposed` base |
| End-to-end / retrieval time | 6.9266 / 0.6378 seconds |
| Model requests / repairs | 1 / 0 |
| Input / output tokens | 1178 / 360 |
| Reasoning tokens | 60, included in output tokens |
| Ledger call | 28 |
| Local estimated cost | $0.000298, using historical ledger rates; not a verified invoice |

SDK retries were disabled. The output cap remained 4,000 tokens and the local
accounting limit remained $1. The restricted shell required escalation for
network access and local ledger/artifact writes. Credentials were not printed.

## Relationship preservation

Exact source `code_info`:

```text
LOT 00000ZRAA1  EXP 08/15/2026 LOT 00000ZUAD2  EXP 08/18/2026
```

| Lot | Associated expiry literal | Exact source character interval |
| --- | --- | --- |
| `00000ZRAA1` | `08/15/2026` | `[0, 30)` |
| `00000ZUAD2` | `08/18/2026` | `[31, 61)` |

The result contains exactly two `lot_date` relations, cited to
`EV-H-1388-2026-CODE_INFO`. Leading zeros, spacing and source spans are retained.
Flat identifiers also list the two lots and expiry dates; consumers should use
the relations to preserve the pairings. The result retains the uncertainty:
`Group C relationships require human review.` Passing validation does not
constitute a new human approval or establish an inventory decision.

## Artifact and independent checks

Owner-only (`0600`) local artifact:
`runtime/a1_service_group_c_live_20261119T153551059225Z.json`.
It contains the result, retrieved IDs/scores, timings and new ledger entry.
It is ignored by Git and must be supplied separately to share the original trace.

After execution, a separate read-only check passed `validate_group_c_result`
using `Source()` reading the immutable starter ZIP directly. It also checked
the complete four-passage retrieved/cited set and point IDs, both exact
relation spans and offsets, the two distinct lot/date pairs, leading zeros,
review uncertainty, ledger response-ID/charge consistency, and permissions.

## Coverage and next gate

One combined live pilot has now passed in each group: A `H-0011-2027`, B
`F-0332-2023`, and C `H-1388-2026`. This is representative execution coverage,
not a measurement of independent accuracy, retrieval relevance, or all 18
combined live flows. Latency is a single observation. OpenAI token counts do
not include Qdrant inference usage. Historical separate live interpreter runs
and the 823-test offline suite remain distinct verification evidence.

No production code was changed, no additional model attempts were made after
success, and no offline tests were rerun for these documentation updates.
Next: review representative pilot results and remaining service/interface gaps
before agreeing the coordinator error/trace contract and integration scope.
