# Controlled live A1–A4 pilot — 24 November 2026

## Scope and result

Member 1 authorized one live `H-0011-2027` / `CASE-001` execution through the
compiled A1/A2/A3/A4 coordinator. Code checkpoint:
`78600af` on local branch `feature/a4-review-local`. Credentials were loaded
privately. Only the two original inventory rows of `SIMSET-001` were loaded
into the temporary inventory database. The shared existing $1 local pilot
ledger was used; no new ledger was created to bypass prior usage.

The execution succeeded and ended at **human_review**:

```text
started → a1_validated → a2_matched → a3_planned
        → a4_human_review → human_review
```

| Stage | Observed result |
| --- | --- |
| A1 | Live Qdrant retrieval, 4/4 exact FDA passages verified, live OpenAI interpretation validated |
| A2 | One exact inventory finding: `INV-001-A`, lot `26078`, UPC `850041392103`, 12 simulated packages |
| A3 | Deterministic plan produced; human review retained |
| A4 | Deterministic checks and live OpenAI semantic critic executed; no findings; human review retained |
| Corrections | Zero structural repairs, zero A3 replays, SDK retries disabled |

No real stock action or human approval was executed. A clean critic result
does not establish safety, independent matching accuracy or A2 owner sign-off.

## Timing and usage

The run started at `2026-11-23T21:10:30.645659+00:00`, corresponding to
24 November 2026 in Asia/Kolkata. The first-to-last case event interval was
8.258619 seconds. This is one measured execution, not average latency.

| Model stage | Ledger call | Input tokens | Output tokens | Included reasoning tokens | Historical estimated USD |
| --- | --- | --- | --- | --- | --- |
| A1 | 32 | 935 | 140 | 0 | 0.000164 |
| A4 | 33 | 2,123 | 34 | 0 | 0.000230 |
| Total | Two requests | 3,058 | 174 | 0 | **0.000394** |

Both stages used the existing `gpt-6-luna` model configuration. A2 and A3 made
no API requests. A1 trace duration was 6.899352 seconds; A4 trace duration was
1.350620 seconds. The A1 output cap remained 4,000 tokens and A4's cap remained
1,500. The ledger rates are the existing historical pilot estimate, not a
provider invoice or a newly verified pricing statement. Reasoning tokens are
included in output totals and are not added again.

The shared ledger now has 33 calls and $0.008612 accounted, leaving
approximately $0.991388 under the local cap. This cap is local accounting,
not a provider-enforced spending cutoff.

## Private artifacts and verification

Run ID:
`live-a1-a4-H-0011-2027-0f43e57f-6fe3-44a5-9132-27ddbc869145`.

Local artifact directory:
`runtime/a1_a4_live_20261123T211030645659Z/`.

- `state.json`: complete typed coordinator state and both usage traces.
- `summary.json`: stage outcomes, events, usage estimate and state checksum.
- `run_metadata.json`: execution identity, code commit, selected case/inventory
  input, configuration flags and prepared-package hashes; no credentials.

The directory uses `0700`; the three files use `0600`. Artifacts and the usage
ledger are ignored by Git. They require an approved private transfer for
teammates who do not share this machine.

State SHA-256:
`33721523f2a5b0a8db8e65f68935bac95a834cc66d73fc374d4323f13f890bc7`.

A separate offline read-only verification:

1. Reloaded `state.json` as `CaseState` and verified its checksum/permissions.
2. Validated A1 directly against the immutable starter ZIP; checked all four
   retrieved/cited passage IDs and their point IDs plus archive hash.
3. Verified the selected inventory pair against the prepared package and
   metadata, compared returned inventory attributes/quantity exactly, and
   recomputed the pure exact-match comparison.
4. Revalidated A3 policy and evidence against the actual A2 envelope.
5. Checked A4's semantic-model invocation, empty findings, correct verified
   references, review requirement and zero revision count.
6. Matched both request traces to the run-linked ledger IDs, response IDs,
   input/output/reasoning counts and settled charges.

All passed. The live runner also confirmed the temporary inventory database
hash was unchanged across execution. No application code was modified or
regression tests rerun for this pilot; the preceding checkpoint had 1,092
passing permitted regression tests and 57 explicit development checks.

## Remaining work

This verifies one complete live matched-case execution. It does not provide
live coverage of all 18 cases, independent accuracy metrics, correction-path
live evidence or production readiness. Offline failure/revision tests remain
the evidence for those routes. A2 matching-policy sign-off, targeted A1/A2
correction and downstream reruns, durable human approval/resumption, and
UI/hosting remain pending. No code or private runtime data was pushed.
