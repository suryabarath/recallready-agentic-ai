# Task 02B — M1-approved A1 contract and offline validation

Status: APPROVED by Member 1 in this conversation on 17 November 2026 for
the output structure and offline validation. An interpreter was implemented in
a later increment; shared-app integration remains pending. The starter ZIP and its proposed JSON Schema remain
unchanged. Scope remains the six Group A development recalls. Example semantic
interpretations remain review candidates, not approved gold labels.

## Approved decisions

Member 1 approved the following contract choices:

1. Keep the starter's eight-field facts object and identifier-kind enum unchanged.
   Place it inside the approved provenance envelope below. Consumers explicitly
   read `result.facts`; shared-app integration remains a separate task.
2. Require exact snapshot/event context and canonical source-field provenance,
   including metadata with no packaged evidence passage. Never invent evidence
   IDs for recalling firm or classification.
3. Keep source strings literal for this first gate. Preserve code context in
   `scope_note`; represent an unresolved identifier kind as `other` and explain
   it in `uncertainties`. Do not silently normalize dates or codes.
4. Defer structured association fields until a separate review before Group C
   or A2 integration. A2 must not derive joins from independent identifier lists.
   If structured associations are required now, revise this proposal first.

## Approved local shape

All objects forbid extra fields. All listed fields are required. The shape is
implemented in `models.py`. The generated structural schema is
`docs/task02b_contract.schema.json`. Source validation is in `validation.py`.
The approved version literal stays `0.1-proposed` for compatibility with the
reviewed examples; it is a version identifier, not the current approval status.

```text
A1Result
  contract_version: literal "0.1-proposed"
  snapshot_id: nonblank string
  event_id: nonblank string
  facts: the existing eight-field starter shape
  source_fields: mapping of the six canonical field names below to SourceField

SourceField
  original_text: string | null
  evidence_id: nonblank string | null
  point_id: UUID string | null
```

The six `source_fields` keys are `product_description`, `code_info`,
`reason_for_recall`, `distribution_pattern`, `recalling_firm`, and `classification`.
The selected recall is `facts.recall_number`. Together with envelope event and
snapshot it identifies every source field. Evidence and point IDs must both be
null or both resolve to the same packaged passage.

The unchanged `facts` fields are:

| Field | Type and approved rule |
| --- | --- |
| `recall_number` | Exact selected string; no trimming or zero removal |
| `product_name` | String or null; for this gate use the entire exact `product_description` |
| `recalling_firm` | String or null; exact canonical `recalling_firm` |
| `recall_reason` | String or null; exact `reason_for_recall`, preserving qualifications |
| `classification` | String or null; exact canonical `classification` |
| `identifiers` | List of the existing `{kind, value, scope_note, evidence_ids}` objects |
| `uncertainties` | List of nonblank explanations; mandatory for unresolved meaning or missing requested facts |
| `evidence_ids` | Unique list of all non-null source-field evidence IDs, including identifier support |

Identifier kinds stay `lot`, `batch`, `upc`, `sku`, `expiry_date`, `use_by_date`,
`best_by_date`, `date_range`, and `other`. Values are nonblank strings. Every
identifier needs at least one resolving evidence ID and exact literal support
in every cited passage, as required by Task 02A. Kind and scope need separate
source/human review: literal membership alone does not establish them.

Use the exact source field containing the identifier as its `scope_note` in
these initial examples. This preserves punctuation, neighboring codes, package
descriptions, and ambiguous wording. It does not convert adjacency into a proven
lot/date association. A2 must treat `other` and unresolved relationships as
requiring review.

The initial `product_name` rule deliberately avoids deriving a shortened name.
A later approved normalization can retain both original and interpreted text;
it must not silently replace source evidence.

## Source and unknown rules

- Source metadata comes from exact local `Source.lookup`; FDA passage facts
  resolve through `Source.resolve`. No model-generated provenance is trusted.
- For the four packaged passage fields, source-field text, evidence ID and point
  ID must match the canonical passage. For `recalling_firm` and `classification`,
  both IDs are null and text must match the original JSON field. Null IDs here
  mean canonical source provenance, not absent evidence or an invented passage.
- Missing fields retain `original_text: null`, null IDs, a null fact where
  applicable, and an explicit uncertainty. An existing passage with altered or
  missing source text is an integrity error, not an acceptable missing fact.
- Preserve existing empty strings and literal `Unknown` in source provenance;
  do not turn them into identifiers. A fact unavailable from that text is null,
  with an uncertainty explaining why. Absence of a supported identifier means
  an empty identifier list, never a guessed code or a claim of no affected lots.
- Full source text remains visible even if a conservative interpretation leaves
  an identifier unresolved. Missing provenance must fail validation.
- JSON/types must validate strictly: no numeric identifier coercion, extra
  fields, silent defaulting, or date normalization. All identifier references
  must also appear in the top-level facts evidence list.
- Schema validation, exact citation validation, and semantic review are separate
  checks. Do not report a schema/citation pass as interpretation accuracy.

## Group A acceptance cases

See `task02b_group_a_review_examples.json` for six source-backed candidate
outputs. These are development review examples, not human-approved gold labels,
model outputs, or new runtime fixtures. Interpretations below require M1 review.

