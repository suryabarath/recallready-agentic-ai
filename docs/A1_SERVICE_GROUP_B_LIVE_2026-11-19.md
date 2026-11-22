# Combined A1 Group B live pilot

Member 1 authorized the next step after the first combined Group A pilot.
One live service request was run for `F-0332-2023`, event `91355`, using the
existing model, collection, output schema, and local budget controls.

## Measured results

| Measure | Actual result |
| --- | --- |
| Started / completed UTC | 2026-11-19T15:26:56.092406+00:00 / 2026-11-19T15:27:01.504714+00:00 |
| Snapshot | `FDA-FOOD-2026-10-23-USER-SNAPSHOT` |
| Collection | `recallready_fda_food_a1_v1` |
| Embedding / interpretation models | `sentence-transformers/all-minilm-l6-v2` / `gpt-6-luna` |
| Retrieved and verified passages | 4/4 |
| Final source/citation validation | Passed (`0.1-proposed`) |
| Total / retrieval elapsed time | 5.4115 / 0.5806 seconds |
| Model requests / structural repairs | 1 / 0 |
| Reported input / output / reasoning tokens | 889 / 111 / 0 |
| Ledger call | 27 |
| Estimated cost | $0.000145 using historical ledger rates; not a verified invoice |

SDK retries were disabled; the output cap remained 4,000 tokens and the local
accounting limit remained $1. No prompt or production source changes were
made. The command required escalation because shell writes/network access are
restricted. Qdrant was queried without modifying collection data.

## Source interpretation

Exact `code_info`: `Lot # 022422SRB, Expiration date: 2/24/2024`.

The validated result preserves lot `022422SRB`, including its leading zero,
and expiry date `2/24/2024`. UPC `855099007764` is cited to the product
description (`Alpha Plant-Based Burrito - Steakless Ranchero 5.5 oz UPC
855099007764 Frozen`). The model returned no uncertainties for this record.
The result does not establish an inventory match or a retailer action.

## Saved evidence and independent checks

The owner-only (`0600`) local artifact is
`runtime/a1_service_group_b_live_20261119T152701504801Z.json`. It contains the
typed result, retrieved IDs/scores, timing, and ledger entry. Runtime artifacts
are ignored by Git and must be supplied separately for teammate inspection.

A separate read-only check passed `validate_result` against `Source()`, which
reads the starter ZIP directly. It also verified the complete four-passage
retrieved/cited set, point IDs against the ZIP, leading-zero lot preservation,
ledger response-ID/charge consistency, and artifact permissions.

## Limits and continuation

There are now two successful combined live service pilots: one Group A and
one Group B. Earlier live interpreter runs for all 18 records and the existing
823-test offline suite are distinct verification evidence. This pilot does
not measure independent extraction accuracy or retrieval relevance. Token
counts above cover OpenAI interpretation, not Qdrant inference; latency is a
single observation. The next combined pilot should exercise Group C relations.
