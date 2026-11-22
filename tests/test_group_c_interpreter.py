"""Real SDK with fake HTTP transport; no network or paid model calls."""

from copy import deepcopy
import json
import stat

import httpx
import pytest

from group_c_interpreter import interpret_group_c
from interpreter import Budget, InterpretationError
from source import GROUP_C, Source
from test_group_c_contract import example
from test_interpreter import client_for


def proposal(source, recall):
    envelope, _ = example(source, recall)
    identifiers = [{key: item[key] for key in ("kind", "value", "evidence_ids")}
                   for item in envelope["base"]["facts"]["identifiers"]]
    return dict(identifiers=identifiers, uncertainties=envelope["base"]["facts"]["uncertainties"],
                relations=[{key: relation[key] for key in ("kind", "evidence_id", "source_span", "parts")}
                           for relation in envelope["relations"]])


@pytest.mark.parametrize("recall", GROUP_C)
def test_six_group_c_sdk_flows(tmp_path, recall):
    source = Source()
    seen = []
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([(json.dumps(proposal(source, recall)), "completed")], seen) as client:
        result = interpret_group_c(source, client, budget, recall_number=recall,
                                   snapshot_id=source.snapshot_id)
    assert result.base.facts.recall_number == recall
    assert [r.source_span for r in result.relations] == [
        r["source_span"] for r in proposal(source, recall)["relations"]
    ]
    assert seen[0]["store"] is False
    assert seen[0]["reasoning"] == {"effort": "low"}
    assert "Always include at least one uncertainty" in seen[0]["instructions"]
    assert len(json.loads(seen[0]["input"])) == 4
    assert "tools" not in seen[0]
    assert len(budget.summary()) == 1


@pytest.mark.parametrize("alter", ["omitted_pair", "wrong_date", "cross_recall", "unknown_code"])
def test_invalid_semantics_stop_after_one_paid_response(tmp_path, alter):
    source = Source()
    recall = "F-1420-2012" if alter == "unknown_code" else "H-1388-2026"
    output = deepcopy(proposal(source, recall))
    if alter == "omitted_pair":
        output["relations"].pop()
    elif alter == "wrong_date":
        output["relations"][0]["parts"][1]["value"] = "08/18/2026"
    elif alter == "cross_recall":
        output["relations"][0]["evidence_id"] = "EV-H-1361-2026-CODE_INFO"
    else:
        output["identifiers"] = [dict(kind="other", value="Unknown",
                                      evidence_ids=["EV-F-1420-2012-CODE_INFO"])]
    seen = []
    diagnostic = tmp_path / "rejected.json"
    with client_for([(json.dumps(output), "completed")], seen) as client:
        with pytest.raises(InterpretationError):
            interpret_group_c(source, client, Budget(tmp_path / "usage.sqlite"),
                              recall_number=recall, snapshot_id=source.snapshot_id,
                              diagnostic_path=diagnostic)
    assert len(seen) == 1
    saved = json.loads(diagnostic.read_text())
    assert saved["recall_number"] == recall
    assert saved["proposal"] == output
    assert "reason" in saved and "response_id" in saved
    assert "offline-test-key" not in diagnostic.read_text()
    assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600


def test_structural_repair_is_bounded_and_accounted(tmp_path):
    source = Source()
    seen = []
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([("{}", "completed"),
                     (json.dumps(proposal(source, GROUP_C[0])), "completed")], seen) as client:
        interpret_group_c(source, client, budget, recall_number=GROUP_C[0],
                          snapshot_id=source.snapshot_id)
    assert len(seen) == len(budget.summary()) == 2


def test_transport_failure_retains_reservation(tmp_path):
    source = Source()
    seen = []
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([httpx.ReadTimeout("offline timeout")], seen) as client:
        with pytest.raises(InterpretationError, match="reservation retained"):
            interpret_group_c(source, client, budget, recall_number=GROUP_C[0],
                              snapshot_id=source.snapshot_id)
    assert len(seen) == 1
    assert budget.summary()[0]["state"] == "reserved"
