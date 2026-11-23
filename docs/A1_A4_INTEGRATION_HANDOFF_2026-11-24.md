# A1–A4 local integration handoff

A subsequent [authorized live pilot](A1_A4_LIVE_PILOT_2026-11-24.md)
completed one A1-through-A4 matched case with the semantic critic enabled.
The final status was human review, with two model requests and no repairs or
replay. The development-check and remaining-work notes below describe the
preceding handoff checkpoint; the live pilot updates its live-coverage gap.

## Current checkpoint and scope

Local branch: `feature/a4-review-local`. The reviewed A3 checkpoint remains
`ce65b48` on `feature/a3-coordinator-local`. Initial A4 integration is at
`b5452f3`; this handoff accompanies its final review fixes. No publication,
teammate approval, live four-agent test or final submission is recorded here.

The graph supports A1, optional A2, optional A3, and optional A4. Enabling A4
requires A3 and an inventory store. A1 uses Qdrant plus the approved OpenAI
interpreter when supplied live clients. A2 and A3 are deterministic. A4 always
has deterministic checks; its separate semantic model requires explicit
`enable_a4_llm=True`. Its default is false. All current A3 actions require
human review, including a clean A4 audit.

## Final review findings

Two additional defects were reproduced with failing tests before correction:

1. A saved A4 trace could contain evidence/item references outside its A1/A2
   context while still passing shared-state parsing. `CaseState` now binds both
   current and prior A4 trace references to the upstream case's evidence and
   finding IDs. This validates context; SQLite verification remains A4's job.
2. An exception while replaying A3 could discard the completed first A4 audit
   from returned state. The coordinator now preserves original A3/A4 artifacts
   and records the single revision attempt before replay starts. A failed
   replay returns unresolved, retains the original audit and its model trace,
   and does not start a second replay.

The three new regression cases initially failed. After the fixes, the A4 suite
passed **58 tests in 2.87 seconds**; the permitted regression suite passed
**1,092 in 8.84 seconds**; the explicit development suite passed **57 in 2.56
seconds**. No existing test was removed or weakened. All three existing
demonstration states reloaded under the stronger validator and their manifest
checksums remained valid. No model or Qdrant service calls were made.

## What to inspect

| Evidence or code | Repository-relative path | Review purpose |
| --- | --- | --- |
| A4 audit and bounded model adapter | `a4_checks.py`, `a4_agent.py` | Exact checks, references, semantic failures, usage accounting and verdicts |
| Shared workflow | `coordinator.py`, `case_state.py` | Routing, identity, review/error handling, revision trace retention |
| A4 tests | `tests/test_a4_checks.py`, `tests/test_a4_agent.py`, `tests/test_a4_coordinator.py` | Normal, tampered, unavailable-store, model/accounting and failed-replay cases |
| Three representative states | `runtime/a1_a2_a3_a4_offline_demo_v1/` | Summary and complete matched/no-match/early-review states; external responses are fixtures |
| Latest development report | `runtime/a1_a2_a3_a4_final_review_checks.xml` | 54 case executions plus the inventory round trip and two demonstration checks |
| Development mapping and inventory | `runtime/a2_development_18_v1/` | 18 recalls mapped to their original 18 sets/36 synthetic rows |
| A2 review packet | `docs/A2_OWNER_REVIEW_PACKET_2026-11-22.md` | Deferred product-name, batch/lot, no-match and review-gate decisions |
| A4 technical guide | `docs/A4_REVIEW_AND_INTEGRATION_2026-11-24.md` | Implementation provenance, setup, commands, research and limitations |

`runtime/`, credentials and the FDA starter ZIP are outside this Git checkpoint.
Runtime content is local and ignored by Git; the three-route JSON demo files
have private permissions. The manifest identifies the prepared data hashes.
The offline demo's simulated token usage is not actual billing evidence.

## Observed development flow

The 18-case development selection is run with three configurations: A1/A2,
A1/A2/A3, and A1/A2/A3/A4. Each execution receives only its own original
two-row inventory set.

| Cases | A4-enabled observation |
| --- | --- |
| Two exact A2 matches | A3 plans review; A4 deterministic checks pass without blockers; final human review |
| Six A2 no-matches | A3 records no demonstrated match without clearance; A4 checks pass without blockers; final human review |
| Four other Group A and six Group C | Stop for A1 review before A2, A3 and A4 |

The case-specific graph tests simulate semantic critic responses to exercise
revision and error routes. These are distinct from the actual-development
data checks, which use deterministic A4 only. Passing tests are not an
independent accuracy evaluation.

## Team actions and outstanding work

- Coordinator owner: review stage flags, A4 references and the failure/replay
  state. Use the guide's offline commands and the three complete demo states.
- A2 owner: complete the deferred matching-policy review. No owner approval is
  implied by passing tests or by this handoff.
- A3/A4 owners: review the current A3/A4 boundary. A4 now imports actual A3
  suggested actions instead of inventing provisional urgency, quarantine or
  disclaimer fields. Check the one-replay limit and human-review wording.
- Team: a controlled live A1-through-A4 pilot remains unperformed. It would
  require explicit authorization for the separate paid A4 semantic request.
  Existing live evidence covers A1/A2, not the full latest workflow.

Automatic targeted A1/A2 correction and downstream reruns remain unfinished.
Their revision requests escalate to human review. A3 replay is bounded but
normally produces the same canonical plan; it does not learn a new policy or
execute critic-generated instructions. Durable approval/resumption, UI/hosting
and production operational validation remain pending. The 21 older tests
requiring the complete inventory package remain unchanged and unrun; no
held-out labels or unselected inventory were used for this work.

The user's instruction to keep new code local remains in force. A future push,
PR or private-data transfer is a separate publication step.
