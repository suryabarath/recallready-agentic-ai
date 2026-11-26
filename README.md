# RecallReady
Evidence-grounded investigation of historical FDA food recalls against simulated retailer inventory, using vector retrieval and four bounded AI agents.

For new development, follow [CONTRIBUTING](CONTRIBUTING.md): start from current
`main`, use a focused branch, and request teammate review through a PR.
[CI setup](docs/CI_SETUP_2026-11-22.md) records workflow verification, the
private source fixture, and the public repository's review and CI rules.

**Local targeted-correction update — 24 November 2026:** the
[implementation guide](docs/TARGETED_CORRECTION_IMPLEMENTATION_2026-11-24.md)
documents opt-in A1/A2 corrections, one shared correction limit, affected-stage
reruns and preserved original results. Existing callers keep upstream escalation
by default. This local change has offline verification and one
[controlled live smoke](docs/TARGETED_CORRECTION_LIVE_SMOKE_2026-11-24.md)
of the normal A1–A4 path with corrections enabled. No live correction occurred.
Human review remains required.
The subsequent [technical review](docs/TARGETED_CORRECTION_REVIEW_2026-11-24.md)
fixes an A1 correction-handoff failure, records the 1,159-test regression and
75 approved development checks, and identifies the local recovery checkpoint.

**Local A1–A4 update — 24 November 2026:** see the
[A4 review and integration guide](docs/A4_REVIEW_AND_INTEGRATION_2026-11-24.md)
for the current optional A3/A4 coordinator path, citation/accounting fixes,
offline verification and remaining correction-policy limits. The historical
stage notes below retain their original dates and test counts. Runtime
datasets and demonstration states remain private and ignored by Git.
The [controlled live A1–A4 pilot](docs/A1_A4_LIVE_PILOT_2026-11-24.md)
records one successful matched-case run with the semantic critic enabled,
independent source/inventory/ledger checks and final human-review routing.

The [A2 development inventory guide](docs/A2_DEVELOPMENT_INVENTORY_2026-11-22.md)
documents a checksum-verified 18-set/36-row subset of the existing synthetic
inventory, its reproduction command and 19 explicit offline dataset checks.
The original 21 full-package-dependent tests remain separate and unrun.

**Local A2 integration — 22 November 2026:** this branch adds optional A2
investigation to the verified A1 coordinator. The
[isolated integration guide](docs/A2_ISOLATED_INTEGRATION_2026-11-22.md)
explains routing, source provenance, synthetic test setup and limitations.
The permitted regression selection passed 969 tests; 21 dataset-dependent
tests remain unrun. A3/A4 integration is pending. The A1 notes below describe
the preceding implementation and live checks.

**A1 handoff — 20 November 2026:** start with the
[technical handoff](docs/A1_HANDOFF_2026-11-20.md) for setup, interfaces,
transfer requirements and pending integration. The
[development record](docs/A1_DEVELOPMENT_RECORD_2026-11-20.md) explains the
implementation stages, module responsibilities, decisions and verified results.

**Coordinator update:** [A1-only coordinator guide](docs/A1_COORDINATOR_GUIDE_2026-11-20.md)
documents the new `CaseRequest`/`CaseState` and real LangGraph routing around
the A1 wrapper. The last full suite passed 912 tests. A live coordinator pilot
for `H-1388-2026` preserved both lot/expiry pairs and correctly ended at
`human_review`; its measured usage and source checks are in the guide.
A2–A4 integration remains pending.

Current implementation: exact source and citation access for all 18 A1
development recalls and 72 evidence passages. The bounded Group A+B adapter
and provisional Group C relationship adapter have offline tests and controlled
live development runs. Member 1 reviewed the reported values in all six Group C
cases; one Group C run initially failed validation and was revalidated offline
after correcting a relation-kind rule. A corrected F-0536-2021 retry includes
the previously omitted item number and UPC, both confirmed by Member 1. Full
FDA vector retrieval is implemented for the 18-record development set; the
four-agent app is pending.

