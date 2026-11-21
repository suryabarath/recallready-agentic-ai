# RecallReady Agent 3 – integration notes

## Snapshot basis

This branch is based on the uploaded `origin/feature/a1-coordinator` snapshot, with Agent 2's implementation and tests copied from `origin/baseline/agent2`. The archive is not the live remote. No remote branches or pull requests were modified.

## New files

- `a3_agent.py`: typed, deterministic response planner; no inventory mutations or LLM-based disposition.
- `tests/test_a3_agent.py`: exact, partial, no-match, unresolved, and duplicate-finding cases.
- Agent 2's `a2_agent.py`, `inventory_store.py`, `inventory_match.py`, `inventory_loader.py` and tests are included so this checkout can import the actual A2 contract.

## Modified files

- `case_state.py`: optional A2/A3 envelopes and event/status validation.
- `coordinator.py`: optional `inventory_store` dependency and A1 -> A2 -> A3 -> human-review routing.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m pytest tests/test_a3_agent.py tests/test_a2_agent.py tests/test_coordinator.py -q
```

Existing A1-only behavior remains when `inventory_store=None`. To enable A2/A3, pass a configured `InventoryStore` to `A1Coordinator(..., inventory_store=inventory_store)`. See `inventory_store.py` and Agent 2's documentation for how to prepare the synthetic inventory SQLite database.

## Deliberate limitations

- All A3 results are recommendations for **human review**, not approved inventory actions.
- A4 Safety Critic is not included in the uploaded branch snapshot; the coordinator does not claim to invoke A4.
- No LLM calls are made in A3. This deterministic baseline can be reviewed and extended with a bounded structured-output LLM later without weakening evidence checks.
- A2 may return `partial` findings even alongside exact findings; A3 preserves each finding's status and evidence.
- `RECORD_NO_DEMONSTRATED_MATCH` is case-level and carries no invented item or evidence IDs.
- Do not merge before running the full tests in an environment with all requirements installed and reviewing integration against the latest remote branches.
