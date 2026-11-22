# A1 interface proposal for Member 1 review

Member 1 approved retaining the separate provisional
`0.2-group-c-provisional` relationship envelope around the approved
`0.1-proposed` A1 output schema. This freezes that boundary for continued A1
development. The coordinator's unresolved/error trace shape and optional
retrieval-query input remain proposals for integration review.

## Proposed call boundary

Input: caller-selected `recall_number` and `snapshot_id`; optional trusted
`event_id` and retrieval query context. The caller, not the model, owns these
selection values. A1 reads FDA evidence only; inventory and evaluation labels
never enter its request.

Output: a validated typed A1 result with canonical `event_id`, original
source fields, identifiers, uncertainties, evidence IDs, and Group C relations
where applicable. Each relation retains its exact source span, offsets,
literal parts, and one cited evidence ID. Unknown or ambiguous scope remains
explicit. A1 does not output a stock-match decision or proposed action.

Failure: return or raise an explicit unresolved/error outcome for missing
source, invalid retrieval hit, API failure, malformed model output, unsupported
literal, or citation mismatch. No silent default or model-authored canonical
metadata. The coordinator records a trace event and decides whether to retry,
review, or stop; A1 does not rerun downstream agents itself.

## Approval questions before coordinator integration

1. Which error shape and trace fields should the coordinator use for an
   unresolved A1 run?
2. Should A1 receive only an exact recall ID, or may the coordinator also pass
   a separate natural-language retrieval query? Exact recall selection must
   never depend on vector similarity.

Stage 2 below can proceed with this proposal because its exact FDA store uses
the already established recall/event/snapshot/evidence identity, independent
of the final CaseState representation.
