# A1 ambiguity diagnostics: pre-merge verification

The original live failure for F-1472-2024 retained a broad error but not the
rejected proposal or failed rule. This change adds opt-in private diagnostics
and clarifies the existing complete-span ambiguity instruction. It keeps the
public error contract, identifier acceptance rules and human-review gates.

The [implementation and live follow-up](A1_VALIDATION_DIAGNOSTICS_2026-11-27.md)
records the successful single-record follow-up and its limitations. This
document records the later verification on the same application files before
publication. The application file hashes matched the live follow-up; no new
paid request was needed for publication.

## Actual checks on 27 November 2026

| Check | Actual result |
|---|---|
| Full permitted regression | 1,168 passed in 7.42 seconds |
| Explicit development/demo suite | 75 passed in 2.39 seconds |
| Independent compiled-coordinator diagnostics probes | 3 passed |
| Fresh A1–A4 offline demo | 3 routes verified |
| Ruff E9/F/B on changed/new Python files | Passed |
| Dependency consistency and git diff --check | Passed |

Both JUnit reports were inspected: zero failures, errors or skipped tests
within the selected suites. The existing four excluded modules contain 21
full-package inventory-dependent tests; they are not counted as passed.
Counts overlap in behavioral coverage and are not an accuracy score.

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short

.venv/bin/ruff check --no-cache --select E9,F,B \
  a1_diagnostics.py interpreter.py validation.py \
  tests/test_a1_diagnostics.py scripts/run_live_development_18.py

.venv/bin/python -B -m pip check
git diff --check
```

Ruff 0.14.6 is local development tooling, not an application dependency.

## Development and end-to-end scope

All 18 approved development recalls ran in four configurations: A1/A2,
A1/A2/A3, A1/A2/A3/A4, and A1/A2/A3/A4 with targeted corrections enabled.
Each configuration produced two matched, six no-match and ten early-review
outcomes. The remaining three development checks cover the selected inventory
round trip and existing demo tests. Network responses were fixtures; actual
local source validation, matching, SQLite and graph code executed.

A fresh three-route demo verified matched H-0011-2027, no-match F-0818-2023
and early-review H-1388-2026. States reloaded through CaseState validation and
their manifest checksums passed. A4 in this demo was deterministic.

Independent compiled-coordinator probes enabled all stage/correction flags:

- The complete F-1472-2024 phrase as `other` with uncertainty reached human
  review and produced no diagnostic rejection record.
- An unsupported confirmed-lot interpretation stopped unresolved with private
  rule `ambiguous_lot_requires_review`.
- An invented evidence reference stopped unresolved with private rule
  `identifier_citation_invalid`.

Both rejection probes retained the rejected proposal, response ID and ledger
identity privately, while preserving public `citation_source_failed`.
Each probe made one simulated model request and vector query, performed no
downstream inventory query or retry, preserved inventory bytes, and retained
the run-to-ledger link. The private probe script and artifacts are under
`runtime/a1_fix_premerge_verification_20261127/`, alongside JUnit and demo
outputs. They are excluded from the public PR.

## Publication and limits

Publish only application changes, tests, the reproducible live runner and
technical documentation. Source ZIPs, selected inventory, rejected model text,
runtime states, ledgers, credentials and evaluator evidence archives remain
private. No new dependencies or CI exclusions were added.

The single live follow-up validated the approved complete `other` phrase and
ended at human review with one settled request, estimated USD 0.000184. It is
separate from the original 18-record batch, whose one unresolved case remains
unchanged. The original rejected proposal is unavailable, so its precise cause
is not established. Independent accuracy, repeated live stability, production
readiness and live correction behavior are not established by these checks.

A teammate other than the author must review this PR, and hosted CI must pass
for its latest commit before merge. Local results alone do not establish that
CI status or approval.
