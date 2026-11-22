# Agent 2 development inventory preparation and checks

## Prepared data and scope

The existing `02_retailer_inventory_SYNTHETIC.json` contains inventory for all
18 A1 development recalls. No new synthetic stock was generated. The selector
joins A1's fixed recall IDs to catalog rows explicitly marked `development`,
then copies the corresponding 18 sets and 36 inventory records unchanged.
The FDA snapshot remains `FDA-FOOD-2026-10-23-USER-SNAPSHOT`.

Local output is `runtime/a2_development_18_v1/`, which is ignored by Git:

| File | Contents |
| --- | --- |
| `inventory_development.json` | Synthetic flag, snapshot and the 36 original inventory rows |
| `cases_development.json` | The 18 development catalog rows plus canonical FDA event IDs |
| `manifest.json` | Version, counts, source inventory/catalog hashes and output checksums |

`development_inventory.py` verifies the inventory and catalog against the
original package's `SHA256SUMS.txt` before selection. It checks the catalog
column contract, development split, snapshot, exact A1 recall coverage,
distinct case/set/item IDs, row schema and A/B pairs. Catalog split metadata
selects the cases; item suffixes verify the original package structure and
are never matching evidence.

Only selected inventory object bodies are JSON-decoded. Other object bodies
are scanned past, and evaluation-label files are never opened. Literal row
values, including leading zeros, blank attributes, notes, quantities and
deliberately different lots, remain unchanged. No label is added to inventory
or A1 prompts. Checksums detect accidental changes; they do not authenticate
a maliciously replaced source package and checksum list together.

The original source files and starter ZIP remain unchanged. New output files
use mode `0600`. Existing output directories are refused rather than overwritten.
The manifest is written last; incomplete exports fail validation.

## Reproduction

From the repository root with its existing environment and FDA ZIP:

```bash
.venv/bin/python -B development_inventory.py \
  "/path/to/RecallReady_FDA_Retail_Datasets_v1" \
  runtime/a2_development_18_v1
```

The source package must contain the original inventory JSON, case catalog and
checksum list. The selector does not open the package's gold-label files,
prebuilt database or broader FDA source. Choose a new output path if a package
already exists; do not delete or overwrite a previous result to rerun export.

Run the actual development-data checks explicitly:

```bash
.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  -q -p no:cacheprovider -o junit_family=xunit1 \
  --junitxml=runtime/a2_development_18_checks.xml
```

The default input is the output directory above. Set
`RECALLREADY_A2_DEVELOPMENT_DIR` to another prepared package if needed.
Its file checksums, counts and case contexts are validated before use. Missing
or altered data fails the explicit command; no check silently skips itself.

The explicit filename is outside default pytest filename discovery because
the private development package is not available in an ordinary checkout or
the existing CI fixture. Its source is retained in Git, while data and JUnit
results stay in ignored runtime storage. CI continues to run the normal
permitted suite, including generated-input selector tests.

## Actual verification

The exporter tests passed **13 tests in 0.13 seconds** using generated fixtures.
The broader permitted regression selection then passed **990 tests in 5.07
seconds**, including those 13 new tests. Its command retains the four original
inventory-dependent module exclusions documented in CONTRIBUTING.

The actual development package passed **19 checks in 1.34 seconds**: 18
case-specific compiled coordinator executions and a complete 36-row SQLite
round trip. The loader, read-only inventory store, matcher, A1 source/citation
validators and coordinator execute normally. A1 model and vector responses
are simulated from existing development fixtures; no live calls were made.

Every case receives only its original inventory pair through a temporary
case-scoped SQLite store. CaseRequest currently has no inventory-set field,
so supplying all 36 rows to a case would unnecessarily widen its search.
The tests verify unchanged database bytes, exact returned inventory fields,
canonical event/citation identity, literal lot support for exact findings,
JSON state round trips, and the A1 review gate before any inventory query.

| Observed coordinator route | Cases | A2 execution |
| --- | --- | --- |
| `a2_completed` with `matched` | 2 | Ran and returned one finding each |
| `a2_completed` with `no_match` | 6 | Ran and returned no findings |
| `human_review` | 10 | Stopped at A1 review gate; A2 did not run |

The matched cases were `H-0011-2027` and `F-1542-2023`. The six no-match
cases were Group B. The four other Group A cases and all six Group C cases
retained their review requirement. These are observed results under current
matching/review policies, not independently adjudicated outcomes or safety
clearance. Case-by-case observations are in the local JUnit properties.

## Remaining work

The 21 original tests in four modules remain unchanged and unrun here.
Several explicitly require all 48 sets/96 rows, including scenarios outside
this 18-case development selection. A 36-row subset cannot satisfy those
full-package assertions. Do not manufacture extra rows, weaken assertions,
or expose held-out scenarios to development to make them pass.

The A2 owner should review the observed matching results and the existing
product-equivalence and batch-to-lot policies. Independent reviewed outcomes
are still needed for accuracy evaluation. The ten human-review cases were
not approved or resumed by these checks. General expiry-date comparison and
durable human-review resumption remain outside the current implementation.

For application integration, the caller must select the approved catalog case
and scope its inventory before invoking the coordinator. Extending the shared
case contract with an inventory-set selector should be reviewed separately.
Publication of code does not publish this local inventory subset; any shared
dataset fixture or CI-secret addition needs its own agreed scope.
