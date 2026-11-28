# Fresh-clone evaluator workflow verification — 27 November 2026

## Result

The documented offline workflow succeeded in a new GitHub clone with a newly
created virtual environment and freshly downloaded dependencies. No existing
environment, API credentials, usage ledger or live results were copied.

| Check | Actual result |
|---|---|
| Application revision cloned from GitHub main | `3e9f72fba27704da83a7a4f80046c742605ac98e` |
| Environment | macOS, Python 3.13.6; new project-local virtual environment |
| Install pinned direct dependencies | Succeeded |
| pip check | No broken requirements |
| FDA ZIP and selected inventory validation | Passed: 18 recalls, 72 passages, 18 sets/36 rows |
| FDA SQLite build from original ZIP | Succeeded |
| Permitted regression suite | 1,168 passed in 12.21 seconds |
| Explicit development/demo suite | 75 passed in 3.53 seconds |
| Fresh A1–A4 demo | Matched, no-match and early-review routes verified |
| Saved states and demo checksums | Passed |
| Relative links in the three draft run documents | Passed |

JUnit results had zero failures, errors and skipped tests within the selected
suites. The existing 21 historical full-package tests remained excluded;
they were not adapted or counted as passed.

## What was actually provisioned

The application was cloned from the GitHub `main` branch into a new temporary
parent directory. Only the draft README, dataset guide and evaluator guide
were overlaid to verify their current instructions; application code came
from the remote checkout.

Approved local copies supplied the original FDA ZIP and the three selected
inventory JSON files. The ZIP remained intact without extraction. The source
path and imported application modules resolved inside the fresh checkout.
The private environment file and persistent usage ledger were absent.
Application API credentials and external tracing credentials were removed
from the test process environment.

Dependencies were installed into a new virtual environment from
`requirements.txt`; the developer's existing environment was not copied.
The six directly pinned package versions matched the requirements.
Transitive dependencies were newly resolved and recorded with `pip freeze`.
This is not a full transitive dependency lockfile.

Only package download/GitHub access used the network. Tests and the demo used
their existing simulated OpenAI/Qdrant responses with actual local source,
SQLite, matching, planning, coordinator and validation code.

## Commands verified

From the fresh repository root:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -q -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -B fda_store.py runtime/fda_a1.sqlite

.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short

.venv/bin/python -B tests/a2_development_demo.py \
  --enable-a3 --enable-a4 --output runtime/evaluator_demo
```

The execution also performed the README input-validation command, wrote
JUnit reports outside the clone, checked installed module locations and
reloaded the three saved states. Existing output directories were not reused.

## Demonstrated outcomes

- H-0011-2027: A2 matched, A3 planned, A4 human-review verdict.
- F-0818-2023: A2 no-match, A3 planned, A4 human-review verdict.
- H-1388-2026: A1 human-review stop before A2/A3/A4.

All final states retained human review. A4 in this demo was deterministic;
the live semantic critic was not invoked.

## Evidence and remaining handoff work

The execution script is preserved locally as
`runtime/verify_evaluator_fresh_clone_20261127.zsh`. Logs, environment list,
JUnit XML, clone location and `result.json` are under
`runtime/evaluator_fresh_clone_verification_20261127/`. These are local
verification artifacts, excluded from public commits.

Member 1 reported A3/A4 owner review complete with no unique changes needing
additional merges. This is separate from the fresh-clone technical check.

The team still needs to provide a working dataset sharing link and verify
download permissions from another account. This run used approved local
dataset copies and therefore does not establish download-link accessibility.
A teammate should also follow the instructions on their own machine and
record their OS/Python/results. Windows fresh setup was not executed here.

The documentation branch has no application-code or dependency changes.
No paid model requests, new cloud collection, source ZIP edits, dataset
publication, commits, pushes or merges were performed for this check.

## Self-report

Verified a real GitHub clone, new environment installation, source/inventory
validation, both selected pytest suites, demo states/checksums and document
links. No selected tests failed or were skipped. External service responses
were fixtures as documented. Unverified: Windows/another physical machine,
dataset URL permissions, new live model behavior and independent accuracy.
No instruction deviations. Confidence: high for clean setup on the tested Mac.
