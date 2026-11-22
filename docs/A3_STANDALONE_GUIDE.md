# RecallReady — Agent 3 standalone implementation and branch handoff

**Scope:** Agent 3 response planning ONLY. Prepared 22 November 2026.

## What has and has not been changed

This deliverable adds **only** these files:

```text
a3_agent.py
tests/test_a3_agent.py
tests/test_a3_a2_contract_optional.py
requirements-agent3.txt
docs/A3_STANDALONE_GUIDE.md
examples/a3_synthetic_a2_input.json
```

It does **not** edit `coordinator.py`, `case_state.py`, `a1_*`, `a2_agent.py`, inventory loaders, the team's `requirements.txt`, or any existing tracked file. Nothing is pushed to GitHub. It is safe to review and merge independently of unfinished coordinator work.

## Source and verification status

- **Attached user document:** `RecallReady_Agent3_Contributor_Handoff(1).docx`. Note: despite the request describing it as an Agent 2-to-Agent 3 handoff, its actual title is **Agent 3 Contributor Handoff**, created for the earlier combined project snapshot. Its API contract and safety constraints were used, but its previous instructions to change coordinator files were **intentionally not followed**.
- **Repository code reviewed:** the earlier user-uploaded repository snapshot and existing `baseline/agent2` code included in the previously supplied combined ZIP, particularly `A2RunEnvelope` and `InventoryFinding`. The current private GitHub repository returned 404 to the connected app at preparation time, so **current remote branch heads are not verified**.
- **Project Drive reviewed:** the 21 November 2026 `RecallReady_Technical_Architecture_Data_Flow_Agent_Communication_Explained_Simply.pdf` and `RecallReady_Lot_Date_Batch_Barcode_Problem_Explanation.txt` from the shared project folder. The architecture describes A3 as bounded, proposed review actions after A2, and a later A4 critic/human review gate.
- **Tests:** A3-only synthetic tests passed in the preparation environment. The optional real A2 import test is skipped if Agent 2 code/dependencies are absent. Full A1/A2/coordinator tests are not part of this deliverable.

## How Agent 3 works

**Entry point:** `plan_response(a2)` in `a3_agent.py`.

Input can be:

1. A real, validated `a2_agent.A2RunEnvelope` Pydantic instance, **when Agent 2 exists**; or
2. Its `model_dump(mode="python")` / JSON-decoded dict, used for standalone tests and future boundary integration.

Agent 3 never imports Agent 2 or inventory data modules at startup. Instead, it checks A2's relevant fields against its own **read-only projection** of the actual A2 contract. This is deliberate: A3 must not alter the A2 team's schema or depend on its local dataset fixtures.

It preserves `case_id`, `run_id`, `recall_number`, `snapshot_id`, `event_id`, `item_id` and A1 evidence references. It requires all findings to be from one inventory set and checks the context of each finding.

### Policy mapping

| Actual A2 condition | A3 proposed action | Notes |
|---|---|---|
| `match_status=exact` | `REVIEW_ITEM` | Review proposal only; does not mutate inventory |
| `match_status=partial`, `lot_match=unknown` | `VERIFY_LOT` | Lot must be investigated |
| `match_status=partial`, `lot_match=mismatched` | `VERIFY_LOT` | Explicitly **does not** regard it as an affected-lot match; asks human to recheck identifiers |
| `match_status=partial`, `lot_match=matched` | `REQUEST_MORE_INFORMATION` | Other product/scope attributes remain unresolved |
| `status=no_match`, no findings | `RECORD_NO_DEMONSTRATED_MATCH` | Case-level action with **no** item/evidence ID; not a safety clearance |
| `status=unresolved` | `A3RunEnvelope(status=unresolved)` | No actions; upstream failure never becomes no-match |

For `status=matched`, A2 can supply **both exact and partial findings**; each is mapped independently. `status=partial` may contain only partial findings. The input and output use Pydantic v2.

### Output contracts

```python
from a3_agent import A3RunEnvelope, SuggestedAction, plan_response, validate_plan_against_a2

# No Agent 2 import is necessary to develop/test the baseline.
a3: A3RunEnvelope = plan_response(a2_envelope_or_dict)
validate_plan_against_a2(a3, a2_envelope_or_dict)
```

