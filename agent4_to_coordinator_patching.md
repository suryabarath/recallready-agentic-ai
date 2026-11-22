# Agent 4 to Coordinator Patching Guide (`recallready-agentic-ai-feature-a1-coordinator`)

**Target Folder:** `recallready-agentic-ai-feature-a1-coordinator`  
**Source Implementation:** `recallready-agentic-ai-agent4`  
**Requirements Reference:** `A4_AGENT_IMPLEMENTATION_REQUIREMENTS.md`  
**Prerequisite:** Apply `agent2_to_coordinator_patching.md` and Member 3's A3 coordinator wiring first so `CaseState` already carries `a2` (`A2RunEnvelope`) and `a3` (`A3RunEnvelope`).

---

## 1. Upstream Compatibility Summary (A1 & A2 Need NO Patch)

- **Agent 1 (`recallready-agentic-ai-baseline-agent1-working`):** **No code changes required.** A4 directly consumes `A1RunEnvelope`, `A1Result`, `GroupCResult`, `FDAStore`, `validate_literal_identifier`, `Budget`, `RunRecorder`, and `active_run` without modifying any A1 schema or module.
- **Agent 2 (`recallready-agentic-ai-baseline-agent2`):** **No code changes required.** A4 directly consumes `A2RunEnvelope`, `InventoryFinding`, and `InventoryStore.resolve_candidate_ids` without modifying any A2 module.
- **Agent 3 (Pending from Member 3):** Once Member 3 merges `a3_agent.py`, either align `A3RunEnvelope`/`ActionRecommendation` imports directly or update the single `normalize_a3_envelope(...)` adapter in `a4_agent.py` (lines 204–214).

---

## 2. Files to Copy into `recallready-agentic-ai-feature-a1-coordinator`

Copy these 4 files directly from `recallready-agentic-ai-agent4` into `recallready-agentic-ai-feature-a1-coordinator`:

```text
a4_checks.py
a4_agent.py
tests/test_a4_checks.py
tests/test_a4_agent.py
```

---

## 3. Patching `case_state.py`