| Recall | Proposed acceptance behavior |
| --- | --- |
| `H-0011-2027` | Preserve lot `26078`, best-by `09/15/2026`, UPC `850041392103`; retain full package context and exact reason |
| `F-1542-2023` | Preserve lot `060723` with its leading zero; retain literal UPC `5803100115` without padding or format correction |
| `F-1472-2024` | Preserve the entire code phrase `06-04-24 08/04/2024` as `other`; flag that the boundary/meaning of the two date-like segments needs review; do not assert an expiry date |
| `H-0579-2025` | Distinguish lot `25223M`, SKU `24682-05020`, and consecutive count `499-6100` (`other`); retain the full source context |
| `F-0705-2025` | Following the 19 November Option A amendment, preserve the entire `04162026 BC 6937218914734` phrase as `other` with uncertainty; do not assert a confirmed lot or UPC |
| `F-0324-2023` | Preserve lot `336`, spaced UPC `17442 30012`, and `Jan 06 2023` as `other` with the exact sell-by label; do not relabel sell-by as use-by or expiry |

The conservative handling of `F-1472-2024` may omit a separately typed lot.
M1 may approve a different interpretation after reviewing the exact source;
do not silently convert this candidate example into extraction ground truth.
The later Option A policy also revises the F-0705-2025 development candidate;
see `A1_OPTION_A_POLICY_2026-11-19.md` for the amendment and test evidence.

## Validation acceptance matrix

| Input or alteration | Required outcome |
| --- | --- |
| Six candidate outputs with exact canonical provenance | Structural and citation pass; semantic interpretations reviewed separately |
| Metadata value changed, or metadata cited through a made-up evidence ID | Reject |
| Wrong recall, event, snapshot, evidence ID, point ID, field name, or source text | Reject |
| `060723` changed to `60723`, or `04162026` changed to a number | Reject |
| Spaced UPC rewritten without spaces, date reformatted, or code suffix invented | Reject |
| Identifier cited only by reason/distribution, or by an extra unrelated passage | Reject |
| Identifier's evidence ID omitted from `facts.evidence_ids` | Reject |
| Literal appears but asserted kind/scope is unsupported | Semantic rejection or unresolved review; literal check alone is insufficient |
| `08/04/2024` asserted to be an expiry, `BC` asserted to mean UPC, or sell-by asserted as use-by | Unresolved/revise; do not silently accept as a supported semantic claim |
| Unknown/missing code | Preserve original text, no fabricated identifier, explicit uncertainty |
| Lot/date/package relationships ambiguous | Preserve context and flag uncertainty; no independent cross-product of values |
| Missing required key, extra inventory/action field, numeric value coercion | Reject |

Unknown/empty codes and missing metadata are tested with synthetic fixtures.
Missing source for an existing passage is tested as an integrity failure.
Multi-association semantics remain deferred; retaining raw context does not
validate those associations. No Group B/C or held-out behavior is claimed.

## Offline implementation and usage

Strict Pydantic models and source validation now use the existing Task 02A
source/citation functions. `tests/test_task02b.py` adds positive and negative
checks without replacing or weakening Task 02A tests. Unknown/empty-code and
missing-metadata tests use explicitly synthetic snapshots built as new test
ZIPs. No original archive is extracted or modified, and no mock replaces the
source/citation checks.

`requirements.txt` pins the directly used packages: Pydantic 2.14.3 and pytest
9.2.0. They are installed in the project-local `.venv`; no dependency upgrade
was performed. From `code_workspace`, run:

```bash
.venv/bin/python -m pytest -q
```

For a decoded JSON candidate, call the complete validator with a trusted
selection supplied separately from the candidate:

```python
from source import Source
from validation import validate_result

source = Source()
selected_recall = "H-0011-2027"
selected_snapshot = source.snapshot_id
selected = source.lookup(selected_recall, snapshot_id=selected_snapshot)
result = validate_result(
    candidate, source,
    recall_number=selected_recall,
    snapshot_id=selected_snapshot,
    event_id=selected["event_id"],
)
```

Catch Pydantic `ValidationError` for structural/type failures and
`validation.ContractError` for source/review-policy failures. `A1Result` model
construction alone and the exported JSON Schema do not perform canonical-source
validation. Validate the final payload before handing it to another component.

Identifier kind checking conservatively requires an explicit adjacent source
label (`Lot`, `Lot Number`, `Batch`, `UPC`, `UPC Code`, `SKU`, expiry/use-by/best-by,
or `Date Range`). A label wording it cannot establish must use `other` and an
uncertainty or fail validation. Scope notes must retain an entire cited field.
This gate rejects the specified sell-by/expiry and BC/UPC relabelings. It does
not prove all meanings, identifier completeness, or lot/date/package relations;
an uncertainty must still be inspected by a human. Generic uncertainty text is
not semantically graded by this offline validator. Structured associations and
broader wording support remain deferred.

Return validation failures explicitly to the caller; do not emit success-shaped
facts with invented defaults. A future interpreter may attempt at most one
schema repair, then return an unresolved error. No repair loop is implemented
or authorized by this document, and the coordinator's bounded Critic cycle is
unchanged.

No OpenAI model, budget, inference route, Qdrant collection, SQLite migration,
CaseState modification, deployment, inventory access, or A2 integration is
selected or performed here. Those remain separate approvals and tasks.
