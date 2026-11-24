# Targeted correction contract

This contract is now implemented locally. See the
[implementation and verification guide](TARGETED_CORRECTION_IMPLEMENTATION_2026-11-24.md)
for exact eligibility, files, results and remaining limits. The earlier
live-tested checkpoint did not include these paths; no new live pilot is claimed.

## Architecture and boundaries

v4.2 permits at most one targeted correction followed by affected downstream
stages. This extends the existing coordinator; it does not replace the A1
facts schema, matching policy, source ZIP, inventory or human-review gate.
Automatic A1/A2 correction requires an explicit coordinator option. Existing
callers retain the current escalation behavior by default.

| Target | Eligible request | Inputs | Stages repeated |
| --- | --- | --- | --- |
| A1 | Semantic critic code `a1_identifier_interpretation`, citing product/code evidence in this case | Exact FDA passages, fixed field-focus instruction, original validated A1 result for preservation checks | A1, then A2/A3/A4 only if preceding stages remain resolved without uncertainty |
| A2 | Deterministic audit code `a2_sqlite_or_match_drift` | Unchanged validated A1 and the same caller-owned inventory store | A2, then A3/A4 if resolved without review |
| A3 | Existing bounded plan request | Unchanged validated A2 | A3 and A4 |

Unknown codes, mixed target blockers, non-fixable findings, provider/accounting
errors, invalid citations, source/store integrity failures and unresolved
meaning escalate. They cannot trigger a broader search, a model change, a
policy change, a new inventory set or removal of human review.

## Correction payload and data separation

The request records case/run/recall/event/snapshot, target, reason codes,
blocking finding IDs and evidence IDs. It is built by the coordinator from
the validated round-0 A4 result. Free-text model instructions are retained in
the original audit for inspection but never executed or treated as authority.
A1 receives fixed trusted guidance naming only validated FDA field names.
No A2 item values, stock quantities, inventory notes or critic prose enter A1.
Only identifiers citing the selected fields may change; unaffected
identifiers, literal source text and context remain protected. Existing
uncertainties cannot be erased. All normal source/citation checks still run.

## State and accounting

Additive optional state retains original A1/A2 alongside original A3/A4 and
the typed correction request. A1's trace records focused evidence IDs without
changing its inner result contract. The same case/run and ledger are used;
each model attempt obtains a distinct ledger call. One structural repair
inside a model request is distinct from the one workflow correction.

The coordinator preserves original artifacts and consumes `revision_count=1`
before invoking the target. If the target fails, later stages are cleared and
the failure envelope/trace is retained. If a corrected A1/A2 introduces review,
later stages are not run. Round-1 A4 cannot request another correction. A valid
unchanged output is possible and does not prove that the objection was solved.
Human review remains the terminal decision boundary.

## Required verification

Offline tests must establish the default escalation behavior, exact target and
context selection, rejection of unsupported requests, protection of A1 fields
and prompt isolation, A2 recomputation from unchanged inventory, preservation
of all original outputs, failure/review stops, ledger call separation, one
global correction limit and JSON round-trip validation. Existing A3 replay,
previous saved states and all 18 development cases must remain compatible.
No new live calls are part of this development step.