### 3.1 Imports to Add
```python
from typing import Annotated, Literal, Self
from a4_agent import A4Error, A4RunEnvelope, RevisionRequest
```
*(Plus Member 3's `A3Error`, `A3RunEnvelope` once merged.)*

### 3.2 Extend `CaseEvent.event` Literal
Add the A4 and revision-replay lifecycle events:

```python
class CaseEvent(StrictModel):
    event: Literal[
        "started",
        "a1_validated",
        "a1_unresolved",
        "a1_unexpected_failure",
        "a1_completed",
        "a2_matched",
        "a2_partial",
        "a2_no_match",
        "a2_unresolved",
        "a2_unexpected_failure",
        "a2_completed",
        "a3_planned",
        "a3_review_required",
        "a3_unresolved",
        "a3_unexpected_failure",
        "a4_approved",
        "a4_revise_requested",
        "a4_human_review",
        "a4_unresolved",
        "a4_unexpected_failure",
        "revision_replay_started",
        "completed",
        "human_review",
        "stopped",
    ]
    timestamp_utc: Nonblank
```

### 3.3 Update `CaseState` Fields
Replace `revision_count: Literal[0] = 0` with `Annotated[int, Field(ge=0, le=1)] = 0`, add `"completed"` to `status`, and add `a4`, `prior_a4` (audit trail preservation across replay), and `active_revision`:

```python
class CaseState(CaseRequest):
    status: Literal[
        "pending",
        "running",
        "a1_completed",
        "a2_completed",
        "a3_completed",
        "completed",
        "human_review",
        "unresolved",
    ] = "pending"
    a1: A1RunEnvelope | None = None
    a2: A2RunEnvelope | None = None
    a3: A3RunEnvelope | None = None
    a4: A4RunEnvelope | None = None
    prior_a4: A4RunEnvelope | None = None  # Preserves round-0 findings & token trace during replay
    active_revision: RevisionRequest | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError | A2Error | A3Error | A4Error] = Field(default_factory=list)
    review_reason: Nonblank | None = None
    revision_count: Annotated[int, Field(ge=0, le=1)] = 0
```

### 3.4 Extend `CaseState.check_outcome(self) -> Self`
Add these invariants inside `check_outcome`:

```python
        if self.prior_a4 is not None:
            if self.revision_count != 1 or self.prior_a4.verdict != "revise" or self.prior_a4.revision_round != 0:
                raise ValueError("prior_a4 is valid only after a round-0 targeted revision")
            if (self.prior_a4.case_id, self.prior_a4.run_id, self.prior_a4.recall_number, self.prior_a4.snapshot_id) != (
                self.case_id, self.run_id, self.recall_number, self.snapshot_id
            ):
                raise ValueError("prior_a4 differs from selected case/run context")

        if self.a4 is not None:
            if (self.a4.case_id, self.a4.run_id, self.a4.recall_number, self.a4.snapshot_id) != (
                self.case_id, self.run_id, self.recall_number, self.snapshot_id
            ):
                raise ValueError("A4 envelope differs from selected case/run context")
            if self.status in ("completed", "human_review", "unresolved") and self.a4.revision_round != self.revision_count:
                raise ValueError("Terminal A4 revision_round must equal CaseState.revision_count")

        if self.status == "completed":
            if (
                self.a1 is None or self.a1.status != "validated"
                or self.a2 is None or self.a2.status not in ("matched", "no_match")
                or self.a3 is None or self.a3.status != "planned"
                or self.a4 is None or self.a4.verdict != "approved"
                or not self.a4.prototype_disclaimer_verified
                or self.a4.requires_human_review
                or self.errors
            ):
                raise ValueError("completed status requires A4 approved verdict, verified disclaimer, and no errors")
```

Also update the `human_review` and `unresolved` validation branches in `check_outcome`:
- Include `a4_needs_review = self.a4 is not None and (self.a4.verdict == "human_review" or self.a4.requires_human_review)` alongside `a1_needs_review`, `a2_needs_review`, and `a3_needs_review`.
- **CRITICAL existing `case_state.py` line 60 fix:** The A1-only `case_state.py` currently has:
  ```python
  if self.status == "unresolved":
      if not self.errors or (self.a1 is not None and self.a1.status != "unresolved"):
          raise ValueError("Unresolved case requires an error and no validated A1 result")
  ```
  Replace this condition so downstream unresolved outcomes (`a2.status == "unresolved"`, `a3.status == "unresolved"`, `a4.verdict == "unresolved"`, or unexpected coordinator failures after A1 succeeded) are accepted whenever `self.errors` is non-empty:
  ```python
  if self.status == "unresolved":
      if not self.errors:
          raise ValueError("Unresolved case requires at least one error")
      if (
          self.a1 is not None and self.a1.status == "validated"
          and (self.a2 is None or self.a2.status != "unresolved")
          and (self.a3 is None or self.a3.status != "unresolved")
          and (self.a4 is None or self.a4.verdict != "unresolved")
          and not any(e.code in ("coordinator_internal_failure", "inventory_match_failed", "critic_internal_failure") for e in self.errors)
      ):
          raise ValueError("Unresolved case requires an unresolved upstream envelope or unexpected coordinator error")
  ```

---

## 4. Patching `coordinator.py`

### 4.1 Imports & Constructor Parameters
Add imports:
```python
from a4_agent import A4Error, run_a4
```

Add optional keyword arguments to the coordinator constructor (keeping defaults backward-compatible for A1/A2-only tests):
```python
        enable_a4: bool = False,
        a4_enable_llm_critic: bool = True,
        a4_max_output_tokens: int = 1500,
```
Store `self.enable_a4`, `self.a4_enable_llm_critic`, and `self.a4_max_output_tokens`.

### 4.2 Increase LangGraph `recursion_limit`
In `run(self, request: CaseRequest | dict) -> CaseState`, increase `recursion_limit` from `8` to `20` (still keeping `with tracing_context(enabled=False):`):
```python
        with tracing_context(enabled=False):
            output = self._graph.invoke(selected.model_dump(), config={"recursion_limit": 20})
```
*Why:* One full replay (`begin -> interpret_a1 -> investigate_a2 -> plan_a3 -> critique_a4 -> prepare_revision -> interpret_a1 -> investigate_a2 -> plan_a3 -> critique_a4 -> terminal`) visits up to 11 nodes. The graph's conditional edges + `CaseState.revision_count <= 1` guarantee termination after at most 1 revision.

### 4.3 Graph Nodes & Conditional Edges
Add 3 nodes to `StateGraph`:
```python
        graph.add_node("critique_a4", self._critique_a4)
        graph.add_node("prepare_revision", self._prepare_revision)
        graph.add_node("complete_case", self._complete_case)
```

Wire edges after `plan_a3`:
```python
        # Route from plan_a3 -> critique_a4 when enable_a4 is True and A3 is not unresolved
        graph.add_conditional_edges(
            "plan_a3",
            self._route_a3,
            {"critique_a4": "critique_a4", "complete_a3": "complete_a3", "review": "review", "stop": "stop"},
        )
        graph.add_conditional_edges(
            "critique_a4",
            self._route_a4,
            {
                "complete_case": "complete_case",
                "prepare_revision": "prepare_revision",
                "review": "review",
                "stop": "stop",
            },
        )
        graph.add_conditional_edges(
            "prepare_revision",
            self._route_revision_target,
            {
                "a1": "interpret_a1",
                "a2": "investigate_a2",
                "a3": "plan_a3",
            },
        )
        graph.add_edge("complete_case", END)
```

### 4.4 Node & Router Implementations
```python
    def _critique_a4(self, state: CaseState) -> dict:
        try:
            a4_envelope = run_a4(
                self.store,
                self.inventory_store,
                state.a1,
                state.a2,
                state.a3,
                case_id=state.case_id,
                run_id=state.run_id,
                recall_number=state.recall_number,
                snapshot_id=state.snapshot_id,
                event_id=state.event_id,
                revision_round=state.revision_count,
                client=self.client if self.a4_enable_llm_critic else None,
                budget=self.budget if self.a4_enable_llm_critic else None,
                max_output_tokens=self.a4_max_output_tokens,
                enable_llm_critic=self.a4_enable_llm_critic,
            )
        except Exception:
            error = A4Error(
                stage="coordinator",
                code="critic_internal_failure",
                message="A4 execution failed unexpectedly; critic outcome requires review.",
                request_state="outcome_unknown",
            )
            return {
                "errors": state.errors + [error],
                "events": state.events + [_event("a4_unexpected_failure")],
            }

        event_map = {
            "approved": "a4_approved",
            "revise": "a4_revise_requested",
            "human_review": "a4_human_review",
            "unresolved": "a4_unresolved",
        }
        errors = state.errors + ([a4_envelope.error] if a4_envelope.error else [])
        return {
            "a4": a4_envelope,
            "errors": errors,
            "events": state.events + [_event(event_map[a4_envelope.verdict])],
        }

    @staticmethod
    def _route_a4(state: CaseState) -> str:
        if state.a4 is None or state.a4.verdict == "unresolved":
            return "stop"
        if state.a4.verdict == "revise" and state.revision_count == 0 and state.a4.revision_request is not None:
            return "prepare_revision"
        if state.a4.verdict == "approved" and not state.a4.requires_human_review:
            return "complete_case"
        return "review"

    @staticmethod
    def _prepare_revision(state: CaseState) -> dict:
        rev = state.a4.revision_request
        updates: dict = {
            "revision_count": 1,
            "prior_a4": state.a4,
            "active_revision": rev,
            "a4": None,
            "events": state.events + [_event("revision_replay_started")],
        }
        if rev.target_agent == "a1":
            updates.update(a1=None, a2=None, a3=None)
        elif rev.target_agent == "a2":
            updates.update(a2=None, a3=None)
        else:
            updates.update(a3=None)
        return updates

    @staticmethod
    def _route_revision_target(state: CaseState) -> str:
        return state.active_revision.target_agent

    @staticmethod
    def _complete_case(state: CaseState) -> dict:
        return {"status": "completed", "events": state.events + [_event("completed")]}
```

And update `_review` to distinguish A4 human review:
```python
        if state.a4 is not None and (state.a4.verdict == "human_review" or state.a4.requires_human_review):
            reason = "A4 safety critic flagged unresolved safety, evidence, or prototype-boundary issues requiring human review."
```

> **Passing `state.active_revision` on Replay:** In `_plan_a3` (and optionally `_investigate_a2` / `_interpret`), pass `revision_request=state.active_revision` when `state.active_revision is not None and state.active_revision.target_agent == "<agent>"`. Because `Budget.run_calls` uses composite `PRIMARY KEY(run_id, call_id)`, reusing `state.run_id` across round 0 and round 1 atomically links all ledger charges to the same run.

---

## 5. Verification Steps After Patching Coordinator

1. Run A4 standalone deterministic and integration tests (offline, 0 API keys):
   ```bash
   .venv/bin/python -m pytest tests/test_a4_checks.py tests/test_a4_agent.py -q
   ```
   *(On Windows: `.venv\Scripts\python.exe -m pytest tests/test_a4_checks.py tests/test_a4_agent.py -q`)*
2. Add coordinator-level tests verifying:
   - Clean `A1 -> A2 -> A3 -> A4(approved) -> completed` (`revision_count == 0`).
   - Targeted revision `A4(revise, target="a3") -> prepare_revision -> plan_a3 -> critique_a4(approved) -> completed` (`revision_count == 1`, `prior_a4.verdict == "revise"` preserved).
   - Max-1 cap: `A4(revise)` on round 0 followed by blocking failure on round 1 ends at `human_review` (`revision_count == 1`, never loops).
   - Upstream replay failure (`unresolved` during round 1) ends cleanly at `stopped`.
3. Run the full regression suite:
   ```bash
   .venv/bin/python -m pytest -q
   ```
