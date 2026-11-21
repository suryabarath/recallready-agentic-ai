# Agent 2 to Coordinator Patching Guide (`recallready-agentic-ai-feature-a1-coordinator`)

**Target Folder:** `recallready-agentic-ai-feature-a1-coordinator`  
**Source Implementation:** `recallready-agentic-ai-agent2`  
**Requirements Reference:** `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md`

---

## 1. Overview of Required Changes

The current `recallready-agentic-ai-feature-a1-coordinator` implements an A1-only LangGraph workflow (`case_state.py` and `coordinator.py`). To integrate Agent 2 (A2 Inventory Investigation Agent) into the coordinator while preserving the strict evidence trust boundary and Pydantic validation rules:

1. **Copy A2 Modules & Tests** from `recallready-agentic-ai-agent2` into `recallready-agentic-ai-feature-a1-coordinator`.
2. **Patch `case_state.py`** to add the typed `a2: A2RunEnvelope | None = None` field, A2 lifecycle events (`a2_matched`, `a2_partial`, `a2_no_match`, `a2_unresolved`, `a2_completed`), A2 terminal/handoff statuses (`a2_completed`), and post-validation invariants.
3. **Patch `coordinator.py`** to accept the read-only `InventoryStore`, add the `investigate_a2` node, route validated `a1_completed` cases into A2, and route A2 outcomes (`matched` / `no_match` -> `complete_a2`, `partial` -> `review`, `unresolved` -> `stop`).
4. **Build Synthetic Retailer Inventory SQLite Store** using `inventory_loader.py` from `02_retailer_inventory_SYNTHETIC.json`.

---

## 2. Files to Copy into `recallready-agentic-ai-feature-a1-coordinator`

Copy the following 8 files directly from `recallready-agentic-ai-agent2` into `recallready-agentic-ai-feature-a1-coordinator`:

```text
a2_agent.py
inventory_store.py
inventory_match.py
inventory_loader.py
tests/test_a2_agent.py
tests/test_inventory_store.py
tests/test_inventory_match.py
tests/test_inventory_loader.py
```

### Summary of New Modules
- **`inventory_loader.py`**: Loads `02_retailer_inventory_SYNTHETIC.json` into a synthetic SQLite database (`manifest` + `inventory` tables), verifying 48 sets (`SIMSET-001`..`SIMSET-048`), 96 rows (1 `*-A` and 1 `*-B` per set), exact column types, and SHA-256 checksum.
- **`inventory_store.py`**: Read-only SQLite store (`InventoryStore`) opening the database with `?mode=ro` and `PRAGMA query_only=ON`. Implements `find_inventory_candidates(...)` in literal priority order (UPC digits -> exact lot code -> deterministic product label / package size -> supporting brand) and `resolve_candidate_ids(...)` to verify any Qdrant/vector candidate IDs against SQLite.
- **`inventory_match.py`**: Pure deterministic comparison tool `compare_recall_to_inventory(recall_attributes, inventory_row) -> InventoryMatch` with zero LLM, Qdrant, or SQLite write calls. Preserves leading zeros on lot codes, normalizes UPC separators/spaces for digit comparison only, parses numeric/unit package sizes (`7.05oz` == `7.05 oz`), keeps blank inventory brands as `unknown`, and excludes `*-B` distractors deterministically.
- **`a2_agent.py`**: Defines strict Pydantic schemas (`InventoryFinding`, `A2Error`, `A2RunEnvelope`) and `run_a2(inventory_store, envelope, ...) -> A2RunEnvelope`. Supports both `A1Result` (`0.1-proposed`) and `GroupCResult` (`0.2-group-c-provisional`).

---

## 3. Patching `case_state.py`

### 3.1 Imports to Add
Import `A2Error` and `A2RunEnvelope` from `a2_agent`:

```python
from a2_agent import A2Error, A2RunEnvelope
```

### 3.2 Update `CaseEvent` Literal
Extend `CaseEvent.event` to record A2 execution outcomes:

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
        "human_review",
        "stopped",
    ]
    timestamp_utc: Nonblank
