# Evaluator and teammate run guide

This guide supplements the [README](../README.md). It covers the current flat
repository and its existing offline/live runners; it does not assume a UI,
notebook or installed Python package exists.

## Choose an execution mode

| Mode | Inputs | External calls | Output |
|---|---|---|---|
| Regression tests | Original FDA ZIP; generated synthetic fixtures | Simulated | pytest results |
| Explicit development checks | FDA ZIP and approved 18-set inventory package | Simulated | 75 dataset/demo checks |
| Offline A1–A4 demo | Same approved inputs | Simulated; deterministic A4 | Three saved states and summary/manifest |
| Optional live runner | Same inputs, FDA store, private keys and existing Qdrant collection | Live and potentially paid | States, diagnostics when enabled, usage and report |

Use the offline workflow for a repeatable evaluator demonstration. Existing
live records are supporting evidence. New live requests are not prerequisites
for running the offline demonstration.

## Fresh-clone procedure

1. Use Python 3.13 and clone the complete repository into `code_workspace`
   inside a new parent directory, as shown in the README.
2. Create a new `.venv` there and install `requirements.txt`. Do not copy a
   developer's existing environment or use an adapted test harness.
3. Obtain the four [approved dataset inputs](../data/README.md). Put the ZIP in
   the sibling `project_reference` directory and the selected inventory files
   in `runtime/a2_development_18_v1`.
4. Run the input validation command and `pip check` from the README.
5. Run the documented regression selection, then the explicit development suite.
6. Run `tests/a2_development_demo.py --enable-a3 --enable-a4` using the virtual
   environment's Python and a new `--output` directory.
7. Read the summary and complete states; record the outcomes before presenting.

All Python commands must run from the repository root. The source archive
path is relative to the source module, not to a user's home directory.

## Windows command substitutions

Windows fresh installation has not been verified by the author of this guide.
These are platform equivalents for a teammate to verify; macOS/Linux shell
examples containing `cp -n` and single-quoted Python commands should not be
pasted unchanged into Command Prompt.

In PowerShell, create the environment with:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Use File Explorer to place the four datasets in the exact folders described
above, or use PowerShell `Copy-Item` with the approved source paths. Replace
every `.venv/bin/python` command with `.\.venv\Scripts\python.exe`.

Regression verification on one line:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --ignore=tests/test_inventory_loader.py --ignore=tests/test_inventory_store.py --ignore=tests/test_a2_agent.py --ignore=tests/test_a2_review_fixes.py --tb=short
.\.venv\Scripts\python.exe -B -m pytest tests/a2_development_inventory_checks.py tests/a2_development_demo_checks.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\python.exe -B tests/a2_development_demo.py --enable-a3 --enable-a4 --output runtime/evaluator_demo
```

## What the evaluator should inspect

Open `runtime/evaluator_demo/summary.json`:

- `network_mode` explicitly identifies fixture responses.
- `a3_enabled` and `a4_enabled` are true.
- Each case supplies its original two inventory rows.
- Matched and no-match cases have an A3 plan, A4 audit and final human review.
- The ambiguous Group C case stops before A2, A3 and A4.
- The individual state files preserve source text, identifiers, provenance,
  findings, plans, audit traces and review reasons.
- `manifest.json` records file checksums.

The three routes are H-0011-2027 (matched), F-0818-2023 (no-match) and
H-1388-2026 (early review). Human review is an intentional final boundary.
A no-match result must not be presented as proof that stock is safe.

The 18-case development suite also exercises the full coordinator with the
targeted-correction feature enabled. No correction occurring in a normal case
does not establish correction-path live coverage. Offline fault tests are
separate evidence.

## Troubleshooting

| Symptom | Check / response |
|---|---|
| FDA ZIP not found | Place the original ZIP at `../project_reference/RecallReady_Agent1_FDA_18_Starter.zip`; a Git clone alone does not supply it |
| ZIP/package checksum mismatch | Obtain the approved version; preserve the failing copy rather than editing evidence or checksums |
| Development package missing | Supply all three selected JSON files at the default runtime path |
| Plain pytest fails on inventory setup | Use the documented selection; the excluded 21 tests need a different frozen full-package fixture |
| Output directory already exists | Choose a fresh output path; builders intentionally refuse overwrite |
| Import error | Run from repository root, use its virtual environment, and keep all source/tests together |
| Dependency conflict | Recreate a new environment and install the pinned direct dependencies; run pip check |
| Live environment variable missing | Privately export the three credentials; the code does not automatically load .env |
| Live record unresolved | Inspect saved error and optional private diagnostics; preserve the original run and do not weaken validation |
| Budget/reservation failure | Inspect the existing ledger before any further live request; do not reset it to bypass accounting |

## Team handoff and remaining submission work

Member 1 reported A3/A4 owner review complete with no unique branch changes
remaining. This does not require merging historical agent branches again.

This setup guide and the selected data can support teammate reproduction.
An actual teammate test on another machine is a separate confirmation; a
fresh clone on the same Mac does not establish Windows support or independent
owner testing.

The required final submission still needs a 5–10-page PDF report, a
contribution table immediately after its cover, a presentation following the
report sequence, executable source, a working dataset link and these run
instructions. The report/presentation should distinguish offline tests,
the original 18-record live batch and the separate F-1472-2024 live follow-up.
Streamlit is optional under the supplied submission requirements.
