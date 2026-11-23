# Agent 3 review and coordinator integration

## Scope and provenance

Reviewed `origin/feature/agent3` at
`a3aabf3ab998f0290bb62adad0378a2dae712742` against the current A1/A2
contracts and v4.2 handoff. The standalone implementation and tests were
imported from that commit using file-scoped patches. Other branch changes
were not merged. Work is on local branch `feature/a3-coordinator-local`, based
on the existing A1/A2 development checkpoint. The implementation is a
deterministic, offline response planner. An LLM planner, A4, durable human
approval/resumption and stock actions remain pending.

## Review findings and fixes

| Finding | Impact | Resolution |
| --- | --- | --- |
| A3 input projection discarded brand/package/UPC comparison statuses | An externally supplied exact finding with a concrete secondary mismatch could reach planning | Consume these statuses and reject an exact finding containing a mismatch |
| Envelope review flag was not checked against all findings | Mixed exact/partial input could drop the required aggregate review flag | Require consistency with finding flags; updated the inconsistent mixed-input fixture and added a rejection test |
| A3 rejected findings across multiple inventory sets | Valid shared A2 envelopes could fail A3 despite unique item IDs and matching case context | Preserve all item actions; remove this extra restriction and test multi-set compatibility |
| A3 was disconnected from the coordinator | No complete A1/A2/A3 path existed | Add optional A3 planning and state validation bound to the actual A2 result |
| Shared state had no A3 failure path | A planner failure after resolved A2 needed a typed terminal route | Add A3-specific error and events; preserve upstream outcomes and stop unresolved |

The real-A2 compatibility test now imports A2 directly. Missing A2 is a failure
in this integration checkout, rather than a skipped compatibility check.
Original assertions remain except those adjusted to correct the demonstrated
contract disagreement (mixed review flags and multi-set acceptance).

## Design and execution

Existing construction defaults to the original A1/A2 behavior. To include A3:

```python
coordinator = A1Coordinator(
    store, retriever, client, budget,
    inventory_store=inventory, enable_a3=True,
)
state = coordinator.run(request)
```

A3 requires an inventory store. A1 errors stop unresolved; A1 uncertainty and
Group C stop before A2. A2 errors stop unresolved; partial/review findings
stop before A3. A2 resolved matched/no-match results without review enter A3.
The resulting plan always stops at `human_review`. A3 failure or altered
context, item, action, rationale or citation stops unresolved with
`response_plan_failed`; no upstream model retry occurs.

`CaseState.a3` is optional and preserves the complete typed envelope. Its
validator checks the plan against A2 again, including during JSON reload.
A3 cannot authorize release, disposal or any other inventory mutation.
No-match plans retain the fixed non-clearance rationale. Planner functions
remain independent of databases and graph orchestration; the coordinator owns
routing, while the A3 module owns plan policy and validation. No new package
dependency, generic agent framework or inheritance hierarchy was added.

Validation follows the official [Pydantic model guidance](https://docs.pydantic.dev/latest/concepts/models/)
and [implementation of model_copy](https://github.com/pydantic/pydantic/blob/main/pydantic/main.py):
copied updates are not validated automatically. Fresh serialized snapshots
are revalidated at the planner and shared-state boundary. Graph routing uses
explicit maps per the [LangGraph conditional-edge API](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges).

## Actual verification

- Focused A3, A2 and coordinator tests: **126 passed in 3.41 seconds**.
- Permitted regression selection: **1,034 passed in 7.27 seconds**.
- Explicit development-data and demo checks: **39 passed in 2.25 seconds**
  (18 cases with A3 disabled, 18 enabled, one 36-row round trip, two demo checks).
- No new OpenAI or Qdrant calls; external A1 responses were fixtures.

Commands from the repository root:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py --ignore=tests/test_a2_review_fixes.py
.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider \
  -o junit_family=xunit1 --junitxml=runtime/a1_a2_a3_development_checks.xml
.venv/bin/python -B tests/a2_development_demo.py --enable-a3 \
  --output runtime/a1_a2_a3_offline_demo_v1
```

The three-route demo is in `runtime/a1_a2_a3_offline_demo_v1/`: `summary.json`,
three complete state JSON files, and a checksum manifest. Existing output
directories are refused; use a fresh name for a rerun. Files remain private
and Git-ignored.

With A3 enabled, the two matched and six no-match development cases produced
review-required plans. The other ten cases stopped before A2/A3. This is
observed policy behavior, not an accuracy result. The four historical
full-package modules (21 tests) remain unrun and unchanged. No evaluation
labels or held-out inventory were used.

## Remaining gates

A2 owner's product-name, batch/lot and no-match policy review is deferred;
this integration does not approve those policies. A3 never removes that
dependency. A fresh fetch revealed a separately named `origin/Agent4` branch;
it has not been technically reviewed or integrated here. A4 critic/correction
and final human decisions still need separate development. Production hosting,
durable execution, real-world safety validation and the optional LLM planner
are not established by these passing prototype tests. No publication was made.