```

### 3.3 Update `CaseState` Fields and `check_outcome` Validator
Add `a2: A2RunEnvelope | None = None`, allow `"a2_completed"` in `CaseState.status`, and validate A2 state consistency in `check_outcome`:

```python
class CaseState(CaseRequest):
    status: Literal[
        "pending",
        "running",
        "a1_completed",
        "a2_completed",
        "human_review",
        "unresolved",
    ] = "pending"
    a1: A1RunEnvelope | None = None
    a2: A2RunEnvelope | None = None
    events: list[CaseEvent] = Field(default_factory=list)
    errors: list[RunError | A2Error] = Field(default_factory=list)
    review_reason: Nonblank | None = None
    revision_count: Literal[0] = 0
```

Add the following validation checks inside `CaseState.check_outcome(self) -> Self`:

```python
        if self.a2 is not None:
            if (self.a2.case_id, self.a2.run_id, self.a2.recall_number, self.a2.snapshot_id) != (
                self.case_id, self.run_id, self.recall_number, self.snapshot_id
            ):
                raise ValueError("A2 envelope differs from selected case/run context")
            if self.a1 is None or self.a1.status != "validated":
                raise ValueError("A2 envelope cannot exist without a validated A1 envelope")
            result = self.a1.result
            base = result.base if isinstance(result, GroupCResult) else result
            if self.a2.event_id != base.event_id:
                raise ValueError("A2 event_id differs from canonical A1 event_id")
        if self.status == "a2_completed":
            if (
                self.a1 is None
                or self.a1.status != "validated"
                or self.a2 is None
                or self.a2.status not in ("matched", "no_match")
                or self.errors
            ):
                raise ValueError("a2_completed requires validated A1, matched/no_match A2, and no errors")
```

Also update the `needs_review` check in `check_outcome` so that `human_review` is valid when either A1 requires review OR A2 returned `status == "partial"` (or `a2.requires_human_review`):

```python
        if self.status in ("a1_completed", "a2_completed", "human_review"):
            if self.a1 is None or self.a1.status != "validated" or self.errors:
                raise ValueError("Successful or review route requires a validated A1 envelope and no errors")
            result = self.a1.result
            base = result.base if isinstance(result, GroupCResult) else result
            a1_needs_review = isinstance(result, GroupCResult) or bool(base.facts.uncertainties)
            a2_needs_review = self.a2 is not None and (
                self.a2.status == "partial" or self.a2.requires_human_review
            )
            if self.status == "human_review" and not (a1_needs_review or a2_needs_review):
                raise ValueError("human_review route requires A1 or A2 review uncertainty")
            if self.status in ("a1_completed", "a2_completed") and (a1_needs_review or a2_needs_review):
                raise ValueError("Completed route cannot bypass A1 or A2 human review requirement")
```

---

## 4. Patching `coordinator.py`

### 4.1 Constructor and Graph Wiring
Update `A1Coordinator.__init__` to accept an optional `inventory_store: InventoryStore | None = None` (so existing A1-only tests continue to pass when `inventory_store=None`, while full A1->A2 orchestration runs when `inventory_store` is provided):

```python
from a2_agent import A2Error, run_a2
from inventory_store import InventoryStore
```

In `A1Coordinator.__init__`:
```python
    def __init__(
        self,
        store: FDAStore,
        retriever: QdrantA1,
        client: OpenAI,
        budget: Budget,
        *,
        inventory_store: InventoryStore | None = None,
        approved_lots: tuple[HumanLotApproval, ...] = (),
        max_output_tokens: int = 4000,
    ):
        self.store, self.retriever, self.client, self.budget = store, retriever, client, budget
        self.inventory_store = inventory_store
        self.approved_lots = approved_lots
        self.max_output_tokens = max_output_tokens
        graph = StateGraph(CaseState, input_schema=CaseRequest, output_schema=CaseState)
        graph.add_node("begin", self._begin)
        graph.add_node("interpret_a1", self._interpret)
        graph.add_node("complete", self._complete)
        graph.add_node("investigate_a2", self._investigate_a2)
        graph.add_node("complete_a2", self._complete_a2)
        graph.add_node("review", self._review)
        graph.add_node("stop", self._stop)
        graph.add_edge(START, "begin")
        graph.add_edge("begin", "interpret_a1")
        graph.add_conditional_edges(
            "interpret_a1",
            self._route,
            {"complete": "complete", "review": "review", "stop": "stop"},
        )
        graph.add_conditional_edges(
            "complete",
            self._route_after_a1_complete,
            {"investigate_a2": "investigate_a2", "end": END},
        )
        graph.add_conditional_edges(
            "investigate_a2",
            self._route_a2,
            {"complete_a2": "complete_a2", "review": "review", "stop": "stop"},
        )
        for terminal in ("complete_a2", "review", "stop"):
            graph.add_edge(terminal, END)
        self._graph = graph.compile()
