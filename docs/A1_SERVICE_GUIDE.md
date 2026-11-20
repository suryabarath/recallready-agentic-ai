# Standalone Agent 1 request flow

## Scope and status

`a1_service.run_a1` connects exact SQLite lookup, filtered Qdrant retrieval,
the existing bounded interpreter, and final citation/source validation.
It supports the 18 development recalls. The complete flow is verified offline
using simulated network responses. A subsequent first live combined pilot
passed for `H-0011-2027`; see `A1_SERVICE_LIVE_PILOT_2026-11-19.md` for actual
timing, token usage and validation results. The subsequent Group B pilot passed for
`F-0332-2023`; see `A1_SERVICE_GROUP_B_LIVE_2026-11-19.md`.
The Group C pilot passed for `H-1388-2026`, preserving both lot/expiry pairs;
see `A1_SERVICE_GROUP_C_LIVE_2026-11-19.md`. These three pilots do not establish
independent accuracy or combined live coverage for all 18 records.

Groups A/B return the existing `A1Result` (`0.1-proposed`). Group C returns the
approved separate `GroupCResult` envelope (`0.2-group-c-provisional`) with
mandatory review uncertainty. Neither schema was changed. The coordinator's
CaseState/error format and external natural-language query input remain open.

## Request flow

1. Validate recall selection, optional event, snapshot, disabled SDK retries,
   output cap, shared SQLite store, and any explicitly supplied lot review.
2. Query `recallready_fda_food_a1_v1` with exact recall/snapshot filters and a
   fixed internal query for product, code/date, reason, and distribution evidence.
3. Require all four distinct passage IDs. Recheck every passage identity and
   original text against SQLite. Empty, partial, duplicate, unknown, or
   cross-context retrieval stops the run before any model call or reservation.
4. Route Groups A/B to `interpret` and Group C to `interpret_group_c`. Both
   re-read the same four canonical passages from SQLite and send only those
   passages to the model. Canonical firm/classification metadata stays local.
5. Return the existing typed result only after its source and citation checks
   pass. Errors raise `A1RunError` identifying preflight, retrieval, or
   interpretation; there is no fallback success. The caller handles escalation.

The four-passage requirement follows the current complete output contract.
Similarity ranks evidence inside a selected recall; it never establishes lot
equality or chooses the recall. This flow is not an open-ended search engine.

## Use from application code

Prerequisites: install `requirements.txt`; build the FDA SQLite store as
described in the README; privately configure `QDRANT_URL`, `QDRANT_API_KEY`,
and `OPENAI_API_KEY` in the process environment. `.env` is not automatically
loaded by the service. The caller creates and closes resource objects.

The example below makes live Qdrant and paid OpenAI requests if executed. It
was not executed as a live test during service implementation.

```python
import os
from pathlib import Path
from openai import OpenAI

from a1_service import run_a1
from fda_store import FDAStore
from interpreter import Budget
from qdrant_a1 import QdrantA1

with FDAStore(Path("runtime/fda_a1.sqlite")) as store:
    retriever = QdrantA1(os.environ["QDRANT_URL"],
                         os.environ["QDRANT_API_KEY"], store)
    budget = Budget(Path("runtime/a1_usage.sqlite"))
    with OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1",
                max_retries=0, timeout=60) as client:
        result = run_a1(store, retriever, client, budget,
                        recall_number="H-0011-2027",
                        snapshot_id=store.snapshot_id)
        print(result.model_dump_json(indent=2))
```

The model remains the existing reviewed pilot configuration; this stage does
not change model selection or its historical price assumptions. The usage
ledger is a local estimate, not an enforceable provider billing cutoff. A
structural repair may make one additional accounted model call; semantic
validation failures stop. Failed requests may retain their reservations.

For an approved ambiguous Group A/B lot, load only that case's review using
`reviews.load_reviews` and explicitly pass `approved_lots`. Reviews never
enter the model prompt. They are not auto-loaded, and Group C rejects this
Group A/B lot-approval argument rather than silently ignoring it.

## Verification and remaining work

```bash
.venv/bin/python -m pytest tests/test_a1_service.py -q
.venv/bin/python -m pytest -q
```

Implementation verification: 45 service tests passed; 880 full-suite tests
passed. These use the real SQLite/source resolvers, Qdrant validation code,
OpenAI SDK request construction, interpreters, and final validators. Only
network responses are simulated. Fixtures are development examples, not
independent model accuracy measurements. Tests cover all 18 recalls, original
literal preservation, retrieval failures, invalid context/reviews, unsupported
model values/citations, transport failure accounting, and bounded repair.
The suite also includes 16 storage/resource regression tests for explicit
database failures, transaction rollback, reservation retention and cleanup.
The coordinator wrapper adds 41 tests; a subsequent controlled Group C live
regression verified the reliability and envelope changes. See
`A1_RUN_ENVELOPE_GUIDE.md` for exact results and limits.

Next: map the implemented `run_a1_with_trace` envelope into the actual
coordinator. See `A1_RUN_ENVELOPE_GUIDE.md`. The first live pilot verified
connectivity after the redirect fix. Independent relevance/accuracy evaluation,
LangGraph/CaseState integration, A2 inventory work, and deployment remain outside
this completed offline integration stage.
