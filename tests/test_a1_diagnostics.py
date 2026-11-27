"""Exercise real A1 validators with offline SDK responses and private diagnostics."""

from copy import deepcopy
import json

import pytest

from a1_diagnostics import capture_validation_failures
from interpreter import Budget, InterpretationError, interpret
from source import GROUP_A, Source
from test_interpreter import client_for, proposal


def execute(tmp_path, payload, seen):
    source = Source()
    budget = Budget(tmp_path / "usage.sqlite")
    with client_for([(json.dumps(payload), "completed")], seen) as client:
        return interpret(source, client, budget, recall_number=GROUP_A[2],
                         snapshot_id=source.snapshot_id)


def test_complete_ambiguous_phrase_validates_without_override(tmp_path):
    seen = []
    with capture_validation_failures() as failures:
        result = execute(tmp_path, proposal(2), seen)
    assert [(i.kind, i.value) for i in result.facts.identifiers] == [
        ("other", "06-04-24 08/04/2024")]
    assert result.facts.uncertainties
    assert result.source_fields.code_info.original_text == "LOT # 06-04-24 08/04/2024"
    assert failures == [] and len(seen) == 1


@pytest.mark.parametrize("alter,rule", [
    ("confirmed_lot", "ambiguous_lot_requires_review"),
    ("split_span", "ambiguous_span_incomplete"),
    ("expiry", "identifier_label_unsupported"),
    ("no_uncertainty", "uncertainty_required"),
    ("invented_citation", "identifier_citation_invalid"),
    ("missing_citation", "identifier_citation_missing"),
    ("altered_literal", "source_contract_failed"),
])
def test_rejected_proposal_records_reason_without_retry(tmp_path, alter, rule):
    payload = deepcopy(proposal(2))
    identifier = payload["identifiers"][0]
    if alter == "confirmed_lot":
        identifier["kind"] = "lot"
    elif alter == "split_span":
        identifier["value"] = "06-04-24"
    elif alter == "expiry":
        identifier.update(kind="expiry_date", value="08/04/2024")
    elif alter == "no_uncertainty":
        payload["uncertainties"] = []
    elif alter == "invented_citation":
        identifier["evidence_ids"] = ["EV-INVENTED"]
    elif alter == "missing_citation":
        identifier["evidence_ids"] = []
    else:
        identifier["value"] = "6-04-24 08/04/2024"
    seen = []
    with capture_validation_failures() as failures:
        with pytest.raises(InterpretationError) as error:
            execute(tmp_path, payload, seen)
    assert error.value.code == "citation_source_failed"
    assert error.value.stage == "validation"
    assert len(seen) == len(failures) == 1
    record = failures[0]
    assert record["validation_rule"] == rule
    assert record["rejected_proposal"] == payload
    assert record["context"]["recall_number"] == GROUP_A[2]
    assert record["context"]["event_id"] == "94806"
    assert record["response_id"] == "resp_test" and record["ledger_call_id"] == 1
    assert record["trusted"] is False
    assert "offline-test-key" not in json.dumps(record)
    ledger = Budget(tmp_path / "usage.sqlite").summary()
    assert len(ledger) == 1 and ledger[0]["response_id"] == record["response_id"]


def test_capture_is_scoped_and_does_not_change_default_failure(tmp_path):
    payload = proposal(2)
    payload["identifiers"][0]["kind"] = "lot"
    with capture_validation_failures() as outer:
        with capture_validation_failures() as inner:
            with pytest.raises(InterpretationError):
                execute(tmp_path, payload, [])
        assert len(inner) == 1 and outer == []
        with pytest.raises(InterpretationError):
            execute(tmp_path, payload, [])
    assert len(outer) == 1
    with pytest.raises(InterpretationError):
        execute(tmp_path, payload, [])
    assert len(outer) == 1
    with capture_validation_failures() as fresh:
        assert fresh == []