- `A3RunEnvelope`: `case_id`, `run_id`, `recall_number`, `snapshot_id`, `event_id`, `status` (`planned|unresolved`), `suggested_actions`, `requires_human_review=True`, `error`.
- `SuggestedAction`: `item_id`, one of the four permitted `action_code` values, `reason`, `evidence_ids`, `requires_human_review=True`.
- Both review flags are **hard-enforced** (`Literal[True]`), not just defaulted to `True`.
- A3 forbids unknown output fields and duplicate evidence IDs. The `validate_plan_against_a2` guard rejects fabricated item IDs, mismatched citations, invalid action mapping, or modified deterministic wording.
- Invalid A2 context or contract raises `pydantic.ValidationError` (or `TypeError` for a non-envelope); only a **valid explicitly unresolved** A2 result produces an unresolved A3 envelope.
- Evidence IDs are forwarded *verbatim* from A2. A3 does **not** independently look them up in SQLite. The coordinator/A4 must enforce full evidence resolution later.

## Dependencies and tests

From the repository root:

```powershell
python -m pip install -r requirements-agent3.txt
python -m pytest tests/test_a3_agent.py -v
```

Run the optional integration contract test **when A2 code and its dependencies are present**:

```powershell
python -m pytest tests/test_a3_a2_contract_optional.py -rs -v
```

The first command does not need the original synthetic inventory JSON, FDA starter ZIP, Qdrant, SQLite, LangGraph or an API key. The optional test skips (rather than fails) when Agent 2 cannot be imported on this feature branch.

Try the minimal synthetic sample:

```powershell
python -c "import json; from a3_agent import plan_response; print(plan_response(json.load(open('examples/a3_synthetic_a2_input.json', encoding='utf-8'))).model_dump_json(indent=2))"
```

The example uses a historical recall identifier in the filename context but **all case, stock and evidence identifiers in the example are synthetic placeholders**; they have not been validated against the FDA data or SQLite.

## Create an independent Git feature branch

Starting from a **clean** local clone (save any uncommitted work on your experimental coordinator branch first):

```powershell
git status
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feature/agent3-standalone
```

Extract the **Agent3-only ZIP** into the repository root, preserving its directory structure. Confirm that it adds files only:

```powershell
git status --short
git diff --name-status
python -m pip install -r requirements-agent3.txt
python -m pytest tests/test_a3_agent.py -v
```

Alternatively, put the `.patch` in the repository root and run:

```powershell
git apply --check RecallReady_Agent3_only.patch
git apply RecallReady_Agent3_only.patch
```

Then commit **only the new Agent 3 files**:

```powershell
git add a3_agent.py requirements-agent3.txt tests/test_a3_agent.py tests/test_a3_a2_contract_optional.py docs/A3_STANDALONE_GUIDE.md examples/a3_synthetic_a2_input.json
git commit -m "Add standalone Agent 3 response planning with isolated tests"
git push -u origin feature/agent3-standalone
```

Open a **draft** PR if desired, and explicitly note that A3's upstream Agent 2 contract is cross-checked from a snapshot. Do not include prior integrated `coordinator.py` or `case_state.py` modifications. Later, the team can merge A2's completed contract and wire A3 through the coordinator as a separate integration PR.

## A4 and optional LLM work (not in this branch)

The architecture anticipates a shared LLM, a safety critic (A4) and human review. **This branch is a deterministic baseline, not an LLM-driven agent.** This ensures repeatable offline tests and a stable contract while the coordinator is unfinished. A later PR may add an optional LLM planner, but every model-produced action, citation and reason must first pass a documented validation policy and then A4/human review. Do not silently add LLM calls, stock mutations, public notices or safety-clearance claims to this baseline.

## Known limits / reviewer checklist

- This is based on the available local source snapshot, **not verified against the latest remote private branch**.
- Test results cover isolated synthetic A2-shaped inputs, **not real FDA/inventory end-to-end outcomes**.
- Cross-agent, exact SQLite citation validation, A4 critic, approval persistence and UI routing are explicitly outside scope.
- All suggested actions remain unexecuted and human-review-required.
- No A1/A2/coordinator files should appear in the diff of this feature branch.
