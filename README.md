# RecallReady

RecallReady investigates historical FDA food recalls against synthetic retailer inventory.
It combines exact source validation, Qdrant retrieval and a bounded A1–A4 coordinator.
Plans and audits retain human review; the program performs no stock actions or safety clearance.

## Current version

The verified application baseline is `3e9f72f`, merged through PR #7 on 27 November 2026.
Recovery tag: [`a1-a4-diagnostics-verified-2026-11-27`](https://github.com/suryabarath/recallready-agentic-ai/tree/a1-a4-diagnostics-verified-2026-11-27).

A1–A4 integration, opt-in targeted corrections and private A1 validation diagnostics are implemented.
Member 1 confirmed A3/A4 owner review and reported no unique changes needing additional merges.
This is team-reported confirmation, separate from automated verification.

Scope: **18 development recalls, 72 FDA passages and 36 synthetic inventory rows**.
The runnable offline demo is a terminal command; there is no Streamlit application or installed-package entry point.

## Code flow and important modules

```text
FDA ZIP -> exact evidence store -> filtered vector retrieval -> A1 interpretation
                                                                |
                                              uncertainty/error -> review/unresolved
                                                                |
                                       case-scoped inventory -> A2 matching
                                                                |
                                                   A3 review plan -> A4 audit
                                                                |
                                                   human review / unresolved
```

| Component | Responsibility | Important files |
|---|---|---|
| A1 | Interpret identifiers, preserve relationships and validate source/citations | `source.py`, `fda_store.py`, `a1_service.py`, `a1_run.py`, `interpreter.py`, `group_c_interpreter.py`, `validation.py`, `citations.py` |
| Retrieval | Rank FDA-only passages and resolve every hit against exact source | `embedding_inputs.py`, `qdrant_a1.py` |
| A2 | Compare validated scope with selected synthetic inventory | `a2_agent.py`, `inventory_loader.py`, `inventory_store.py`, `inventory_match.py` |
| A3 | Build a deterministic plan requiring human review | `a3_agent.py` |
| A4 | Audit evidence/inventory/plan consistency; optional semantic critic | `a4_checks.py`, `a4_agent.py` |
| Coordinator | Route typed results and limit targeted correction to one | `coordinator.py`, `case_state.py`, `corrections.py` |
| Diagnostics | Capture rejected A1 proposals privately when enabled | `a1_diagnostics.py` |

Keep the complete flat module layout, `tests/` and `docs/` together.
The offline demo imports reviewed test helpers.

## Prerequisites and data access

Use **Python 3.13**, Git and a new virtual environment. Python 3.13 is used in the
recorded macOS verification and hosted Ubuntu CI. Installing packages requires internet;
the offline tests/demo need no API credentials.

A clone does **not** include runtime datasets. Obtain approved inputs from Member 1:
[data access and placement guide](data/README.md). A working evaluator download link
has not yet been supplied; the team must provide it and verify access before submission.

```text
recallready/
├── project_reference/
│   └── RecallReady_Agent1_FDA_18_Starter.zip
└── code_workspace/                  Git checkout
    ├── *.py, requirements.txt, scripts/, tests/, docs/
    └── runtime/a2_development_18_v1/
        ├── inventory_development.json
        ├── cases_development.json
        └── manifest.json
```

Preserve the ZIP without extraction or editing. The full 40 MB evidence dataset,
evaluation labels and credentials are not inputs to this offline demo.

## Quick start: macOS/Linux terminal

### 1. Clone and install

Run in a new parent directory:

```bash
mkdir recallready
cd recallready
git clone https://github.com/suryabarath/recallready-agentic-ai.git code_workspace
cd code_workspace
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

To select the exact application baseline, use
`git switch --detach a1-a4-diagnostics-verified-2026-11-27`.
See the [evaluator guide](docs/EVALUATOR_RUN_GUIDE.md) for Windows substitutions.

### 2. Place and validate approved inputs

From `code_workspace/`, replace the example paths with those supplied by Member 1.
Use a fresh checkout and the same approved dataset version.

```bash
mkdir -p ../project_reference runtime/a2_development_18_v1
cp -n "/path/to/approved/RecallReady_Agent1_FDA_18_Starter.zip" ../project_reference/
cp -n "/path/to/approved/a2_development_18_v1/inventory_development.json" runtime/a2_development_18_v1/
cp -n "/path/to/approved/a2_development_18_v1/cases_development.json" runtime/a2_development_18_v1/
cp -n "/path/to/approved/a2_development_18_v1/manifest.json" runtime/a2_development_18_v1/

.venv/bin/python -B -c 'from pathlib import Path; from source import Source; from development_inventory import load_development_package; s=Source(); _, cases, manifest=load_development_package(Path("runtime/a2_development_18_v1"), s); print(s.snapshot_id, manifest["counts"])'
```

Expected: 18 recalls, 18 inventory sets and 36 inventory rows. Source loading also
checks all 72 passages. An alternative original-package selection command is in
[data/README.md](data/README.md).

### 3. Run offline tests

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py --tb=short

.venv/bin/python -B -m pytest \
  tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py \
  -q -p no:cacheprovider --tb=short
```

Recorded post-merge results: **1,168 regression passes** and **75 explicit development checks**.
The four excluded modules contain **21 historical full-package inventory-dependent tests**;
they remain outside this selection and are not counted as passed. Plain `pytest` includes them.
The 75 checks cover 18 records in four configurations, a SQLite round trip and two demo tests.
These results establish checked development behavior, not independent accuracy.

A [fresh-clone verification](docs/FRESH_CLONE_VERIFICATION_2026-11-27.md) also
installed dependencies in a new environment and passed both selections and the demo.

### 4. Run the offline A1–A4 demo

```bash
.venv/bin/python -B tests/a2_development_demo.py \
  --enable-a3 --enable-a4 --output runtime/evaluator_demo
```

Open `runtime/evaluator_demo/summary.json` and the three complete case-state JSON files.
Use a new output directory each time; the runner refuses to overwrite results.

| Case | Expected route |
|---|---|
| H-0011-2027 | A1 validated → A2 matched → A3 planned → A4 audit → human review |
| F-0818-2023 | A1 validated → A2 no-match → A3 planned → A4 audit → human review |
| H-1388-2026 | A1 validated → human review before A2 |

This demo uses **simulated OpenAI/Qdrant responses** with real local source validation,
SQLite, matching, planning and coordinator code. A4 performs its deterministic audit.
There are no project API charges for this command.

## Optional live execution

Live execution needs private process environment variables `OPENAI_API_KEY`, `QDRANT_URL`
and `QDRANT_API_KEY`. The application does not automatically load `.env`.
The existing collection is `recallready_fda_food_a1_v1`, with
`sentence-transformers/all-minilm-l6-v2`, 384-dimensional cosine vectors and exact
recall/snapshot filters. The approved model is `gpt-6-luna`.
Do not recreate the collection for an evaluator run.

Build the FDA-only store once, only if it does not already exist:

```bash
.venv/bin/python -B fda_store.py runtime/fda_a1.sqlite
```

With credentials loaded, local preflight sends no OpenAI/Qdrant requests:

```bash
.venv/bin/python -B scripts/run_live_development_18.py \
  --recall F-1472-2024 --preflight-only --output runtime/live_evaluator_case
```

**This next command makes live, potentially paid requests:**

```bash
.venv/bin/python -B scripts/run_live_development_18.py \
  --recall F-1472-2024 --capture-validation-failures \
  --output runtime/live_evaluator_case
```

The runner reuses `runtime/a1_usage.sqlite`, disables SDK retries and permits an additional
local estimated allowance of USD 0.005 for one record or USD 0.05 for an 18-record batch.
Omitting `--recall` selects all 18. Review gates remain active; not every record reaches A4.
The ledger is not a provider spending cap. Preserve any historical ledger and review
unsettled reservations rather than resetting it.

Rejected-proposal diagnostics are opt-in, private, untrusted and never used as instructions.
Keep credentials, runtime states, raw diagnostics and ledgers outside public commits.

## Results, limits and reference documents

The original 27 November live batch had 17 validated A1 results: eight completed A1–A4
and nine stopped for A1 review. One record, F-1472-2024, stopped unresolved.
A **separate single-record live follow-up** validated its whole phrase as `other`
with uncertainty and ended at human review. The original batch remains unchanged;
the follow-up is not an 18/18 rerun.

Independent held-out accuracy, repeated live stability, live correction execution,
durable approval/resumption, stock actions and production hosting remain unverified
or unimplemented. Source checks do not prove semantic completeness; A2 no-match
does not mean stock is safe.

| Reference | Purpose |
|---|---|
| [Evaluator guide](docs/EVALUATOR_RUN_GUIDE.md) | Fresh-clone handoff and troubleshooting |
| [Fresh-clone verification](docs/FRESH_CLONE_VERIFICATION_2026-11-27.md) | Actual clean-install results and remaining handoff limits |
| [Dataset guide](data/README.md) | Input identities, access and placement |
| [A1 diagnostics/live follow-up](docs/A1_VALIDATION_DIAGNOSTICS_2026-11-27.md) | Failure handling and separate live result |
| [Pre-merge verification](docs/A1_FIX_PREMERGE_VERIFICATION_2026-11-27.md) | Commands, test scope and results |
| [Targeted corrections](docs/TARGETED_CORRECTION_IMPLEMENTATION_2026-11-24.md) | Correction design and preserved history |
| [A3](docs/A3_REVIEW_AND_INTEGRATION_2026-11-24.md), [A4](docs/A4_REVIEW_AND_INTEGRATION_2026-11-24.md) integration | Dated technical records |
| [Contributing](CONTRIBUTING.md), [CI setup](docs/CI_SETUP_2026-11-22.md) | PR workflow and hosted checks |

Older dated documents retain historical counts and pending-stage statements.
Use this README for the current procedure. Dataset access, the final PDF report
and presentation are separate submission deliverables.
