# RecallReady A1: 18-record development status — 19 November 2026

**20 November update:** an A1-only LangGraph coordinator and typed CaseState
are now implemented; the current full suite passed 912 tests in 5.79 seconds.
See [the coordinator guide](A1_COORDINATOR_GUIDE_2026-11-20.md). Historical
counts and missing-coordinator notes below predate this addition. A subsequent
live coordinator pilot passed for `H-1388-2026`, preserving both lot/expiry
pairs and routing to human review; the coordinator guide records the evidence.
No A2–A4 workflow is claimed.

This is the current status summary for teammates and final-submission authors.
It describes a standalone A1 prototype, not a completed four-agent product or
an independent accuracy evaluation. Detailed case histories remain in the
Group A, B, and C live-review documents.

## Implemented and verified

| Area | Current state |
| --- | --- |
| Source | Exact lookup for 18 selected food recalls (six each in Groups A, B, C) and 72 passages from the immutable starter ZIP, read in place |
| Provenance | Recall, event, snapshot, passage ID, point ID, and original text validated against the selected source |
| Group A+B | Bounded OpenAI adapter using the approved `0.1-proposed` result schema; 12 development records tested live and reviewed |
| Group C | Separate provisional `0.2-group-c-provisional` relationship envelope around the unchanged A1 schema; six development records tested live with source-bound validation and Member 1 review |
| Cost control | Persistent local usage ledger, request reservations, no SDK retries, bounded structural repair; charges are local estimates, not invoices |
| Exact FDA SQLite store | Stage 2 implementation in `fda_store.py` builds a separate FDA-only database from the verified starter ZIP. A project-local `runtime/fda_a1.sqlite` was built and independently read back: 18 records, 18 events, 72 passages. Both interpreter adapters accept the read-only store; the Group A+B CLI exposes `--fda-store`. |
| Embedding input preparation | `embedding_inputs.py` binds the starter's 72 vector-free staging entries to exact SQLite evidence and the source archive hash before Cloud Inference. |
| Qdrant retrieval | Member 1 selected `recallready_fda_food_a1_v1` for the FDA-only collection. It contains 72 Cloud Inference points using `sentence-transformers/all-minilm-l6-v2`, 384-dimensional cosine vectors, and keyword indexes on recall and snapshot. All cloud IDs and payload identities matched SQLite; filtered retrieval passed for 18/18 development recalls and all 72 returned hits were revalidated through SQLite. |
| Qdrant review fixes | HTTPS transport refuses all redirects to prevent forwarding API keys. Query input types are checked before transport calls; malformed response objects, results, points, and payloads raise `QdrantA1Error`. Offline regressions cover cross-context and invented IDs, duplicate/excess hits, invalid scores, and redirect handling. |
| Standalone A1 service | `a1_service.run_a1` connects exact selection, complete four-passage Qdrant retrieval, SQLite revalidation, Group A/B or Group C interpretation, and final citation/source validation. All 18 recalls passed the offline combined flow; partial retrieval stops before model calls. See `A1_SERVICE_GUIDE.md`. |
| Combined live pilots | Group A `H-0011-2027` passed in 7.8552 seconds; Group B `F-0332-2023` passed in 5.4115 seconds; Group C `H-1388-2026` passed in 6.9266 seconds with both lot/expiry pairs intact and review uncertainty retained. Each retrieved 4/4 passages, used one model request without repair, and passed a separate direct-ZIP source check. See the three `A1_SERVICE_*LIVE*2026-11-19.md` pilot records. This is representative coverage, not independent accuracy evaluation. |
| Storage and cleanup fixes | Budget operations explicitly close owned SQLite connections and report storage errors; failed settlement retains the reservation and warns that a request may be charged. The service normalizes local storage errors, failed store construction closes its connection, and CLI cleanup runs even if usage reporting fails. These fixes were verified offline. |
| Latest local test suite | 880 tests passed, including 41 run-envelope tests, 16 database/resource tests, 45 service integration tests and 96 Qdrant tests. A new live Group C regression subsequently verified the storage and trace changes. |
| Coordinator boundary | Member 1 approved the outer envelope. `run_a1_with_trace` returns typed result/error/trace metadata and persists atomic run-to-ledger links. Concurrent offline runs remain isolated. A live `H-1388-2026` regression passed with 4/4 passages, both relations, one model attempt and ledger call 29; see `A1_RUN_ENVELOPE_GUIDE.md`. No actual coordinator implementation was found, so CaseState mapping and LangGraph routing remain pending. |

Group C review status:

| Recall | Reviewed source interpretation | Remaining qualification |
| --- | --- | --- |
| `H-1388-2026` | Two lot/expiry pairs approved | Development case only |
| `H-1361-2026` | Seven state/code/date pairs approved | Code and date meanings remain unlabeled in source |
| `H-1396-2026` | Two code/date pairs approved | Only `SEP 20 2027` has the explicit `BEST if Used By` label; second date stays untyped |
| `F-1420-2012` | No visible code or date identifier approved | Source retains `Unknown` |
| `F-0536-2021` | Use By range `04/20/2021` through `05/04/2021`, Item # `81068`, and UPC `7 95631 81068 4` approved | Item # remains `other` in the unchanged A1 schema |
| `F-2413-2017` | Seven literal lot/date pairs and two UPCs approved | `1/10/2 018` stays literal; no unsupported package-to-lot mapping |

The F-0536-2021 omission was found after its first live run. The validator now
requires every explicitly labeled `UPC` and `Item #` literal from a product
description, cited to that passage. `Item #` uses the existing `other` kind
with an uncertainty because the approved schema has no item-number kind.
This rule does not assign a UPC or item number to a particular lot or package.
The saved first F-0536-2021 result is now rejected for missing both identifiers;
its date-range finding remains human-reviewed source evidence. A controlled
retry (ledger call 25) passed the revised validator with both literals and the
date range. Member 1 subsequently confirmed both product identifiers; no
package-to-date association was inferred.

## Reproduce the offline check

From `code_workspace`, with the sibling `project_reference` folder containing
the starter ZIP:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

The tests need no API key. Historical live results and the cost ledger are
local `runtime/` artifacts and are not required for offline tests. Group C has
no paid CLI entry point; its adapter is called directly in controlled pilots.
The older `A1_IMPLEMENTATION_REFERENCE.md` explains module roles and trust
boundaries but contains historical stage counts; use this page for current
coverage.

## Submission boundaries

The 18 records are development examples selected for different source
patterns. They are not a held-out test set or an accuracy denominator. The
Qdrant check verifies integrity and context-bounded retrieval, not relevance
metrics on independent queries. No inventory, held-out labels, A2–A4 implementation, complete
CaseState workflow, or retailer decision was evaluated in this A1 work.
The starter ZIP, proposed A1 output schema, and v4.2 architecture were
preserved. Describe Group C relationship output as provisional and subject to
human review, including the documented rejection and offline correction for
`F-2413-2017`.
