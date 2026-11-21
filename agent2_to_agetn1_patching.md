# Agent 2 to Agent 1 Patching Guide (`recallready-agentic-ai-baseline-agent1-working`)

**Target Folder:** `recallready-agentic-ai-baseline-agent1-working`  
**Source Implementation:** `recallready-agentic-ai-agent2`  
**Requirements Reference:** `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md`

---

## 1. Executive Summary: Does Agent 1 Require Code Changes?

Per Section 9 of `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md`:
> *"The current A1 modules should not be modified unless the integration contract requires a shared state field."*

And per Section 2 of `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md`:
> *"A2's primary input is the validated A1 envelope already produced by `run_a1_with_trace`. A2 must accept the envelope itself or an integration object that contains a strict reference to the same envelope. Do not copy A1 facts into a second editable Pydantic model."*

**Because A2 directly consumes `A1RunEnvelope` (from `a1_run.py`), `A1Result` (from `models.py`), and `GroupCResult` (from `group_c_contract.py`) without altering any inner A1 schemas, no existing files in `recallready-agentic-ai-baseline-agent1-working` need to be modified for A1 to produce valid inputs for A2.**

However, if the team wishes to run A2 standalone directly on top of `recallready-agentic-ai-baseline-agent1-working` (without the LangGraph coordinator) or address optional A1-to-A2 handoff edge cases, follow the technical specifications below.

---

## 2. Running A2 Standalone with `recallready-agentic-ai-baseline-agent1-working`

`recallready-agentic-ai-baseline-agent1-working` already contains all A1 modules (`a1_run.py`, `a1_trace.py`, `models.py`, `group_c_contract.py`, `source.py`, `validation.py`, `fda_store.py`, `qdrant_a1.py`).

To enable A2 directly inside `recallready-agentic-ai-baseline-agent1-working` without modifying any existing A1 files, copy the following 8 files from `recallready-agentic-ai-agent2`:

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

With those files added, an A1 envelope produced by `run_a1_with_trace` in `a1_run.py` can be passed directly into `run_a2`:

```python
from pathlib import Path
from a1_run import run_a1_with_trace
from a2_agent import run_a2
from inventory_store import InventoryStore

with InventoryStore(Path("runtime/retailer_inventory.sqlite")) as inv_store:
    a2_envelope = run_a2(
        inv_store,
        a1_envelope,
        case_id="case-001",
        run_id=a1_envelope.run_id,
        recall_number=a1_envelope.trace.recall_number,
        snapshot_id=a1_envelope.trace.snapshot_id,
        event_id=a1_envelope.trace.event_id,
    )
```

---

## 3. Optional A1 Enhancements for Downstream A2 Coverage

While no breaking changes to A1 are required, our analysis of the 18 development recalls in A1 against `02_retailer_inventory_SYNTHETIC.json` identified three specific A1-to-A2 interaction details that the A1 owner (Member 2) and Integration lead (Member 1) should be aware of:

### 3.1 `batch` vs `lot` Identifier Kind in Group B (`F-0882-2023`, `F-1025-2023`)
- **Current A1 Behavior:** In `validation.py`, A1 distinguishes `kind="lot"` (when the FDA text says `Lot`) from `kind="batch"` (when the FDA text says `Batch #2-401` in `F-0882-2023` or `Batch #101097` in `F-1025-2023`).
- **A2 Requirement (Section 4.1):** The requirements table specifies:
  > `Lot number | Source identifier kind lot, or explicit Group C lot_date relation | Exact string comparison, preserving leading zeros and case`
- **Impact:** In `02_retailer_inventory_SYNTHETIC.json`, the inventory table only has a `lot_code` column (`"2-402"` for `INV-019-A` and `"101091"` for `INV-021-A`).
- **Implemented in A2 (no A1 change needed):** `_extract_a1_scope` in `a2_agent.py` now compares A1 `batch` identifiers against inventory `lot_code` (`ident.kind in ("lot", "batch")`), using exact string comparison. Every finding that matched through a batch value carries the reason code `lot_source:batch_identifier:<value>`, so A3 can see it. A1 keeps `"batch"` distinct in its own provenance; `models.py` and `validation.py` are unchanged.
- **Open decision for M1:** Confirm that treating `batch` as lot-equivalent for inventory comparison is acceptable. If M1 rejects it, remove `"batch"` from that kind check in `a2_agent.py`; recalls with only a batch identifier will then return `unresolved` (`ambiguous_recall_scope`).
- **Current behavior on the fixture:** `F-0882-2023` (batch `2-401` vs inventory `2-402`) and `F-1025-2023` (batch `101097` vs inventory `101091`) return `no_match`, an explicit lot mismatch.

### 3.2 `HumanLotApproval` and Residual `uncertainties` in `validation.py` (`F-0705-2025`, `F-1472-2024`)
- **Current A1 Behavior:** When `approved_lots` (`docs/a1_member1_lot_approval.json`) is passed into `run_a1_with_trace`, `validation.py` allows an ambiguous lot span to be validated as `kind="lot"`, **provided** the model emitted `kind="lot"`. However, As noted in `A1_COORDINATOR_GUIDE_2026-11-20.md`:
  > *"Group A/B uncertainties also route to review; a caller-supplied historical lot approval does not erase uncertainties."*
- **Impact on A2:** Because A1 preserves `facts.uncertainties` even when `HumanLotApproval` is supplied, the coordinator routes `F-0705-2025` to `human_review` and does not invoke A2 automatically unless human review resumes the case (`allow_group_c_or_uncertain=True` in `run_a2`, which outputs `partial` findings with `requires_human_review=True` so human uncertainty is never converted into an exact match).
- **Recommendation:** Keep A1's current conservative behavior unchanged. It satisfies Section 1 Rule 4 of `A2_AGENT_IMPLEMENTATION_REQUIREMENTS.md` (*"Human uncertainty from A1 remains visible and must not be converted into an exact match"*).

### 3.3 `RunTrace.event_id` Population on Unresolved A1 Runs (`a1_service.py`)
- **Current A1 Behavior:** In `a1_service.py`, `recorder.trace.event_id = record["event_id"]` is set after `store.lookup(...)` succeeds. If `store.lookup(...)` fails during `preflight`, `trace.event_id` remains `None`.
- **Impact on A2:** `a2_agent.py` safely handles `envelope.trace.event_id is None` when `envelope.status == "unresolved"` and returns `status="unresolved"` with `error.code="a1_unresolved"`. No patch to `a1_service.py` is required.
