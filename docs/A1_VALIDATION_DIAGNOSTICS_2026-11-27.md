# RecallReady — A1 Validation Diagnostics and Live Follow-up
Date: 27 November 2026
Record: F-1472-2024 / event 94806 / CASE-005 / SIMSET-005

## Outcome

The single authorized live follow-up returned validated A1 facts and final human_review. The complete literal phrase `06-04-24 08/04/2024` was preserved as `other`, with uncertainty. A2, A3 and A4 correctly remained unrun.

The original 18-record batch still records 17 validated A1 results and one unresolved result. Its artifacts and evidence ZIP were verified unchanged. This follow-up is a separate measurement with a revised prompt, not a replacement of the original failure.

## Original issue and evidence limit

FDA code_info is exactly `LOT # 06-04-24 08/04/2024`. The original live batch retrieved all four correct passages but rejected the model interpretation with the broad public error citation_source_failed. The old adapter did not retain the rejected proposal or specific failed rule, so the exact original offending interpretation remains unknown.

Member 1's approved representation is the complete phrase as other with uncertainty. It does not establish an expiry date or a confirmed lot. No special human lot override is required for that representation.

## Implementation

- interpreter.py: clarified that multiple unlabeled date-like parts under a LOT label remain one complete other span with uncertainty. No literal recall-specific answer was added to the prompt. Validation rejections now expose a specific reason through optional private diagnostics.
- validation.py: added reason codes to ContractError and tagged ambiguity, incomplete-span, unsupported-label, required-identifier and missing-uncertainty failures. The acceptance/rejection conditions and public error code are unchanged.
- a1_diagnostics.py: opt-in ContextVar capture of rejected proposals, rule details, source context, response ID and ledger link. Capture is reset after its scope ends. Default callers retain no additional proposal diagnostics. These records are untrusted data and never become model instructions.
- tests/test_a1_diagnostics.py: nine additional tests exercise whole-span acceptance, seven invalid variants and scoped diagnostic isolation using the real validator with offline SDK responses.
- scripts/run_live_development_18.py: added optional single-recall execution and private diagnostic persistence. Captures exact application hashes and changed application source copies so local changes are identifiable independently of the base commit.

The live follow-up ran with uncommitted changes on `fix/a1-ambiguity-diagnostics`, based on main commit `fd1c5c2e86cdc864c5334ab4e0b27b9a607ed581`. The exact application hashes and modified source copies are retained in its private artifacts. This PR publishes the implementation, tests and runner after the subsequent [pre-merge verification](A1_FIX_PREMERGE_VERIFICATION_2026-11-27.md). The unrelated submission-readiness proposal and private artifacts are excluded.

## Offline verification

| Selection | Actual result |
|---|---|
| Diagnostics + interpreter + contract tests | 265 passed in 1.29s |
| Full permitted regression | 1,168 passed in 7.65s |
| Explicit 18-record development/demo checks | 75 passed in 2.23s |
| Ruff E9/F/B on the five changed/new Python files | Passed |
| git diff --check | Passed |

Counts overlap and must not be added as independent coverage. The four historical full-package modules containing 21 tests remain outside the established regression selection; no tests were weakened, deleted or silently skipped.

Executed from code_workspace:

```text
.venv/bin/python -B -m pytest tests/test_a1_diagnostics.py tests/test_interpreter.py tests/test_task02b.py -q -p no:cacheprovider --tb=short

.venv/bin/python -B -m pytest -q -p no:cacheprovider --ignore=tests/test_inventory_loader.py --ignore=tests/test_inventory_store.py --ignore=tests/test_a2_agent.py --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short

.venv/bin/ruff check --no-cache --select E9,F,B a1_diagnostics.py interpreter.py validation.py tests/test_a1_diagnostics.py scripts/run_live_development_18.py
```

## Live follow-up

After privately loading environment variables:

```text
.venv/bin/python -B scripts/run_live_development_18.py --recall F-1472-2024 --capture-validation-failures --output runtime/live_f1472_diagnostics_20261127
```

Run ID: `live18-5b20cb01-a4fb-439a-ae14-ddf58e1bd0c0-F-1472-2024`.

| Field | Observed value |
|---|---|
| Source snapshot | FDA-FOOD-2026-10-23-USER-SNAPSHOT |
| Qdrant collection | recallready_fda_food_a1_v1 |
| Model | gpt-6-luna; SDK retries 0 |
| A1 status | validated |
| Identifier kind | other |
| Identifier value | 06-04-24 08/04/2024 |
| Scope note | LOT # 06-04-24 08/04/2024 |
| Evidence ID | EV-F-1472-2024-CODE_INFO |
| Uncertainty | Meanings/boundaries of the two date-like parts remain unresolved; package relationship unspecified |
| Final case status | human_review |
| A2 / A3 / A4 | Not run due to A1 uncertainty |
| Requests / structural repairs / workflow corrections | 1 / 0 / 0 |
| Elapsed case time | 5.849 seconds |
| Ledger entry | 62, settled |
| Input tokens | 953 |
| Output tokens | 177, including 71 reasoning tokens |
| Estimated OpenAI usage | USD 0.000184 |

The estimate uses the existing local rates, is not a provider invoice, and excludes Qdrant charges and taxes. This follow-up used a USD 0.005 additional local estimate allowance and the existing persistent ledger.

## Artifact and provenance verification

Private outputs are under code_workspace/runtime/live_f1472_diagnostics_20261127.

- cases/F-1472-2024.json: complete state and trace.
- cases/F-1472-2024.diagnostics.json: empty array because this attempt had no validation rejection.
- cases/F-1472-2024.result.json: per-case outcome.
- summary.json, results.csv, ledger_calls.json: execution/accounting record.
- application_sources/: exact modified application source copies.
- run_live_development_18.py: runner copy.
- REPORT.md and manifest.json: generated record and file checksums.

Independent checks reloaded CaseState, revalidated A1 against the original ZIP, verified the exact leading-zero phrase and required uncertainty, confirmed no downstream stages ran, matched ledger entry 62 to its run/response/settled usage, verified all 11 manifest files and private permissions, and found no unsettled ledger reservation.

The original batch's 41 manifest file hashes and original evidence ZIP SHA-256 remained unchanged.

## Interpretation and remaining limits

The revised prompt produced an acceptable response in this one follow-up. This does not prove the original failure's exact cause, repeated-run stability, independent accuracy or semantic completeness. Rejected-proposal diagnostics were verified through offline failure tests; the live follow-up did not trigger a rejection.

No source text, identifier policy, review gate or architecture changed. No automatic semantic retry was added. A successful diagnostic follow-up does not authorize stock action or remove human review.

## Self-report

Verified the focused and full offline suites, selected-data checks, static checks, one real live follow-up, source validation, accounting and immutable historical evidence. No fixture responses were used for the live call. The historical 21 full-package tests and exact original rejected proposal remain unverified. No instruction deviations or additional paid reruns. Confidence is high for the measured follow-up; original root cause and repeated-run reliability remain open.
