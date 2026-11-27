# Targeted-correction PR verification — 26 November 2026

The reviewed application checkpoint is `c3961432667dff8864fc2af1a26522194a3c7b28`,
based on merged `e81e5c3`. This follow-up adds the existing controlled live
smoke runner and record, and aligns the README and implementation links.
The smoke runner now closes its inventory/client contexts before removing the
temporary directory, including on platforms that lock open SQLite files.
The separate submission-readiness proposal is excluded.

## Behavior and scope

Opt-in A1/A2 correction permits one targeted correction with affected-stage
reruns, protects original evidence and unrelated facts, retains the original
chain and accounting, and preserves final human review. Existing callers
keep upstream escalation by default. A2 matching rules are reused unchanged.
Member 2 explicitly approved Option A for the selected development scope:
batch identifiers may match inventory lot_code exactly with provenance,
while the full A1–A4 workflow still ends at human review.

Member 2's historical 14 legacy-test passes used an adapted in-memory harness;
the historical matrix was standalone A2/diagnostic evidence. Those results
are not counted as native test passes here or as verification of the newer
correction branch. The submitted Windows file hashes matched the earlier
merged baseline. The handoff review and owner submissions remain in the
local project_reference archive, outside this public PR.

## Actual offline verification

From code_workspace:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short

.venv/bin/python -m pip check
```

Results: **1,159 passed in 7.21 seconds**; **75 development checks passed in
2.07 seconds**; **no broken requirements found**. The 67 correction tests are
included in the regression total. The development run uses only the approved
18 cases/36 synthetic inventory rows and fixture external responses.
The 21 full-package inventory tests remain outside this selection; an earlier
attempt at two of those modules stopped at fixture setup. No tests were
weakened and no held-out labels were used.

## Live evidence and limits

The existing 24 November smoke ran the normal A1–A4 path with corrections
and the A4 semantic critic enabled, ended at human review, and performed
**zero corrections**. See TARGETED_CORRECTION_LIVE_SMOKE_2026-11-24.md.
No new live request was made for this publication step. The smoke runner's
syntax was checked; its paid path was not rerun. Correction/failure paths
have offline evidence only. Durable approval/resumption and independent
accuracy evaluation remain future work.

## Publication boundary

The PR contains code, tests and documentation. The FDA source ZIP, selected
inventory, private states, ledger, credentials and Qdrant contents are excluded.
The existing recovery tag still identifies c396143. A teammate other than the
author must review the PR, and GitHub CI must pass before merge. Local results
do not establish hosted CI success.

## Static-quality follow-up before publication

Ruff 0.14.6 was installed as local development tooling without changing
application requirements. The first scan found unused imports and shared
pytest-fixture import warnings. Two unused imports were removed; the two
changed test modules now register test_a1_service through pytest_plugins.
No assertions or expected results changed.

```bash
.venv/bin/ruff check --no-cache --select E9,F,B \
  a1_run.py a1_service.py a1_trace.py a4_agent.py a4_checks.py \
  case_state.py coordinator.py corrections.py interpreter.py \
  tests/a2_development_inventory_checks.py \
  tests/live_targeted_correction_smoke.py tests/test_targeted_corrections.py
```

All selected Ruff checks passed on these 12 Python files. After the fixes,
the correction/development selection passed **142 tests in 3.66 seconds**
(67 correction tests plus 75 development checks). The full permitted
regression then passed **1,159 tests in 7.20 seconds**. pip check reported
no broken requirements; git diff --check passed. Test counts overlap and
must not be summed as independent coverage.

These checks cover Python errors, unused names/imports and selected common
bug patterns. They do not establish static typing, full formatting compliance,
a dependency vulnerability audit, Windows smoke execution, or live correction
behavior. Ruff is not added as a new required CI gate in this PR.
