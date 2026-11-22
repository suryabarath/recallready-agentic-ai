# A1-to-A2 offline demonstration

## Purpose

This demonstration makes the representative Agent 1 to Agent 2 data flow
inspectable without paid requests or cloud dependencies. It runs the real FDA
source and citation validation, coordinator, case-scoped SQLite inventory,
A2 matcher and final `CaseState` validation. Only Qdrant and OpenAI responses
are replayed from the existing reviewed development fixtures.

It is integration evidence, not an accuracy benchmark, live-service result or
replacement for independent outcome review.

## Run it

From the repository root, after preparing `runtime/a2_development_18_v1`:

```bash
.venv/bin/python -B tests/a2_development_demo.py \
  --output runtime/a1_a2_offline_demo_v1
```

The runner refuses to overwrite an existing output directory. Choose a new
output path for a later run. Generated files are private local runtime
artifacts, are ignored by Git and use mode `0600`.

## Representative cases

| Route | Recall | Expected policy observation |
| --- | --- | --- |
| Inventory match | `H-0011-2027` | A1 validates, A2 returns one finding, case completes A2 |
| No inventory match | `F-0818-2023` | A1 validates, A2 returns no findings, case completes A2 |
| Human review | `H-1388-2026` | A1 validates Group C relationships and stops before A2 |

Each case receives only the two inventory rows belonging to its cataloged
inventory set. This is necessary because the current `CaseRequest` has no
inventory-set selector.

## Inspect the output

`summary.json` provides a compact route table. Each route also has a complete
JSON `CaseState`, including the A1 result, evidence references, events and any
A2 findings. `manifest.json` records SHA-256 checksums for the summary and state
files.

Useful read-only commands are:

```bash
.venv/bin/python -m json.tool runtime/a1_a2_offline_demo_v1/summary.json
.venv/bin/python -m json.tool \
  runtime/a1_a2_offline_demo_v1/matched_H-0011-2027.json
```

The saved metadata states that the two external request types were simulated.
Do not describe these artifacts as live OpenAI or Qdrant results.

## Verification and limits

The focused test validates all three complete state files, route/status pairs,
case-scoped row counts, simulated request counts and manifest checksums. The
human-review case must contain no A2 result, proving that inventory matching
did not bypass the A1 review gate.

Run that private-data check explicitly:

```bash
.venv/bin/python -B -m pytest tests/a2_development_demo_checks.py \
  -q -p no:cacheprovider
```

Its filename is intentionally outside default pytest discovery. If the private
development package is missing or altered, the explicit command fails; it does
not skip the check.

## Controlled live follow-up (22 November 2026)

Member 1 authorized one live A1-to-A2 run for `H-0011-2027` using the same
case-scoped `SIMSET-001` inventory pair. The complete result is held locally in
`runtime/a1_a2_live_H-0011-2027_20261122T160822428518Z.json` (mode `0600`,
ignored by Git). Its SHA-256 is
`768a8892f4100d67076c483a10163a73361fb629f53387e9c0b588ff31f49927`.

The compiled coordinator retrieved and verified four FDA passages through
Qdrant Cloud, made one OpenAI model request with no structural repair, and
validated A1. A2 matched `INV-001-A`: lot `26078`, UPC `850041392103`,
simulated quantity 12 packages. Events were
`started → a1_validated → a2_matched → a2_completed`. The result had one exact
finding and final status `a2_completed`.

A separate read-only check parsed the saved `CaseState`, revalidated A1 against
the immutable FDA starter ZIP, checked all four cited/retrieved passage IDs,
compared the A2 finding with the original selected synthetic inventory row,
and matched the model trace to shared usage-ledger call 31. All passed.
The model reported 935 input and 110 output tokens, including zero reasoning
tokens. The ledger's historical pilot rates estimated **$0.000149**, which is
not a provider invoice. The source ZIP, inventory export, and application
code were not modified by the live call.

This records one live matched case. The offline no-match and human-review
demonstrations remain simulated at their external request boundaries.
Independent A2 owner review of matching policy and outcome evaluation remain
pending.
