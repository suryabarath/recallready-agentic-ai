# A1 verification record — 18 November 2026

Scope: Group A source/citation/contract checks and the bounded OpenAI adapter.
Workspace: `recallready/code_workspace`. Interpreter: Python 3.13.6 on macOS.
Dependencies: Pydantic 2.14.3, pytest 9.2.0, OpenAI SDK 2.54.0.

## Executed checks

| Command | Measured result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 475 passed in 0.92 seconds |
| `.venv/bin/python -m pip check` | No broken requirements |
| `.venv/bin/python interpreter.py --help` | Exit 0; single-recall CLI and paid-call flag documented |
| `shasum -a 256 ../project_reference/RecallReady_Agent1_FDA_18_Starter.zip` | Unchanged SHA below |

ZIP SHA-256:
`b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e`.

The original 455 tests remain in place. Twenty adapter tests use the installed
OpenAI SDK and `httpx.MockTransport` to return explicit synthetic HTTP responses.
No real model endpoint is called. Six tests assemble and validate the six
development examples through the complete adapter; they are not six real model
interpretations. No model accuracy percentage is measured.

The adapter tests additionally cover one structural repair, the two-attempt
ceiling, invented citations, lost leading zeros, unsupported kinds, incomplete
responses, timeout reservation retention, persistent budget exhaustion, invalid
budget amounts, and missing paid-call/key preconditions.

For a simulated response with 4,000 input and 2,000 output tokens, the ledger
accounts USD 0.0014 at the configured Luna rates. Reasoning tokens are recorded
as a component of output and not charged twice. This is an accounting test,
not an observed live charge. Unknown-charge failures retain their reservations.

## Limitations and audit notes

- The offline checks above preceded credential setup. The first live pilot is
  recorded below; the subsequent five-run expansion and semantic limitations
  are recorded in `A1_GROUP_A_LIVE_REVIEW.md`.
- Account credits were reported purchased by the user, not inspected or verified.
- No current bill, credit eligibility, measured request latency, refusal rate,
  extraction accuracy or cross-provider comparison was measured. Real token usage
  for the single pilot is recorded below.
- No Qdrant integration, embeddings, SQLite evidence-store
  migration, multi-agent routing, deployed UI, or A2–A4 implementation is claimed.
- No inventory, held-out labels or excluded collection was accessed.
- Python 3.11 was not executed; tests ran on 3.13.6.
- Source checksum checks detect corruption, not malicious replacement of the
  entire archive and its checksums. A trusted snapshot manifest remains required.
- Label checking and literal membership cannot establish all semantic meanings,
  association fidelity, completeness, or whether uncertainty text is adequate.
- Local cost accounting estimates are not an instantaneous provider billing cap.
- SDK credentials are environment-only; no `.env` auto-loading is implemented.
- The managed session is read-only. File edits and test temporary files required
  managed approval. An initial unapproved pytest invocation failed before running
  tests because temporary directories were not writable; the approved run above
  executed the complete suite. No tests were removed, weakened or skipped.
- SDK installation completed in the project-local `.venv`. No branch, commit,
  deployment, inventory operation, extra agent, or presentation deck was created.

## Subsequent live pilot — H-0011-2027

After private credential setup, `.env` permissions were checked as `600` and
only the boolean presence of `OPENAI_API_KEY` was printed. The interrupted
approval attempt had left no ledger; the subsequent authorized run completed:

```bash
.venv/bin/python interpreter.py --recall H-0011-2027 --allow-paid-call --budget-usd 1.00 --ledger runtime/a1_usage.sqlite
```

- Exit status: 0. One real response, no structural repair or automatic retry.
- Model configuration: `gpt-6-luna`, low reasoning, default service tier,
  `store=False`, 4,000 maximum output tokens.
- Returned identifiers: UPC `850041392103`, lot `26078`, best-by `09/15/2026`.
- Local contract, literal, citation and source validation passed. Event `99686`
  and snapshot `FDA-FOOD-2026-10-23-USER-SNAPSHOT` were preserved.
- Actual API-reported usage: 855 input tokens, 110 output tokens, 0 reasoning
  tokens. Ledger call 1 estimated USD 0.000141 after rounding up to microdollars;
  this is local accounting, not a verified invoice charge.
- Response ID: `resp_098f7c6aee12808c016afdc78ff10887d09451233de257a451`.
- The full validated result was printed to the execution transcript. The SQLite
  ledger stores usage metadata, not the full result; no separate output JSON
  artifact was saved during this run.

Manual source comparison confirms that these three identifier values and labels
appear in the cited passages. The model returned an empty uncertainty list.
The product passage includes mixed package-count wording (`10ct`, `5 count
carton`, and `5 individually wrapped packages of two donuts each`). Whether this
needs an explicit uncertainty remains a human review question; passing the local
validator does not establish semantic completeness or adequate uncertainty.
This single development recall establishes connectivity and one validated result,
not six-recall accuracy or held-out performance.

Subsequent authorized expansion completed the remaining five Group A recalls
using the same ledger. See `A1_GROUP_A_LIVE_REVIEW.md` for all six measured
outcomes and the unresolved semantic issues. The offline suite was rerun after
the expansion: **475 passed in 0.94 seconds**. No source code was changed.
