# Agent 4 review, fixes and coordinator integration

The subsequent [final review and team handoff](A1_A4_INTEGRATION_HANDOFF_2026-11-24.md)
records two additional reproduced boundary/failure fixes and the latest
1,092-test regression result. The measurements below describe the initial
A4 checkpoint.

## Source and scope

Reviewed the uploaded A4 at `origin/Agent4`, commit
`60f220b2962a96d269bf0c5c1bea207f29c72dd4` (Git author
`khanujagaganjot-77`). That snapshot supplied `a4_agent.py`, `a4_checks.py`
and a proposed coordinator patch guide, but no test modules. This local branch
starts at tested A3 checkpoint `ce65b48`. No remote branch was merged or changed.

The bounded OpenAI critic and its accounting were retained and corrected.
The provisional deterministic checks were replaced with a smaller audit of
the actual A1/A2/A3 contracts, reusing established exact validation and matching
tools. Its test results establish consistency, not independent matching
accuracy or approval of the pending A2 policies.

## Review findings and fixes

| Finding | Correction |
| --- | --- |
| A4 defined a different A3 envelope and action vocabulary | Import and revalidate the real `a3_agent.A3RunEnvelope`; do not synthesize quarantine, urgency or disclaimer fields |
| Unknown model evidence/item IDs were silently removed | Reject the critic response; retain accounting; do not retry semantic failures |
| Semantic inconsistency shared the structural repair loop | Only schema/JSON failures permit one repair; contradictions, duplicate/unknown references and unsupported revision targets stop immediately |
| Model review was enabled by default | Require explicit `enable_llm_critic=True`; coordinator has a separate `enable_a4_llm` flag |
| A2 audit could miss omitted findings/false no-match | Replay matching against the same case-scoped SQLite store and compare the complete A2 result |
| Critic could request a revision while non-fixable blockers remained | Request revision only when all blockers are marked fixable; otherwise escalate |
| No tests accompanied the upload | Add deterministic, SDK/accounting and compiled-coordinator test modules |
| Coordinator had no A4 outcome or revision history | Add typed A4 state, errors, events, original A3/A4 artifacts and a counter capped at one |

The provisional `prototype_disclaimer_verified` field is replaced locally by
`review_boundary_verified`. Current A3 has no disclaimer field, so claiming
that such a field had been verified would be misleading. This is an explicit
alignment of the uploaded provisional A4 contract, documented for its owner.

## Files and responsibilities

- `a4_checks.py`: exact FDA validation, A2 inventory replay, A3 policy/provenance
  audit, finding and error types; no network or inventory writes.
- `a4_agent.py`: typed verdict/trace, deterministic gate, explicitly enabled
  semantic critic, shared budget reservations and one structural repair.
- `case_state.py`: checks A4 identity and preserves review, errors and revision
  history when loading final JSON.
- `coordinator.py`: optional audit stage, one A3 replay, escalation and safe
  failure routing.
- `tests/test_a4_checks.py`, `tests/test_a4_agent.py`,
  `tests/test_a4_coordinator.py`: actual store/tool/graph tests; external model
  responses alone are simulated.

## Runtime behavior

```python
coordinator = A1Coordinator(
    store, retriever, client, budget, inventory_store=inventory,
    enable_a3=True, enable_a4=True,
    enable_a4_llm=False,  # deterministic audit only
)
state = coordinator.run(request)
```

Calling the coordinator with real A1 clients still invokes Qdrant and OpenAI
for A1. This example is not an offline fixture runner. To enable the separate
paid semantic critic, explicitly set `enable_a4_llm=True`; it shares the
existing budget ledger and requires SDK retries disabled. No new live run was
performed for this integration. A4 trace `llm_invoked` distinguishes the modes.

