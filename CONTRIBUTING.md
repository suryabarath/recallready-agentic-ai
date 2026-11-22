# Contributing to RecallReady

Start each task from the latest `main`, create a focused branch, and open a
pull request targeting `main`. Use names such as `feature/a3-planner` or
`fix/a2-package-comparison`. Each branch contains the application; branch
names describe the work, not separate deployed agents.

Keep unrelated agent work in separate pull requests. Coordinate changes to
`case_state.py` and `coordinator.py` with the integration owner. Preserve the
approved inner A1 contracts and source text. Attribute reused teammate code
and describe any new or changed matching policy in the PR.

The PR author records the test command, actual result, data used and remaining
limitations. A different teammate reviews the affected contract and behavior.
The maintainer merges after review and appropriate tests, then developers
start subsequent work from updated `main`. Retire completed feature branches
only after verifying their work is merged; retain agreed recovery tags.

## Offline verification

Install `requirements.txt` in a local virtual environment. Keep the original
FDA starter ZIP at `../project_reference/RecallReady_Agent1_FDA_18_Starter.zip`.
Run from the repository root:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py
.venv/bin/python -m pip check
```

This selection includes exact FDA source validation and generated synthetic
inventory integration tests. The four excluded modules currently contain
21 tests that need the frozen inventory file. They remain part of the project;
the command above does not establish their results or independent accuracy.
Do not use held-out scenarios or labels to develop or tune agent behavior.

Keep `.env`, `.venv`, runtime ledgers and private live results outside commits.
Use a separate, explicitly scoped request for live model or Qdrant testing.

## Review and enforcement

The policy is a pull request, one teammate approval and a successful
`offline-regression` check before changes reach `main`. The repository is
public. Its active `Protect main` ruleset requires one approving review, the
successful GitHub Actions `offline-regression` check, up-to-date branches and
resolved review conversations. New code changes dismiss stale approvals.
Deletion and force pushes are blocked, with no bypass actors.

The FDA fixture is provisioned as a repository Actions secret. Actual hosted
results appear in the PR checks and Actions page; local results alone do not
establish CI success. See [CI setup](docs/CI_SETUP_2026-11-22.md).