Read the [current 18-record status](docs/A1_18_RECORD_STATUS_2026-11-19.md)
before using historical implementation notes or drafting the submission report.
The [standalone service guide](docs/A1_SERVICE_GUIDE.md) explains
`a1_service.run_a1`, which connects retrieval, exact SQLite evidence,
interpretation, and final validation in one call. Its full request flow has
offline integration coverage for all 18 recalls. The
[first combined live pilot](docs/A1_SERVICE_LIVE_PILOT_2026-11-19.md) passed for
`H-0011-2027`. The [Group B pilot](docs/A1_SERVICE_GROUP_B_LIVE_2026-11-19.md)
also passed for `F-0332-2023`. The
[Group C pilot](docs/A1_SERVICE_GROUP_C_LIVE_2026-11-19.md) passed for
`H-1388-2026`, preserving both lot/expiry pairs. These are three representative
combined live checks, not independent accuracy evaluation.
Storage-failure handling and resource cleanup have additional offline coverage.
The approved [run envelope guide](docs/A1_RUN_ENVELOPE_GUIDE.md) explains
`run_a1_with_trace`, typed outcomes, per-run evidence/usage traces and atomic
ledger links. It has 41 new offline tests and one successful live Group C
regression. The new A1-only coordinator consumes this envelope; full shared
workflow integration remains pending.
Stage 1's [A1 interface record](docs/A1_STAGE1_INTERFACE_PROPOSAL.md) records
Member 1's approval of the provisional Group C envelope. Stage 2's exact FDA SQLite store can be built
locally with `.venv/bin/python fda_store.py runtime/fda_a1.sqlite`; it refuses
to overwrite an existing file. The database is FDA-only and contains no stock
or evaluation labels. The Group A+B CLI can read it with
`--fda-store runtime/fda_a1.sqlite`; both interpreter adapters also accept
`FDAStore` directly. `embedding_inputs.py` verifies all 72 vector-free FDA
staging points against that store. The approved new Qdrant collection name is
`recallready_fda_food_a1_v1`; `qdrant_a1.py` prepares Cloud Inference upload
and exact-source retrieval. The live collection contains 72 verified points,
uses 384-dimensional cosine vectors and keyword indexes for exact recall and
snapshot filters, and passed one filtered retrieval check for each of the 18
development recalls on 19 November 2026.

Start with [A1 implementation reference](docs/A1_IMPLEMENTATION_REFERENCE.md)
for setup, modules, trust boundaries, cost controls, teammate handoff and report
wording. See [verification record](docs/A1_VERIFICATION_2026-11-18.md) for measured
results and limitations. The [six-recall live review](docs/A1_GROUP_A_LIVE_REVIEW.md)
records measured usage and unresolved interpretation issues. No API key is
needed for the offline tests.

The [Group B verification record](docs/A1_GROUP_B_VERIFICATION_2026-11-19.md)
documents the six-recall intermediate expansion, its 574-test result, and the
explicit separation between offline adapter coverage and unrun paid inference.
The [Group C offline record](docs/A1_GROUP_C_OFFLINE_2026-11-19.md) documents
the additional source/citation coverage and the relationship-contract gap.

The [approved ambiguous-code policy](docs/A1_OPTION_A_POLICY_2026-11-19.md)
records the later validator change and its effect on two historical live runs.
Member 1's [case-specific human lot review](docs/A1_HUMAN_LOT_REVIEW_2026-11-19.md)
can be passed explicitly to validation; the default ambiguity rule remains.
The [review workflow](docs/A1_REVIEW_WORKFLOW_2026-11-19.md) documents the CLI's
explicit review-file option, offline results and remaining live verification.
The [targeted live verification](docs/A1_REVIEW_LIVE_RESULTS_2026-11-19.md)
records the subsequent two successful runs with the review policy in place.

```bash
../code_workspace/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py
```
