# Targeted A1/A2 correction and downstream reruns

Implemented locally on `feature/targeted-corrections-local`, based on merged
checkpoint `e81e5c3`. This work has not been pushed. The
earlier live-tested checkpoint `a591cde` remains unchanged. This guide supersedes
earlier notes that automatic A1/A2 correction is entirely unimplemented.

The subsequent [technical review and checkpoint record](TARGETED_CORRECTION_REVIEW_2026-11-24.md)
adds four reproduced A1-handoff regressions and the final 1,159-test result.
The verification counts below retain the preceding implementation checkpoint.

## Problem and resulting behavior

A4 could already detect inventory/result drift and request upstream review,
but the coordinator could only replay A3. The new opt-in path performs one
precisely scoped A1 or A2 correction, reruns the affected downstream stages,
and retains the original chain. Human review remains the decision boundary.
This implements a bounded part of v4.2; it does not change the original FDA
ZIP, basic A1 schema, Group C contract, matching policy or stock records.

For example, if a returned A2 finding says 20 packages while its unchanged
SQLite row says 12, A4 detects the difference. With corrections enabled, the
coordinator saves the original result/audit, consumes its single attempt,
recomputes A2 from the same store, rebuilds A3 and audits at round 1. If the
wrong value persists, it stops for review rather than correcting again.
The automated tests inject this error deliberately; no live quantity incident
is claimed. No correction is needed for ordinary, consistent development data.

## Enabling it

The existing constructor adds one boolean flag, defaulting to false:

```python
coordinator = A1Coordinator(
    store, retriever, client, budget,
    inventory_store=inventory,
    enable_a3=True,
    enable_a4=True,
    enable_a4_llm=False,
    enable_targeted_corrections=True,
)
state = coordinator.run(request)
```

This is configuration of the existing API, not an offline runner. Supplying
live A1 clients still makes Qdrant/OpenAI requests. A4's separate semantic
request requires `enable_a4_llm=True`. With that flag false, eligible A2 drift
can be corrected by deterministic checks; no A1 semantic correction is requested.
The shared existing budget, model configuration and disabled SDK retries apply.
No additional CLI, dependency, provider or environment variable was introduced.

Existing callers retain upstream escalation by default. Existing bounded A3
replay remains available regardless of the new upstream-correction flag.

## Eligible requests

| Target | Required finding | Correction inputs | Stages repeated |
| --- | --- | --- | --- |
| A1 | Round-0 semantic finding with code `a1_identifier_interpretation`, citing only this recall's product/code evidence | Original FDA passages, fixed field-focus guidance, original A1 result for local preservation checks | A1, then A2/A3/A4 only while prior stages remain resolved without review |
| A2 | Round-0 deterministic finding `a2_sqlite_or_match_drift` | Unchanged validated A1 and the same caller-owned inventory store | A2, then A3/A4 if no failure/review gate intervenes |
| A3 | Existing fixable, single-target plan request | Unchanged A2 | Canonical A3 replay and A4 |

All blocking findings must be fixable, share the same target and be covered by
the request. Unknown reason codes, mixed target blockers, unsupported references,
non-fixable findings, source/store integrity failures and provider/accounting
errors cannot initiate an upstream correction. A semantic A2 complaint cannot
pretend to be the deterministic SQLite drift finding. A1 source-validation
failure remains a blocking review finding; it does not permit source repair.

## A1 data boundary and preservation

`corrections.py` creates a typed request containing case/run/recall/event/snapshot,
reason codes, blocking finding IDs and exact evidence IDs. It deliberately has
no executable instruction/prose field.

The correction prompt includes the same four canonical FDA passages and fixed
trusted guidance naming only `product_description` and/or `code_info`. It does
not receive stock attributes, item IDs, quantities, original A2 results, critic
messages or critic-generated instructions. The original A1 result is used for
local preservation checks, rather than being injected as new source evidence.

Before dispatch, normal source validation checks the original result. After
generation, the normal source/citation/identifier checks still run. Additional
checks require:

- Identical source fields, metadata, event, snapshot and non-identifier facts.
- Identical unrelated identifiers, including duplicate counts. An identifier
  citing any field outside the focus is protected; changing its citations does
  not make it eligible retroactively.
- Preservation of existing uncertainty; new uncertainty stops the downstream
  flow before A2.
- The same archive/model/retrieval configuration at the saved-state boundary.

Only identifiers supported entirely by focused fields may change. No output
is silently merged or filtered to repair a failed preservation check. A
source-valid but out-of-scope change returns `correction_scope_violation`.
Group C and existing uncertain A1 results retain the earlier review gate and
never enter this correction flow.

## State, accounting and failure handling

The existing `CaseState` adds optional `prior_a1`, `prior_a2` and `correction`.
Original `prior_a3`/`prior_a4` remain. Before an upstream attempt, the coordinator
saves the complete original chain, clears downstream results and sets
`revision_count=1`. An exception cannot silently restore stale downstream work
as if it belonged to a corrected A1/A2 result.

