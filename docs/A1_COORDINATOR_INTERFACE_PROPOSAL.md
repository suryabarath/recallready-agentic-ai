# A1 coordinator boundary: proposal for Member 1

Status: Member 1 approved proceeding with the outer envelope and fixed query.
Implemented in `a1_run.py`; see `A1_RUN_ENVELOPE_GUIDE.md` for the exact API,
tests and controlled live regression. The proposal below records the design
basis. No inner A1 schema or team-wide CaseState was changed. LangGraph
integration remains pending the actual coordinator implementation.

## Recommended input

Keep caller-selected `recall_number`, `snapshot_id`, and optional exact
`event_id`. Keep the fixed internal retrieval query for this 18-record stage.
Pass only explicitly selected, source-bound human lot reviews for Group A/B.
Do not add inventory, labels, or arbitrary query text to the A1 request.
The caller creates a run ID and owns the client, store and accounting policy.

## Recommended outer run envelope

| Field | Proposed meaning |
| --- | --- |
| `run_id` | Caller-generated unique ID, shared by this run's events and ledger associations |
| `status` | `validated` or `unresolved` |
| `result` | Existing `A1Result` or complete `GroupCResult`; null on failure |
| `error` | Null on success; otherwise the structured failure below |
| `trace` | Operational evidence and accounting summary below |

Use the existing `contract_version` discriminator to identify the result type.
For Group C, keep both `base` and `relations`; never pass only the flat
identifier list downstream. A validated Group C result retains its review
uncertainty. Validation does not imply human approval or an inventory decision.

Illustrative failure shape (proposed, not a saved live failure):

```json
{
  "stage": "accounting",
  "code": "usage_settlement_failed",
  "message": "Request may already be charged; reservation retained.",
  "request_state": "response_received",
  "automatic_retry_allowed": false
}
```

Suggested stages: `preflight`, `retrieval`, `interpretation`, `validation`,
`accounting`. Suggested codes include invalid context/review, source storage
failure, retrieval failure/incomplete evidence, budget reservation failure,
provider failure, invalid output, citation/source failure and settlement
failure. Use typed failure information when implemented; do not parse human
error-message strings as a permanent coordinator interface.

## Recommended trace

Record selected recall/event/snapshot, collection and model configuration,
retrieved evidence IDs and point IDs, retrieval and total durations, response
IDs, per-run ledger call IDs, model attempts, repair count, reported token
usage and the cost-estimate rate basis. Keep unknown usage explicitly unknown.
Never substitute zero usage when the ledger is unavailable.

Associate ledger entries with a run directly. The serial pilot scripts use
before/after ledger differences, which are not sufficient for concurrent runs.
Capture events per request before and after transport and accounting steps;
do not infer request counts from ledger-row counts alone. A reserved row can
exist even when a process stops before sending its request.

Keep API keys, raw prompts and full FDA text out of operational logs. Existing
validated results still retain their exact source fields and citations.

## Error and resource behavior

- Reservation/storage failure before transport blocks a new model request.
- Provider timeouts retain conservative reservations; do not retry automatically.
- Settlement failure can follow a chargeable request; preserve the reservation
  and route to accounting review rather than regenerate the model answer.
- Semantic/source validation failures return unresolved; the existing bounded
  structural repair is the only model repair within an A1 interpretation.
- A1 does not trigger A2 or subsequent agents after a failure. The coordinator
  owns human review and the architecture's correction/rerouting policy.
- The caller closes caller-owned clients and stores. Budget operations close
  their own connections. A CLI that creates resources closes them even if
  reporting fails.

## Approval record

Member 1 instructed "proceed" after the next-step recommendation to implement
the envelope. The outer `run_id/status/result/error/trace` shape and fixed
internal query were implemented. One subsequent paid regression was executed
through an approved escalated command. Deployment and inner-schema changes
were not part of this implementation. Actual CaseState mapping remains open.

## Reliability work already verified

The completed local fixes normalize budget storage failures, preserve
reservations on failed settlements, explicitly close budget connections,
close failed FDAStore construction, and make CLI cleanup independent of
summary success. Service-level local storage failures raise `A1RunError`.

Verification: 16 new database/resource failure tests; 117 focused tests passed;
839 full-suite tests passed in 2.53 seconds. Failures were injected into real
SQLite operations, including after INSERT/UPDATE, to verify rollback. Network
responses were simulated; no paid request or cloud mutation occurred. The
three earlier live pilot results predate these fixes and were not rerun.
