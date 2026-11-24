# Agent 2 owner review packet — development evidence

## What to review

This packet asks the Agent 2 owner to review matching policy and observed
outputs. It does not record owner approval or an accuracy score. The source is
the selected 18 development recalls and their 36 original synthetic inventory
rows. Evaluation labels and held-out inventory were not used.

Read `inventory_store.py` (product equivalences and candidate selection),
`inventory_match.py` (attribute comparisons and exact/partial/no-match rules),
`a2_agent.py` (A1 scope, batch mapping and output envelope), and
`coordinator.py` (review gate and status routing). The actual test cases are in
`tests/a2_development_inventory_checks.py`; the saved per-case statuses are in
`runtime/a1_a2_final_local_checks.xml` when available locally.

## Observations to assess

| Development cases | Observed route | Interpretation limit |
| --- | --- | --- |
| `H-0011-2027`, `F-1542-2023` | A2 `matched`, one exact finding each | Matches are deterministic outputs, not adjudicated truth |
| All six Group B cases | A2 `no_match`, zero findings | No-match means no candidate met the current rules in the selected pair; it does not establish that stock is safe |
| Other four Group A cases; all six Group C cases | `human_review` before A2 | No A2 matching result exists for these ten cases |

One controlled live `H-0011-2027` run retrieved all four FDA passages, validated
A1, and returned an exact A2 match for `SIMSET-001` / `INV-001-A`, lot `26078`,
UPC `850041392103`, simulated quantity 12 packages. The complete private
artifact and source/ledger verification are documented in
`docs/A1_A2_OFFLINE_DEMO_2026-11-22.md`.

An independent read-only comparison of each selected A/B row against the
reviewed A1 fixtures produced the following attribute-level observations:

| Recall | A1 lot/batch identifier | Selected `-A` row | Selected `-B` row |
| --- | --- | --- | --- |
| `H-0011-2027` | `26078` | Exact lot, product, package and UPC | No lot; different product |
| `F-1542-2023` | `060723` | Exact lot, product, package and UPC | No lot; different product |
| `F-0818-2023` | `US3-12` | Product, package and UPC match; lot differs | No lot; different product |
| `F-0882-2023` | Batch `2-401` | Product and package match; code differs | No lot; different product |
| `F-1025-2023` | Batch `101097` | Product and brand match; code differs | No lot; different product |
| `F-0011-2024` | `23194` | Product, package and UPC match; lot differs | No lot; different product |
| `F-0332-2023` | `022422SRB` | Product, package and UPC match; lot differs | No lot; different product |
| `H-1273-2026` | `LB028ACP04` | Product, package, UPC and brand match; lot differs | No lot; different product |

The A1 identifiers above are literal strings, including the leading zero in
`060723` and `022422SRB`. Under the current strict lot rule, all six Group B
`-A` rows are `no_match` despite their other matching attributes. For the two
batch cases, A2 compares the batch value to the inventory `lot_code`. This is a
policy observation for review, not independent ground truth.

## Policy decisions requested from the owner

1. **Product names:** `APPROVED_PRODUCT_NAME_EQUIVALENCES` in
   `inventory_store.py` is a teammate-supplied fixed table. Please verify its
   entries against the FDA text and the selected inventory labels, particularly
   abbreviated or branded descriptions. The constant's name is not evidence
   of an independent owner sign-off.
2. **Batch versus lot:** `a2_agent.py` places A1 `batch` values into the lot
   comparison scope because inventory exposes only `lot_code`. Please confirm
   whether that mapping is acceptable and whether a batch-derived exact match
   should remain exact or require human review.
3. **No-match meaning:** `inventory_match.py` rejects candidates with a
   concrete product, lot, package, UPC or brand mismatch. `a2_agent.py` returns
   `no_match` with no findings when nothing qualifies. Please check the six
   Group B outcomes against the two original rows per selected set and confirm
   that downstream agents and demonstrations never interpret this as a stock
   safety determination.
4. **Review gate:** Confirm that four Group A cases with A1 uncertainty and all
   six Group C cases should remain stopped before A2 until a separately
   designed approval/resumption flow exists. Do not infer approval from prior
   human inspection of literal FDA values.

## How to record the review

For each decision above, record **approve / request change / unresolved** with
a short rationale and, for any change, the affected recall and inventory item.
Separately review both exact findings and all six no-match cases. Any policy
change should have focused tests and a fresh run of the 18 development checks.
Independent labeled evaluation is a later, separately scoped task.

The four older inventory-dependent test modules (21 tests) still require the
full 48-set package and were not run on this development subset. The new
private-data checks passed 21/21, and the permitted regression suite passed
990/990 before this packet was written. No new API call is needed for owner
review.
