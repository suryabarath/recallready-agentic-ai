# Dataset access and placement

This directory documents inputs; application code still reads the FDA ZIP from
`../project_reference/` and the selected inventory from
`runtime/a2_development_18_v1/`. Moving inputs into `data/` will not configure
the current application.

## Access status

The approved files are available to Member 1 locally. **A working evaluator
download link has not yet been provided.** Obtain the package from Member 1.
Before submission, the team must supply a read-only link through its approved
sharing service and verify access from an evaluator/teammate account.

No dataset upload, permission change or public dataset publication has been
performed by preparing this guide. A public code clone alone is insufficient
to reproduce source-backed tests.

## Minimum offline input package

| Input | Destination relative to repository root | Purpose |
|---|---|---|
| `RecallReady_Agent1_FDA_18_Starter.zip` | `../project_reference/RecallReady_Agent1_FDA_18_Starter.zip` | Exact 18 FDA records, 72 passages, source manifest/checksums |
| `inventory_development.json` | `runtime/a2_development_18_v1/inventory_development.json` | Original selected 36 synthetic inventory rows |
| `cases_development.json` | `runtime/a2_development_18_v1/cases_development.json` | 18 recall/case/inventory-set mappings |
| `manifest.json` | `runtime/a2_development_18_v1/manifest.json` | Selected package identity, counts and hashes |

The FDA ZIP is read directly. Its relevant internal files include
`01_FDA_Original_Source_18.json`, `03_Agent1_Evidence_Passages_72.jsonl`,
`05_Agent1_Record_Selection.csv`, `08_Agent1_Manifest.json` and
`SHA256SUMS.txt`. Do not extract, edit or normalize the ZIP for the program.

Snapshot: `FDA-FOOD-2026-10-23-USER-SNAPSHOT`.

Approved SHA-256 identities:

```text
RecallReady_Agent1_FDA_18_Starter.zip
b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e

inventory_development.json
599128ded679406e3ada28800f013c10b580b01ece19113167aa9c1465770e74

cases_development.json
349fbb678cdd9e9004a838bf1eba5fbf586e5635bb983979746c3df25a0e70b7

manifest.json
2b87b12538c77d6cd81425209db5f516a2ce74050c8026596e068e103cb9aae3
```

Source loading and `load_development_package` validate source associations,
manifest identity and checksums. The selected package contains 18 development
sets, two original rows per set. It contains no evaluation labels.

## Optional: reproduce the selection from the original synthetic package

This route is only needed when the selected package has not been supplied.
The original package directory must contain:

- `02_retailer_inventory_SYNTHETIC.json`
- `03_case_catalog.csv`
- `SHA256SUMS.txt`

With the FDA ZIP already placed, run from the repository root:

```bash
.venv/bin/python -B development_inventory.py \
  "/path/to/RecallReady_FDA_Retail_Datasets_v1" \
  runtime/a2_development_18_v1
```

Use only an approved original package. The selector checks its hashes, joins
the 18 development recalls to catalog entries, decodes only their selected
inventory bodies and preserves literal row values. Existing output directories
are refused. Do not change counts or tests to accommodate another package.

## Generated stores and live services

The offline demo builds temporary FDA/inventory SQLite stores and temporary
simulated-call ledgers itself; do not distribute an old ledger or database as
a required offline input.

Live execution additionally uses an FDA SQLite store built from the ZIP,
a persistent local usage ledger, private OpenAI/Qdrant credentials and the
existing `recallready_fda_food_a1_v1` collection. These are not supplied by a
public Git clone. The collection contains FDA-only evidence, not inventory.

The full `FoodRecall_Evidence_v1.json` (approximately 40 MB), evaluation labels,
unselected inventory, historical live-result files and the four full-package
test fixtures are not required for the approved offline 18-record workflow.

## Dataset handoff checklist

Member 1 should share the four minimum input files, this guide and their
checksums. Keep credentials, raw diagnostic proposals, private ledgers and
unrelated datasets outside the evaluator input package.

A receiving teammate should download the approved files, place them as above,
validate them with the README command, run the two test selections, and
inspect the three-route demo. Record the code revision, OS/Python version
and results. Successful local provisioning does not establish that a shared
download link has working permissions.
