# Targeted-correction technical review and local checkpoint

Reviewed locally on `feature/targeted-corrections-local`, based on merged
baseline `e81e5c3`. This is the coding assistant's technical review, not a
teammate's GitHub approval or approval of pending A2 matching policies.
The earlier live-tested checkpoint `a591cde` remains unchanged.

## Scope and decision

Reviewed correction eligibility, source/prompt separation, A1 preservation,
same-store A2 recomputation, typed coordinator handoffs, original/current
history, accounting references, one-attempt limits and terminal review/error
routes. The review covered the changed source and its tests, not held-out data
or an independent model-accuracy evaluation.

One additional defect was reproduced and fixed. The final permitted regression
and approved development checks pass. No further blocking finding was identified
in the reviewed diff. The feature is suitable for a local recovery checkpoint;
live correction-path behavior remains unverified.

## Reproduced defect: invalid A1 handoff escaped the workflow error boundary

**Severity: medium.** Availability and inspectability were affected; this was
not an observed live incident or acceptance of unsupported source facts.

After a valid initial A1/A2/A3/A4 chain, an A1 correction returns another
envelope. A2 and A3 validate proposed handoffs before accepting their state
updates. A1 previously depended on its adapter's validation and returned the
envelope without the equivalent coordinator check.

Four fault-injection probes changed the corrected envelope after the actual
offline adapter completed:

1. Run ID no longer matched the case.
2. Product metadata changed outside the permitted identifier scope.
3. The traced collection changed.
4. The correction-focus trace no longer matched the request.

All four probes initially failed. A later snapshot rejected the malformed A1
result, but the invalid result was already in the pending updates. The outer
handler added an A4 error without removing it. LangGraph's subsequent state
coercion then raised `ValidationError` instead of returning an inspectable
unresolved case. The four exact rejection categories were case/run context,
protected A1 metadata, source/model configuration and correction focus.

### Fix

`A1Coordinator._interpret_a1` now validates the proposed A1 envelope together
with the selected `CaseState` inside its existing exception boundary, before
returning an accepted update. This reuses the established state validators;
no second preservation policy or new error schema was introduced.

An invalid result is not attached to the case. The coordinator returns its
existing safe `coordinator_internal_failure`, with conservative unknown request
outcome, and stops unresolved. The original A1/A2/A3/A4 artifacts, consumed
correction attempt and completed first audit remain available. No downstream
rerun or extra model request follows the malformed handoff.

The rejected current handoff is not a usable trace: it may itself have bad
identity/configuration. It is therefore not fabricated into a trusted A1
failure envelope. Original traces and the existing run-linked ledger remain
the accounting evidence; the current unexpected failure requires inspection.
Normal typed adapter failures still retain their A1 error envelope and trace.

### Regression evidence

`test_invalid_a1_correction_boundary_returns_failure_with_original_audit`
has four parametrized cases. Each now returns unresolved, preserves original
artifacts, records exactly one correction and confirms three actual offline
SDK request boundaries / three ledger entries: initial A1, first A4 and the
rejected corrected A1. No final A4 request is made.

These are intentionally injected handoff failures. External network responses
alone are fixtures; the source, SQLite, adapter, validators and graph execute.
Existing tests were not deleted, skipped or weakened.

## Actual verification after the fix

From `code_workspace`:

```bash
.venv/bin/python -B -m pytest tests/test_targeted_corrections.py \
  -q -p no:cacheprovider --tb=short

.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short
```

Results on 24 November 2026:

- Four new probes before the fix: **4 failed**, demonstrating the defect.
- Complete correction suite after the fix: **67 passed in 2.62 seconds**.
- Final permitted regression: **1,159 passed in 8.18 seconds**; the 67
  correction cases are included, not an additional independent total.
- Final approved development checks: **75 passed in 2.53 seconds**: 18 cases
  in four configurations, one 36-row round trip and two demonstration checks.

The 21 unchanged full-package inventory tests remain outside this selection.
The development checks retain the original two matched, six no-match and ten
early-review routes. All current A3/A4 outcomes retain human review. These
counts are behavior/consistency evidence, not accuracy scores.

## Local checkpoint and publication boundary

Local recovery tag: `a1-a4-corrections-reviewed-2026-11-24`.
The tag identifies the reviewed commit; inspect it with:

```bash
git show --stat a1-a4-corrections-reviewed-2026-11-24
```

The checkpoint includes the correction source, tests, contract, implementation
guide, this review and related README/A4-guide updates. It excludes the separate
submission-readiness proposal, credentials, source ZIP, runtime databases,
private outputs and Qdrant data. The interview reference under the sibling
`project_reference` folder is updated separately; that folder is outside this
code repository. No branch creation or GitHub push, PR, merge or deployment is
part of this review/checkpoint step.

The working feature remains off by default for upstream corrections. Owner
matching-policy sign-off, live correction verification, durable human
approval/resumption, independent evaluation and application hosting remain
separate work. The earlier live pilot does not verify the new correction path.