Each original artifact is validated against its original upstream chain;
current artifacts are validated against the current chain. This matters when
an omitted match becomes a finding after correction: old A4 item references
must not be checked against a different corrected result. Reload validation
also binds the typed correction to the original audit and rejects reused
ledger-call IDs across distinct attempts.

The A1 trace adds `correction_evidence_ids`, populated before execution so
even pre-model failures retain the intended scope. Corrected A1 calls use the
same run ID and persistent budget ledger, with distinct reservation/call IDs.
Known rejected responses are accounted; timeout reservations remain conservative.
Budget exhaustion stops before dispatch and retains original usage.

A1/A2 errors or new uncertainty stop downstream execution. An A3/A4 failure
after correction preserves the original audit/history and stops unresolved.
A successful rerun is audited at round 1, which cannot request another revision.
A structurally invalid model response may still use its existing one structural
repair. That is separate from the one workflow correction; one correction
does not mean one API request total. No workflow loop or graph retry was added.

Old saved states without the additive fields still load. Existing A3 replay
states also load without a typed correction request, provided their original
audit supports that replay.

## Files and responsibilities

| File | Change |
| --- | --- |
| `corrections.py` | Typed requests, eligibility policy and A1 preservation checks |
| `interpreter.py` | Fixed focused guidance and pre/post source-preservation validation |
| `a1_service.py`, `a1_run.py`, `a1_trace.py` | Carry correction scope through the existing service/envelope and retain scope on failures |
| `a4_checks.py`, `a4_agent.py` | Opt-in deterministic A2 drift eligibility and supported A1 critic code |
| `coordinator.py` | One attempt, original history, affected-stage reruns and existing review/error routing |
| `case_state.py` | Original/current chain validation, correction provenance and distinct ledger calls |
| `tests/test_targeted_corrections.py` | 63 initial regressions; 67 after the subsequent handoff review |
| `tests/a2_development_inventory_checks.py` | Add a fourth configuration: A1-A4 with corrections enabled |

## Actual offline verification

Commands from `code_workspace`:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short

.venv/bin/python -B -m pip check
```

Recorded results on 24 November 2026:

- Final permitted regression: **1,155 passed in 7.06 seconds**, including
  all 63 new correction checks. Focused counts are not additional unique tests.
- Final approved private development selection: **75 passed in 2.45 seconds**:
  72 executions (18 cases in four configurations), one
  36-row inventory round trip and two existing demonstration checks.
- `pip check`: no broken requirements. Pip reported its cache was unavailable
  under the current permissions; no dependency installation was attempted.
- Three saved offline demo states and the existing full-chain live state
  reloaded under the new model; their original checksums matched.
- Starter ZIP SHA-256 remained
  `b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.
- `git diff --check` passed. No new live OpenAI/Qdrant requests were made.

Offline normal flows execute real source resolution, SQLite stores, matching,
planning, graph routing and SDK serialization. External model/vector responses
are simulated. Selected tests deliberately inject faulty stage outputs,
exceptions, budget exhaustion or malformed stored state; they do not replace
the correction implementation or matcher with expected answers.

The first new test run had two incorrect test assumptions: A3 does not carry
quantity in its plan, and a non-fixable critic response must not suggest a
revision target. The tests were corrected to verify actual planner invocations
and a consistent non-fixable proposal. Existing tests/assertions were not
weakened or removed. The read-only sandbox initially prevented pytest from
creating temporary files; scoped approved test execution resolved that
environment restriction without changing the tests.

## Limits and next verification gate

- These are development behavior/consistency checks, not independent accuracy
  measurements. Shared matching-policy errors can survive deterministic replay.
- The semantic critic may request an unchanged A1 interpretation. A rerun does
  not prove the objection was solved or that source meaning is now certain.
- The new correction prompts/routes have no live evidence. The previous
  controlled live pilot remains evidence for the earlier no-correction path.
- A2 policy sign-off, general date comparison, case inventory-set selection,
  durable human approval/resumption, UI/hosting and independent evaluation
  remain pending.
- The 21 full-package inventory tests remain unchanged and unrun. No held-out
  labels or unselected inventory objects were used.
- Same caller-owned stores, snapshot and run are reused; no source/inventory
  writes occur. This does not provide isolation from an external process
  modifying a database or a durable crash-recovery/checkpoint service.
- No branch creation, commit, push, merge, deployment or new paid call was
  performed in the initial implementation step. The subsequent local review
  and checkpoint are recorded separately in the linked review document.

The next gate is review of the local diff and eligibility rules. Any live
correction pilot is a separately scoped step, with an approved input, unchanged
authoritative stores, existing ledger and explicit expected stopping behavior.
