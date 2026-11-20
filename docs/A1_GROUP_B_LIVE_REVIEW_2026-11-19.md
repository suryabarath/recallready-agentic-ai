# A1 Group B live review — 19 November 2026

## Run and source review

Six Group B development recalls were run through the real OpenAI Responses API
with `gpt-6-luna`, low reasoning, one call per recall, `store=False`, and the
existing project ledger. The caller selected the recall; A1 assembled metadata
and four passages from the starter ZIP and validated each final result. This is
an exploratory development review, not independent gold-label evaluation.

| Recall | Event | Live identifiers, exact source spelling | Review observation | Input/output tokens | Local estimated USD |
| --- | --- | --- | --- | ---: | ---: |
| `F-0818-2023` | `92067` | UPC `8904067712635`; lot `US3-12` | Both appear under distinct labels in `code_info`; accepted | 838/80 | 0.000124 |
| `F-0882-2023` | `92215` | Batch `2-401` | Exact batch label and value; accepted | 816/49 | 0.000107 |
| `F-1025-2023` | `92421` | Batch `101097` | Exact batch and source reason about pasteurization; accepted | 809/48 | 0.000105 |
| `F-0011-2024` | `93135` | Lot `23194`; expiry `13/JAN/2025`; UPC `858788004495` | All three distinct labels and literals preserved; accepted | 853/108 | 0.000140 |
| `F-0332-2023` | `91355` | UPC `855099007764`; lot `022422SRB`; expiry `2/24/2024` | UPC comes from product description; lot and expiry from code field; leading zero preserved; accepted | 846/111 | 0.000141 |
| `H-1273-2026` | `99538` | UPC `194346207961`; lot `LB028ACP04`; expiry `January 28, 2027` | Source label is literally `exp. date`; all three values preserved; accepted | 872/146 | 0.000161 |

All outputs carried the selected event and snapshot, the original source fields,
and the four source passage IDs. All had empty `uncertainties`; that is the
model's output, not a general assertion that every source relationship is
fully resolved. The source reason and classification fields were copied from
the original records. In `F-0332-2023`, the reason mentions both sandwiches and
burritos while this record's product description identifies a burrito; the
original broader wording was preserved without recasting it as a package claim.

## Member 1 human review

On 19 November 2026, Member 1 reviewed the five remaining Group B outputs
against their cited FDA source passages and approved them as good:

`F-0882-2023`, `F-1025-2023`, `F-0011-2024`, `F-0332-2023`, and `H-1273-2026`.

The approval confirms the displayed identifiers, source wording and citation
context for this development review. It does not convert these development
cases into independent gold labels or establish production safety decisions.

Total reported usage: **5,034 input tokens, 542 output tokens**, including any
reasoning tokens within output. Local estimated charge: **USD 0.000778** for
six calls. This is ledger accounting at the configured pilot rates, not a
verified invoice or credit deduction. Previous ledger charges remain separate.

## Verification and limitations

The first result was inspected directly during the live run. The other five
stdout results are retained under `runtime/group_b_live_2026_11_19/` (local,
ignored runtime files). The ledger contains calls 9–14 and the usage values
above. The first run's full output was not separately saved; its response ID
and usage remain in the ledger.

The pre-live offline suite had **580 passing tests**. Live results passed the
code's exact-source and citation validator. The review compared all reported
identifier literals and labels with the frozen FDA record text. It did not
prove extraction completeness for every possible package or date relation,
independent human gold-label accuracy, cross-record generalization, Qdrant
retrieval, or downstream inventory decisions. No held-out labels were read.
