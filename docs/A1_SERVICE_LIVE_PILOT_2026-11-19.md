# A1 combined service: first live pilot

## Scope

Member 1 authorized the next development step. One complete live request was
run through `a1_service.run_a1` for development recall `H-0011-2027`. No other
recall was run in this pilot. No Qdrant writes or inventory access occurred.

The existing model (`gpt-6-luna`), output cap (4,000 tokens), disabled SDK
retries, source schema, and existing $1 local accounting limit were retained.
Credentials were loaded privately and were not printed or copied into this
record. The read-only shell restriction required an escalated command for
network access and ledger/result writes.

## Actual measured results

| Measure | Result |
| --- | --- |
| Started UTC | 2026-11-19T15:06:02.296503+00:00 |
| Completed UTC | 2026-11-19T15:06:10.152397+00:00 |
| Recall / event | `H-0011-2027` / `99686` |
| Snapshot | `FDA-FOOD-2026-10-23-USER-SNAPSHOT` |
| Qdrant collection | `recallready_fda_food_a1_v1` |
| Embedding model | `sentence-transformers/all-minilm-l6-v2` |
| Retrieved and source-validated passages | 4/4 |
| Final contract | `0.1-proposed` |
| Final source/citation validation | Passed |
| End-to-end elapsed time | 7.8552 seconds |
| Retrieval elapsed time | 1.4817 seconds |
| OpenAI requests / structural repairs | 1 / 0 |
| Reported input / output tokens | 935 / 110 |
| Reported reasoning tokens | 0 |
| Persistent ledger call ID | 26 |
| Local estimated cost | $0.000149 |

The estimate uses the existing historical ledger rates, not a freshly verified
provider tariff or invoice. Elapsed times measure this single request; they
are not averages or performance guarantees. Retrieval uses Cloud Inference;
OpenAI token figures above cover interpretation, not Qdrant inference usage.

## Returned facts and evidence

- Lot: `26078`.
- Best-by date: `09/15/2026`.
- UPC: `850041392103`.
- Recall reason: `Undeclared Milk.`
- Classification: `Class I`.
- Model uncertainties: empty for this basic development case.

The exact source code field is `Lot # 26078 BEST BY: 09/15/2026`.
The UPC is supported by the product-description passage. The date retains
its best-by label and literal spelling.

All four expected passages were retrieved and cited: `PRODUCT_DESCRIPTION`,
`CODE_INFO`, `REASON_FOR_RECALL`, and `DISTRIBUTION_PATTERN`, with prefix
`EV-H-0011-2027-`. Exact text came from SQLite, not from Qdrant similarity.

## Artifact and independent verification

Private local result:
`runtime/a1_service_live_20261119T150610152460Z.json` (permissions `0600`).
This ignored runtime artifact contains the validated result, retrieval IDs
and scores, timing, and the new usage-ledger entry. Teammates need the
artifact supplied separately to inspect the original live trace.

After execution, a separate read-only check loaded the artifact and:

1. Ran `validate_result` against `Source()` reading the immutable starter ZIP
   directly, independently of the SQLite runtime source. Validation passed.
2. Compared retrieved and cited evidence to the exact four-passage set. Passed.
3. Compared saved usage and response ID to persistent ledger call 26. Passed.
4. Checked owner-only artifact permissions. Passed.

Source ZIP SHA-256:
`b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.

## Limitations and next gate

This verifies one live combined Group A request, including successful HTTPS
connectivity after the redirect fix. It does not establish combined live
coverage of all 18 records, independent retrieval relevance, extraction
accuracy, or Group C combined behavior. Historical separate live tests and
the 823-test offline suite remain separate evidence.

The next development gate is a controlled intermediate Group B pilot, followed
by a Group C relationship pilot. Coordinator/CaseState integration and wider
evaluation remain pending. No schema, prompt, or production source code was
changed during this pilot. No extra model attempts were made after success.
