# Agent 3 — standalone feature-branch package

This contains **only new Agent 3 files** for RecallReady. It does not change
Agent 1, Agent 2, `coordinator.py` or `case_state.py`.

Start with [`docs/A3_STANDALONE_GUIDE.md`](docs/A3_STANDALONE_GUIDE.md).

Run the isolated tests:

```bash
python -m pip install -r requirements-agent3.txt
python -m pytest tests/test_a3_agent.py -v
```

The planner is a deterministic, evidence-preserving baseline, not an LLM agent.
It works from synthetic validated A2-shaped input without importing A1/A2
or requiring the team's external datasets.
