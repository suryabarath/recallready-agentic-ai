"""Bounded critic through real OpenAI SDK with offline HTTP responses."""

import json

import httpx
import pytest

from a1_trace import active_run
from a4_agent import A4RunEnvelope, run_a4
from interpreter import Budget
from test_a1_service import store
from test_a4_checks import upstream
from test_interpreter import client_for


def critic(upstream, **kwargs):
    source, inventory, state = upstream
    return run_a4(source, inventory, state.a1, state.a2, state.a3,
        case_id=state.case_id, run_id=state.run_id, recall_number=state.recall_number,
        snapshot_id=state.snapshot_id, event_id=state.a2.event_id, **kwargs)


def proposal(upstream, **updates):
    state = upstream[2]
    result = dict(passed=False, findings=[dict(severity="blocking", category="unsupported_claim",
        target_agent="a3", code="check_rationale", message="Review rationale against source.",
        evidence_ids=[state.a1.result.facts.evidence_ids[0]], item_ids=[state.a2.findings[0].item_id],
        fixable_by_revision=True)], suggested_revision_target="a3", revision_instructions="Review the rationale.")
    return result | updates


def test_deterministic_default_makes_no_model_request(upstream):
    result = critic(upstream)
    assert result.verdict == "human_review" and result.review_boundary_verified
    assert not result.trace.llm_invoked and result.trace.calls == []
    assert A4RunEnvelope.model_validate_json(result.model_dump_json()) == result


def test_passing_semantic_critic_does_not_remove_human_review(upstream, tmp_path):
    seen = []
    passed = dict(passed=True, findings=[], suggested_revision_target=None, revision_instructions=None)
    budget = Budget(tmp_path / "critic.sqlite")
    with client_for([(json.dumps(passed), "completed")], seen) as client:
        result = critic(upstream, client=client, budget=budget, enable_llm_critic=True)
    assert result.verdict == "human_review" and result.requires_human_review
    assert len(seen) == result.trace.model_attempts == len(budget.summary()) == 1
    assert seen[0]["store"] is False and "tools" not in seen[0]
    assert "synthetic_generation_note" not in seen[0]["input"]
    assert active_run.get() is None


@pytest.mark.parametrize("failure", ["bad_evidence", "bad_item", "duplicate", "empty_refs", "contradiction", "empty_blocking"])
def test_semantic_failure_has_no_repair_or_citation_filtering(upstream, tmp_path, failure):
    data = proposal(upstream)
    f = data["findings"][0]
    if failure == "bad_evidence": f["evidence_ids"].append("EV-INVENTED")
    elif failure == "bad_item": f["item_ids"].append("INV-INVENTED")
    elif failure == "duplicate": f["evidence_ids"] *= 2
    elif failure == "empty_refs": f.update(evidence_ids=[], item_ids=[])
    elif failure == "contradiction": data["passed"] = True
    else: data["findings"] = []
    seen = []
    with client_for([(json.dumps(data), "completed")], seen) as client:
        result = critic(upstream, client=client, budget=Budget(tmp_path / "critic.sqlite"), enable_llm_critic=True)
    assert result.verdict == "unresolved" and result.error.code == "invalid_output"
    assert len(seen) == result.trace.model_attempts == 1
    assert result.trace.repair_count == 0 and active_run.get() is None


def test_one_structural_repair_accounted(upstream, tmp_path):
    seen = []
    with client_for([("{}", "completed"), (json.dumps(proposal(upstream)), "completed")], seen) as client:
        result = critic(upstream, client=client, budget=Budget(tmp_path / "critic.sqlite"), enable_llm_critic=True)
    assert result.verdict == "revise" and result.trace.repair_count == 1
    assert len(seen) == len(result.trace.calls) == 2


@pytest.mark.parametrize("round,expected", [(0, "revise"), (1, "human_review")])
def test_revision_cap(upstream, tmp_path, round, expected):
    seen = []
    with client_for([(json.dumps(proposal(upstream)), "completed")], seen) as client:
        result = critic(upstream, client=client, budget=Budget(tmp_path / "critic.sqlite"),
                        enable_llm_critic=True, revision_round=round)
    assert result.verdict == expected
    assert result.requires_human_review


@pytest.mark.parametrize("response,code", [(httpx.ReadTimeout("private diagnostic"), "provider_failure"),
    (("", "incomplete"), "incomplete_response")])
def test_provider_failure_retains_accounting(upstream, tmp_path, response, code):
    seen = []
    budget = Budget(tmp_path / "critic.sqlite")
    with client_for([response], seen) as client:
        result = critic(upstream, client=client, budget=budget, enable_llm_critic=True)
    assert result.verdict == "unresolved" and result.error.code == code
    assert len(seen) == len(result.trace.calls) == 1
    assert "private diagnostic" not in result.model_dump_json()
    if code == "provider_failure":
        assert result.trace.estimated_cost_usd is None
        assert budget.summary()[0]["state"] == "reserved"


def test_deterministic_block_short_circuits_paid_critic(upstream, tmp_path):
    upstream[2].a1.result.source_fields.code_info.original_text = "altered source"
    seen = []
    with client_for([], seen) as client:
        result = critic(upstream, client=client, budget=Budget(tmp_path / "critic.sqlite"), enable_llm_critic=True)
    assert result.verdict == "human_review" and seen == []
    assert any(f.target_agent == "a1" for f in result.findings)


@pytest.mark.parametrize("mode", ["missing_usage", "settlement", "budget", "two_bad_shapes", "refusal"])
def test_accounting_and_response_failure_modes(upstream, tmp_path, monkeypatch, mode):
    from types import SimpleNamespace
    from interpreter import InterpretationError
    seen = []
    budget = Budget(tmp_path / "critic.sqlite", limit_microdollars=1 if mode == "budget" else 1_000_000)
    if mode == "settlement":
        def fail(*args):
            raise InterpretationError("private diagnostic")
        monkeypatch.setattr(budget, "settle", fail)
    outputs = [("{}", "completed"), ("{}", "completed")] if mode == "two_bad_shapes" else [(json.dumps(proposal(upstream)), "completed")]
    with client_for(outputs, seen) as client:
        if mode in ("missing_usage", "refusal"):
            original = client.responses.create
            def create(**kwargs):
                result = original(**kwargs)
                if mode == "missing_usage":
                    result.usage = None
                else:
                    result.output = [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]
                return result
            monkeypatch.setattr(client.responses, "create", create)
        result = critic(upstream, client=client, budget=budget, enable_llm_critic=True)
    assert result.verdict == "unresolved"
    expected = {"missing_usage": "usage_missing", "settlement": "usage_settlement_failed",
                "budget": "budget_exhausted", "two_bad_shapes": "invalid_output", "refusal": "model_refusal"}
    assert result.error.code == expected[mode]
    assert len(seen) == (0 if mode == "budget" else 2 if mode == "two_bad_shapes" else 1)
    if mode in ("missing_usage", "settlement"):
        assert result.trace.estimated_cost_usd is None
        assert budget.summary()[0]["state"] == "reserved"
    assert active_run.get() is None