```

### 4.2 Add A2 Node and Routing Methods to `A1Coordinator`

Per Section 7 of `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md`:
- **A1 unresolved or unexpected failure**: stops before A2 (`_route` -> `"stop"`).
- **A1 `human_review` (Group C or any A1 uncertainty)**: stops at `"review"` before A2 (`_route` -> `"review"`).
- **A1 `a1_completed`**: transitions to `investigate_a2` when `self.inventory_store is not None`.
- **A2 `matched` or `no_match`**: transitions to `complete_a2` (`status = "a2_completed"`), ready for A3 handoff.
- **A2 `partial`**: transitions to `review` (`status = "human_review"`, preserving partial findings and setting `review_reason`).
- **A2 `unresolved`**: transitions to `stop` (`status = "unresolved"`, appending `a2.error` to `state.errors`).

```python
    def _route_after_a1_complete(self, state: CaseState) -> str:
        if self.inventory_store is None:
            return "end"
        return "investigate_a2"

    def _investigate_a2(self, state: CaseState) -> dict:
        try:
            a2_envelope = run_a2(
                self.inventory_store,
                state.a1,
                case_id=state.case_id,
                run_id=state.run_id,
                recall_number=state.recall_number,
                snapshot_id=state.snapshot_id,
                event_id=state.event_id,
            )
        except Exception:
            error = A2Error(
                code="inventory_match_failed",
                message="A2 execution failed unexpectedly; inventory outcome requires review.",
            )
            return {
                "errors": state.errors + [error],
                "events": state.events + [_event("a2_unexpected_failure")],
            }
        event_map = {
            "matched": "a2_matched",
            "partial": "a2_partial",
            "no_match": "a2_no_match",
            "unresolved": "a2_unresolved",
        }
        errors = state.errors + ([a2_envelope.error] if a2_envelope.error else [])
        return {
            "a2": a2_envelope,
            "errors": errors,
            "events": state.events + [_event(event_map[a2_envelope.status])],
        }

    @staticmethod
    def _route_a2(state: CaseState) -> str:
        if state.a2 is None or state.a2.status == "unresolved":
            return "stop"
        if state.a2.status == "partial" or state.a2.requires_human_review:
            return "review"
        return "complete_a2"

    @staticmethod
    def _complete_a2(state: CaseState) -> dict:
        return {"status": "a2_completed", "events": state.events + [_event("a2_completed")]}
```

And update `_review` in `coordinator.py` so its `review_reason` reflects whether A1 or A2 triggered human review:

```python
    @staticmethod
    def _review(state: CaseState) -> dict:
        if state.a2 is not None and (state.a2.status == "partial" or state.a2.requires_human_review):
            reason = "A2 partial inventory match or missing scope attributes require human review."
        else:
            reason = "A1 relationships or uncertainties require human review."
        return {
            "status": "human_review",
            "review_reason": reason,
            "events": state.events + [_event("human_review")],
        }
```

---

## 5. Verification Steps After Patching Coordinator

1. **Build the synthetic retailer inventory SQLite database**:
   ```bash
   python inventory_loader.py runtime/retailer_inventory.sqlite --json-path ../02_retailer_inventory_SYNTHETIC.json
   ```
2. **Run focused A2 unit and acceptance tests**:
   ```bash
   python -m unittest discover -s tests -p "test_*.py" -v
   ```
   Or with pytest in the project `.venv`:
   ```bash
   .venv/bin/python -m pytest tests/test_inventory_loader.py tests/test_inventory_store.py tests/test_inventory_match.py tests/test_a2_agent.py -q
   ```
3. **Run full coordinator regression suite**:
   ```bash
   .venv/bin/python -m pytest -q
   ```
