# Coordinator-facing A1 run envelope

Member 1 approved proceeding with the result/error/trace proposal. The
implementation is `a1_run.run_a1_with_trace`. The existing `run_a1` function
and inner A1/Group C schemas remain compatible. No coordinator or LangGraph
implementation was found in this workspace, so this delivers the A1 boundary
and its tests, not a fabricated shared CaseState or completed graph integration.

## Call and result

Using the same store, retriever, client and budget construction as
`A1_SERVICE_GUIDE.md`, replace the service invocation with:

```python
from uuid import uuid4
from a1_run import run_a1_with_trace

envelope = run_a1_with_trace(
    store, retriever, client, budget,
    run_id=str(uuid4()),
    recall_number="H-1388-2026",
    snapshot_id=store.snapshot_id,
)
```

Calling this with live clients makes live Qdrant and paid OpenAI requests.
The caller must supply a unique nonblank run ID and own/close its resources.
Invalid envelope argument types fail validation before execution. The fixed
internal retrieval query and current 18-record scope remain in place.

The five outer fields are `run_id`, `status`, `result`, `error`, and `trace`.
`validated` requires a result and no error; `unresolved` requires an error and
no result. JSON parsing is supported by
`A1RunEnvelope.model_validate_json(envelope.model_dump_json())`.

For Group C, keep the entire `result.base` and `result.relations` envelope.
Do not flatten separate lot/date pairs. A validated result retains its
review uncertainty; it does not authorize a retailer action.

## Error handling

Errors carry typed `stage`, `code`, safe `message`, `request_state`, and
`automatic_retry_allowed=false`. Stages cover preflight, retrieval,
interpretation, validation and accounting. The coordinator can use codes
without parsing human error-message text. Low-level diagnostics, model text,
raw prompts, credentials and original source passages are excluded from the
error and operational trace. Exact source fields remain in the inner result.

Expected source/provider/validation/accounting failures produce unresolved
envelopes. Unexpected programming exceptions propagate to the caller, while
run-local context is reset. They must not be treated as validated runs.

## Trace and accounting

Trace fields include selected recall/snapshot and canonical event/archive
identity, collection/model configuration, evidence/point references and
similarity scores, retrieval and total duration, model attempts, repair count,
and per-attempt response IDs, reported token counts and accounting state.
Reasoning tokens are included in output tokens, not an extra charge term.
Rates remain historical local estimates, not provider invoices.

The budget creates a separate `run_calls(run_id, call_id)` association table.
It inserts the run link in the same transaction as the reservation. Existing
`calls` records remain intact; historical rows have no invented run IDs.
There is no global before/after ledger subtraction. Context-local recording
isolates concurrent runs; the concurrent regression uses separate source
connections and a shared budget ledger.

Request states mean:

| State | Meaning |
| --- | --- |
| `not_sent` | No request-start boundary was crossed for this reservation |
| `outcome_unknown` | Transport was entered, but no response was received; a timeout may have incurred usage |
| `response_received` | A response was received, even if usage or accounting later failed |

`model_attempts` counts actual request-boundary entries, not reserved rows.
`repair_count` counts additional model attempts within the bounded structural
repair loop. Unknown token counts and unsettled cost remain null. On ledger
unavailability, `accounting_available` is false and aggregate estimated cost
is null, never a substitute zero. Reservations remain conservative when usage
cannot be settled. This is not an enforceable provider billing cutoff.

The wrapper returns the trace; the caller owns saving it. A reservation-to-run
link is persistent, but a process crash can prevent delivery of the full trace.
Durable event streaming and duplicate-run-ID enforcement are not implemented;
callers must generate unique IDs and must not automatically repeat a run.

## Verification

```bash
.venv/bin/python -m pytest tests/test_a1_run.py -q
.venv/bin/python -m pytest -q
```

41 new wrapper tests cover all 18 development recalls, outcome invariants,
JSON parsing, malformed output/repair, source validation failures, timeout,
missing usage, reservation/settlement failure, interrupted dispatch, concurrent
run isolation, persistent run links, and exclusion of source text/secrets from
operational traces. The full suite passed: 880 tests in 3.06 seconds.

## Controlled live regression

An escalated command was approved and ran one live regression after the
reliability and envelope changes. No collection data was modified.

| Measure | Actual result |
| --- | --- |
| Recall / event | `H-1388-2026` / `99841` |
| Start / completion UTC | 2026-11-19T17:17:45.186683+00:00 / 2026-11-19T17:17:57.050054+00:00 |
| Status | `validated` |
| Retrieval | 4/4 passages verified |
| Total / retrieval time | 11.863129 / 0.637533 seconds |
| Model attempts / repairs | 1 / 0 |
| Input / output / included reasoning tokens | 1178 / 368 / 55 |
| Ledger call | 29, directly linked to the run ID |
| Estimated cost | $0.000302 at historical ledger rates |

Both relations remain exact: `00000ZRAA1` to `08/15/2026`, and `00000ZUAD2`
to `08/18/2026`. The human-review uncertainty remains present.
Owner-only local artifact:
`runtime/a1_envelope_live_20261119T171757050393Z.json`.

A separate read-only command parsed the saved envelope, validated its Group C
result against the starter ZIP directly, verified all four retrieved evidence
and point IDs, checked both relations and review uncertainty, compared its
run link and usage with ledger call 29, and checked `0600` permissions. All
checks passed. The artifact is ignored by Git and must be shared separately.

This is one live envelope regression, not an independent accuracy or relevance
evaluation. Earlier A/B/C pilots remain separate historical results. The next
integration dependency is the actual coordinator implementation and its
CaseState mapping, including unresolved and human-review routing.