A1 uncertainty/Group C and partial A2 findings retain the existing stop before
downstream stages. After a validated A3 plan, A4 runs its deterministic audit.
Blocking/fatal audit outcomes prevent a semantic model request. Current A3
always requires human review, so a clean A4 audit ends at `human_review`, not
stock clearance. The `approved` critic verdict remains in its uploaded
vocabulary but is not reachable from the current review-required A3 contract.

For a fixable A3 revision request, the coordinator preserves `prior_a3` and
`prior_a4`, reruns canonical A3 once from unchanged A2, and audits at round 1.
Round 1 cannot request another revision. Both critic traces retain their
distinct run-linked ledger calls. Replanning does not execute model-generated
instructions, learn a new rule or guarantee a changed plan. The deterministic
planner normally returns the same result; a persistent objection goes to a
human. A1/A2-targeted requests remain visible and escalate without rerunning
those stages.

This is a bounded first correction path, not the complete v4.2 targeted
A1/A2 correction mechanism. Defining targeted correction inputs, validating
changed upstream facts, and rerunning affected downstream stages remain
explicit unfinished architecture work. Durable human approval/resumption and
production hosting also remain pending.

## Reproduce and inspect

From the repository root:

```bash
.venv/bin/python -B -m pytest tests/test_a4_checks.py tests/test_a4_agent.py \
  tests/test_a4_coordinator.py -q -p no:cacheprovider
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py --ignore=tests/test_a2_review_fixes.py
.venv/bin/python -B -m pytest tests/a2_development_inventory_checks.py \
  tests/a2_development_demo_checks.py -q -p no:cacheprovider \
  -o junit_family=xunit1 --junitxml=runtime/a1_a2_a3_a4_development_checks.xml
.venv/bin/python -B tests/a2_development_demo.py --enable-a3 --enable-a4 \
  --output runtime/a1_a2_a3_a4_offline_demo_v1
```

The demonstration directory already exists locally. Choose a new output name
to rerun; existing artifacts are never overwritten. It contains a summary,
three complete case states and checksums. A1 model/vector responses are
fixtures and A4 is deterministic in this runner. Generated files use `0600`
and remain ignored by Git.

The explicit dataset suite covers 18 approved development recalls in each of
three configurations: A1/A2, A1/A2/A3, and A1/A2/A3/A4 (54 executions), one
36-row SQLite round trip and two original demo checks: 57 checks total.
In the A4 configuration, the eight resolved A2 cases reach an audit without
blocking findings and retain human review. The ten earlier review cases never
reach A2/A3/A4. No evaluation labels or unselected inventory objects were used.
The four original full-package modules (21 tests) remain unchanged and unrun.

## Research basis and limits

Actual local verification on 24 November 2026:

- Initial focused A4 tests: 51 passed in 3.12 seconds. Four subsequent
  configuration tests also passed in the final regression gate.
- Final permitted regression selection: **1,089 passed in 9.03 seconds**.
- Explicit development/demo checks: **57 passed in 2.68 seconds**.
- All three saved demo states reloaded as `CaseState`; checksums and `0600`
  permissions passed independent read-only checks.
- `pip check`: no broken requirements. Pip disabled its unavailable cache;
  no dependency was installed.
- The first focused attempt exposed a missing fixture import in the new
  critic test module; it was corrected before the passing runs above.
- No paid model or Qdrant service requests were made.

The [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
describes schema-constrained responses and separate refusal handling. Schema
compliance does not establish whether a claim is true; this implementation
adds explicit reference and consistency checks and accounts for rejected
responses. Valid citation IDs alone cannot prove semantic support for every
critic claim. Human review remains necessary.

[Pydantic model guidance](https://docs.pydantic.dev/latest/concepts/models/)
informs fresh-snapshot validation at mutable handoff boundaries. The
[LangGraph conditional-edge API](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)
informs explicit stage routing. No framework abstraction or dependency was
added for these changes.

A2 owner sign-off is still deferred. No tests or labels were weakened to
obtain passing results. These are prototype verification results, not a
claim of production readiness, regulatory compliance or matching accuracy.
