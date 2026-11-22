# Agent 2 isolated integration

## Scope and provenance

This local development slice connects the verified A1 coordinator to Agent 2
inventory investigation. It stops after A2 or at human review. Agent 3 and
Agent 4 are outside this slice.

Branch: `feature/a2-isolated-integration`. Its starting point is `9267620`,
the verified A1 coordinator plus the handoff dependency correction.
The separate working directory is `recallready/a2_isolated_workspace`.
The original `code_workspace` and shared GitHub branch are unchanged by this
integration. Source ZIP and runtime credentials remain outside Git.

The initial `a2_agent.py`, `inventory_loader.py`, `inventory_match.py`,
`inventory_store.py` and their existing tests came from commit
`cd8b5bfc8eeeadbd4a4d98c858d150e9aa3db00d`, authored by
`midhun-not-mithun`. That commit's integration notes attribute the A2
implementation to the team's Agent 2 branch. The additions here are the
bounded A2 coordinator connection, stronger boundary validation, independent
synthetic integration tests, and this operating guide. No A3 module or
integration patch was imported.

## Execution and outcomes

```text
Fresh CaseRequest -> A1
  A1 unresolved                    -> unresolved
  Group C or A1 uncertainty        -> human_review, before any inventory read
  Validated A1, no inventory store -> a1_completed
  Validated A1, inventory store    -> A2
    exact findings, no uncertainty -> a2_completed
    no demonstrated match         -> a2_completed
    any partial finding           -> human_review
    unresolved or exception       -> unresolved
```

`a2_completed` means the A2 investigation stage returned a resolved result.
It does not authorize stock actions, establish safety, or close the full case.
Mixed exact and partial findings retain their separate rows, quantities,
locations and review requirement. A2 makes no model requests and performs
no inventory writes. A1 continues to use the existing interpretation service.

Pass an open, caller-owned `InventoryStore` to the existing constructor:

```python
from coordinator import A1Coordinator
from inventory_store import InventoryStore

with InventoryStore(inventory_db_path) as inventory:
    coordinator = A1Coordinator(
        store, retriever, client, budget, inventory_store=inventory,
    )
    state = coordinator.run(request)
```

`store`, `retriever`, `client`, `budget` and `request` use the existing
[A1 setup](A1_HANDOFF_2026-11-20.md). Using live clients invokes Qdrant and
potentially paid OpenAI calls for A1. The tests below simulate their responses
and require no credentials. The graph owns neither the source connection nor
the inventory connection; callers close both. SQLite connections should stay
on their owning thread.

## Boundary validation and failure handling

A2 runs while the case remains `running`. A typed A2 error or unexpected
exception can therefore reach the stop node without contradicting a completed
case status. The graph does not retry A1 or A2 automatically.

Every finding must match its A2 envelope's case, run, recall, snapshot and
event. Duplicate item IDs, findings marked `no_match`, and exact findings with
a concrete attribute mismatch are rejected. The envelope's review flag must
preserve review required by any finding.

CaseState additionally checks A2 against the selected A1 context. Finding
evidence IDs and identifier values must belong to that validated A1 result;
uncertainties cannot be altered. Group C and uncertain A1 results cannot carry
A2 results through this graph. A2 output is checked before accepting the node
update; invalid output becomes an unresolved failure with a safe error.

These checks bind findings to A1 evidence. Their inventory attributes are
authoritative only when produced by the trusted `run_a2` path using the selected
SQLite store; parsing arbitrary JSON is not a revalidation against inventory.

## Reproducing offline verification

Use the existing Python environment from `code_workspace`, or install the
unchanged `requirements.txt` into a new local environment. No new dependency
was added. Keep the FDA starter ZIP at
`../project_reference/RecallReady_Agent1_FDA_18_Starter.zip`.

From `a2_isolated_workspace`, the existing environment can run focused tests:

```bash
../code_workspace/.venv/bin/python -B -m pytest \
  tests/test_a2_isolated_integration.py \
  tests/test_inventory_match.py tests/test_coordinator.py -q -p no:cacheprovider
```

The complete permitted regression selection is:

```bash
../code_workspace/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --ignore=tests/test_inventory_loader.py \
  --ignore=tests/test_inventory_store.py \
  --ignore=tests/test_a2_agent.py \
  --ignore=tests/test_a2_review_fixes.py
```

On 22 November 2026 this selection passed **969 tests in 7.33 seconds**:
912 original tests, 50 new isolated integration tests, and 7 existing pure
matching tests. No selected test was skipped or weakened.

The 50 new tests generate small JSON inventories in temporary directories,
build real SQLite databases through the actual loader, open them read-only,
and execute the matcher and compiled graph. Coverage includes exact, partial,
no-match and mixed findings; closed/unavailable stores; snapshot mismatch;
unexpected failures; all 18 A1 outputs and their review gates; context/citation
tampering; immutable database contents; leading zeros; absent candidate IDs;
loader overwrite refusal; and JSON state round trips. Synthetic failure
objects exercise exceptional paths. Network responses alone are simulated
for normal integration runs.

## Limitations and next gate

The four excluded modules retain 21 original tests that depend on the frozen
48-scenario inventory file. They are preserved unchanged but were not executed.
This is a permitted regression selection, not a full dataset-backed suite.
The frozen inventory, held-out labels, cloud services and paid interpretation
were not accessed for this integration. Existing tests and source material
remain available in the separate review checkout and original commit history.

The imported product equivalence table and batch-to-lot comparison policy
remain teammate-supplied matching rules; this work does not establish new human
approval or independent accuracy for those rules. Date relationships still
require human review, and inventory has no general expiry-date comparison.
The live FDA and model resources were not revalidated on this branch.

Next, the A2 owner should review the matching policy and shared contract.
Dataset-backed tests need an explicitly scoped development inventory fixture
that excludes held-out scenarios. Publication or replacement of the shared
branch should follow that review. A3/A4, critic correction, persisted case
resumption and final human decision handling remain later stages.
