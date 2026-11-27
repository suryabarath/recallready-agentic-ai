# Controlled live smoke with corrections enabled — 24 November 2026

Member 1 authorized the next step after local checkpoint `c396143`.
One `H-0011-2027` / `CASE-001` development case ran through the compiled
A1→A2→A3→A4 coordinator with both the semantic critic and targeted corrections
enabled. The run used the original two synthetic rows in `SIMSET-001`, the
existing FDA SQLite store and Qdrant collection, and the existing usage ledger.

**Outcome:** `human_review`. A1 validated all four FDA passages. A2 returned
one exact finding for `INV-001-A`, lot `26078`, UPC `850041392103` and 12
simulated packages. A3 planned review. A4 ran its four deterministic checks and
the live semantic critic, returned zero findings, and retained human review.
The event sequence was:

```text
started → a1_validated → a2_matched → a3_planned
        → a4_human_review → human_review
```

**Correction count: zero.** This verifies the normal live flow with corrections
enabled. It does not verify that a real A1/A2 correction request will be
generated or resolved; fault-injected correction paths have offline coverage.
No real inventory action or human approval was executed.

## Scope and cost

The runner was `tests/live_targeted_correction_smoke.py`, on local branch
`feature/targeted-corrections-local`. Its preflight found 33 settled ledger
calls, $0.008612 in historical estimated usage and no unsettled reservation.
It set a **$0.02 cumulative local ledger ceiling** and used the existing ledger,
not a fresh one. SDK retries were disabled. The cap is local accounting, not a
provider billing limit or an invoice.

| Stage | Ledger ID | Input tokens | Output tokens | Included reasoning tokens | Historical estimated USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 | 34 | 935 | 110 | 0 | 0.000149 |
| A4 | 35 | 2,014 | 190 | 154 | 0.000297 |
| Total | Two requests | 2,949 | 300 | 154 | **0.000446** |

The shared ledger now accounts for **$0.009058** in total. These estimates use
the project's historical pilot rates and exclude separate Qdrant inference
charges. Reasoning tokens are included in output tokens and are not added
again. No structural repair or correction replay occurred.

## Private artifact and independent validation

Run ID: `live-corrections-b61df334-fdcf-485e-b0b4-e9819f3ea99f`.

Ignored local artifact directory:
`runtime/a1_a4_corrections_live_20261124T141835845158Z/`.
It contains `state.json` and `summary.json` with directory mode `0700` and
file mode `0600`. State SHA-256:
`dfd6f6ddad915b5037caf497bdf0d0040e4be5ae27886e879a89cd765d95323d`.
The runner used a temporary, case-scoped inventory SQLite database and checked
that its bytes did not change during the run.

A separate read-only verification reloaded the state as `CaseState`, checked
its checksum and permissions, validated A1 against exact FDA SQLite passages,
confirmed all four retrieved point/evidence IDs, compared the A2 finding with
the selected original inventory row, recomputed the pure product/lot comparison,
validated A3 against A2, inspected A4's checks and zero findings, and matched
both model traces to ledger calls 34 and 35 including response IDs, tokens and
settled charges. It also checked the starter ZIP hash and the total ledger
against the $0.02 local ceiling. All checks passed.

The first runner invocation failed before any network call because direct
execution from `tests/` did not include the project root on Python's import
path (`ModuleNotFoundError: No module named 'case_state'`). The runner was
aligned with the existing demo runner's import setup and retried. The second
invocation completed as described above. That initial failure created no
ledger entry or model request.

No new pytest run was needed for this live execution: the preceding reviewed
checkpoint had 1,159 passing permitted regressions and 75 approved development
checks, and only the standalone runner was added afterward. No held-out labels
or unselected inventory objects were accessed. The runner and this record are
local, uncommitted follow-up work; the checkpoint tag still identifies the
earlier reviewed code.
