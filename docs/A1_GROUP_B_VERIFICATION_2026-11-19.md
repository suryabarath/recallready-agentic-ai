# A1 Group B intermediate verification — 19 November 2026

## Scope and outcome

This increment expands the standalone A1 development scope from the six Group A
recalls to 12 Group A+B recalls. It reads the unchanged starter ZIP directly and
adds the six intermediate records listed by its selection file:

| Recall | Event | Covered interpretation |
| --- | --- | --- |
| `F-0818-2023` | `92067` | UPC `8904067712635`; lot `US3-12` |
| `F-0882-2023` | `92215` | Batch `2-401` |
| `F-1025-2023` | `92421` | Batch `101097`; exact recall reason |
| `F-0011-2024` | `93135` | Lot `23194`; expiration `13/JAN/2025`; UPC `858788004495` |
| `F-0332-2023` | `91355` | UPC `855099007764`; lot `022422SRB`; expiration `2/24/2024` |
| `H-1273-2026` | `99538` | UPC `194346207961`; lot `LB028ACP04`; expiration `January 28, 2027` |

The source text is preserved byte-for-text after UTF-8 decoding. In particular,
the leading zero in `022422SRB`, punctuation in `13/JAN/2025`, and literal label
`exp. date` are not normalized. Recognizing `exp. date` required a narrow label
pattern extension; it does not convert or infer a date value.

## Implementation changes

- `source.py` defines `GROUP_B` and `DEVELOPMENT_RECORDS`, verifies both approved
  selection groups, and restricts runtime access to their 12 records and 48 passages.
- `validation.py` accepts the explicit label form `exp. date` while retaining
  exact-value, exact-scope and citation validation.
- `interpreter.py` permits the 12 approved development recall numbers in the CLI.
- `tests/test_group_b.py` adds six exact lookups, all 24 Group B passage checks,
  explicit identifier/kind expectations, leading-zero and boundary rejection,
  altered/cross-context rejection, six contract examples and six SDK flows using
  an in-process fake HTTP transport.
- The existing Group A rejection test now uses a Group C record as the valid
  out-of-scope case because Group B is intentionally in scope.

The proposed output schema, model settings, budget controls and v4.2 architecture
were not changed. The starter ZIP was neither extracted nor edited. No inventory,
held-out labels, Qdrant collection, branch or commit was used.

## Commands and measured results

```text
.venv/bin/python -m pytest -q tests/test_group_b.py tests/test_task02a.py tests/test_task02b.py tests/test_interpreter.py
574 passed in 1.28s

.venv/bin/python -m pytest -q
574 passed in 1.10s

.venv/bin/python -m pip check
No broken requirements found.

shasum -a 256 ../project_reference/RecallReady_Agent1_FDA_18_Starter.zip
b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e
```

The first unprivileged full-suite attempt could not create a temporary file in
the managed read-only environment. It did not run tests. The approved escalated
rerun above completed the full suite. `git diff --check` also completed without
reporting whitespace errors.

## Pre-live review follow-up

The subsequent code review found that a response could cite the UPC for
`F-0818-2023` while silently omitting its explicitly labeled lot. The A1
validator now requires every explicitly labeled lot and batch in `code_info`
to appear with its exact value and kind. Ambiguous combined lot phrases retain
the existing full-phrase or human-review rule. A prior synthetic boundary test
that contained two explicit lots now supplies both, preserving its original
boundary assertion. The full offline suite passed with **580 tests**; a direct
reproduction of the former missing-lot case now raises `ContractError`.

This check covers explicit lot and batch labels. It does not establish general
completeness for every UPC, date, package description, or semantic association.
Those remain live-run and human-review concerns.

## Limitations

- The six SDK flows use the real installed SDK with a fake local HTTP transport.
  They verify request assembly and deterministic validation, not model accuracy.
- No paid OpenAI call was made for Group B, so token cost, latency, extraction
  quality, refusal behavior and semantic uncertainty have not been measured.
- These are development records and reviewed expectations, not independent gold
  labels or held-out evaluation results.
- Exact literal and explicit-label validation cannot prove that every semantic
  association or uncertainty statement is complete. Human review remains required.
- Qdrant, embeddings, authoritative-source SQLite migration, A2–A4, LangGraph,
  Streamlit and deployment remain outside this increment.
