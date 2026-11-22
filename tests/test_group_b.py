"""Group B expansion: exact source, contract, and offline adapter coverage."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
from openai import OpenAI
import pytest

from citations import CitationError, validate_citation, validate_literal_identifier
from interpreter import Budget, interpret, main
from source import (
    DEFAULT_ARCHIVE, DEVELOPMENT_RECORDS, Evidence, FIELDS, GROUP_B, Source,
    SourceError,
)
from validation import ContractError, validate_result


SNAPSHOT = "FDA-FOOD-2026-10-23-USER-SNAPSHOT"
EVENTS = dict(zip(GROUP_B, ("92067", "92215", "92421", "93135", "91355", "99538")))
PREFIX = "RecallReady_Agent1_FDA_18_Starter/"
IDENTIFIERS = {
    "F-0818-2023": (("upc", "8904067712635", "code_info"),
                     ("lot", "US3-12", "code_info")),
    "F-0882-2023": (("batch", "2-401", "code_info"),),
    "F-1025-2023": (("batch", "101097", "code_info"),),
    "F-0011-2024": (("lot", "23194", "code_info"),
                     ("expiry_date", "13/JAN/2025", "code_info"),
                     ("upc", "858788004495", "code_info")),
    "F-0332-2023": (("upc", "855099007764", "product_description"),
                     ("lot", "022422SRB", "code_info"),
                     ("expiry_date", "2/24/2024", "code_info")),
    "H-1273-2026": (("upc", "194346207961", "product_description"),
                     ("lot", "LB028ACP04", "code_info"),
                     ("expiry_date", "January 28, 2027", "code_info")),
}


@pytest.fixture(scope="module")
def source():
    return Source()


@pytest.fixture(scope="module")
def raw():
    with ZipFile(DEFAULT_ARCHIVE) as archive:
        records = json.loads(archive.read(PREFIX + "01_FDA_Original_Source_18.json"))["results"]
        passages = [
            json.loads(line)
            for line in archive.read(PREFIX + "03_Agent1_Evidence_Passages_72.jsonl").splitlines()
        ]
    return (
        {r["recall_number"]: r for r in records if r["recall_number"] in GROUP_B},
        {p["evidence_id"]: p for p in passages if p["recall_number"] in GROUP_B},
    )


def context(recall):
    return dict(recall_number=recall, event_id=EVENTS[recall], snapshot_id=SNAPSHOT)


def eid(recall, field="code_info"):
    return f"EV-{recall}-{field.upper()}"


def expected_result(source, recall):
    """Assemble canonical envelope plus explicit reviewed Group B identifiers."""
    ctx = context(recall)
    record = source.lookup(**ctx)
    passages = {field: source.resolve(eid(recall, field), **ctx) for field in FIELDS}
    source_fields = {
        field: dict(
            original_text=passage.original_text,
            evidence_id=passage.evidence_id,
            point_id=passage.point_id,
        )
        for field, passage in passages.items()
    }
    source_fields.update(
        recalling_firm=dict(original_text=record["recalling_firm"], evidence_id=None, point_id=None),
        classification=dict(original_text=record["classification"], evidence_id=None, point_id=None),
    )
    identifiers = [
        dict(
            kind=kind,
            value=value,
            scope_note=record[field],
            evidence_ids=[eid(recall, field)],
        )
        for kind, value, field in IDENTIFIERS[recall]
    ]
    return dict(
        contract_version="0.1-proposed",
        snapshot_id=SNAPSHOT,
        event_id=record["event_id"],
        facts=dict(
            recall_number=recall,
            product_name=record["product_description"],
            recalling_firm=record["recalling_firm"],
            recall_reason=record["reason_for_recall"],
            classification=record["classification"],
            identifiers=identifiers,
            uncertainties=[],
            evidence_ids=[eid(recall, field) for field in FIELDS],
        ),
        source_fields=source_fields,
    )


@pytest.mark.parametrize("recall", GROUP_B)
def test_six_group_b_exact_lookups(source, raw, recall):
    actual = source.lookup(recall, snapshot_id=SNAPSHOT)
    assert actual == raw[0][recall]
    assert actual["event_id"] == EVENTS[recall]
    actual["code_info"] = "invented"
    assert source.lookup(**context(recall)) == raw[0][recall]


@pytest.mark.parametrize("recall", GROUP_B)
@pytest.mark.parametrize("field", FIELDS)
def test_all_24_group_b_passages(source, raw, recall, field):
    passage = raw[1][eid(recall, field)]
    citation = Evidence(**{key: passage[key] for key in Evidence.__dataclass_fields__})
    assert validate_citation(source, citation, **context(recall)).original_text == raw[0][recall][field]


def test_runtime_scope_is_exactly_selected_development_records(source):
    assert len(DEVELOPMENT_RECORDS) == 18
    assert len(set(DEVELOPMENT_RECORDS)) == 18
    for recall in DEVELOPMENT_RECORDS:
        assert source.lookup(recall, snapshot_id=SNAPSHOT)["recall_number"] == recall
    with pytest.raises(SourceError, match="out-of-scope"):
        source.lookup("H-1388-2027", snapshot_id=SNAPSHOT)


@pytest.mark.parametrize(
    "recall,kind,value,field",
    [
        (recall, kind, value, field)
        for recall, identifiers in IDENTIFIERS.items()
        for kind, value, field in identifiers
    ],
)
def test_group_b_exact_literals_and_kinds(source, recall, kind, value, field):
    evidence = validate_literal_identifier(
        source, value, [eid(recall, field)], **context(recall)
    )
    assert value in evidence[0].original_text
    result = validate_result(expected_result(source, recall), source, **context(recall))
    assert any(i.kind == kind and i.value == value for i in result.facts.identifiers)


@pytest.mark.parametrize("recall", GROUP_B)
def test_six_group_b_contract_examples(source, recall):
    expected = expected_result(source, recall)
    assert validate_result(expected, source, **context(recall)).model_dump() == expected


@pytest.mark.parametrize("recall", GROUP_B)
def test_group_b_cannot_omit_explicit_lot_or_batch(source, recall):
    payload = expected_result(source, recall)
    payload["facts"]["identifiers"] = [
        item for item in payload["facts"]["identifiers"]
        if item["kind"] not in ("lot", "batch")
    ]
    payload["facts"]["uncertainties"] = ["Model did not identify a lot or batch."]
    with pytest.raises(ContractError, match="missing from identifiers"):
        validate_result(payload, source, **context(recall))


@pytest.mark.parametrize("value", ["22422SRB", "022422srb", "022422SR", "022422SRBX"])
def test_group_b_leading_zero_and_literal_boundaries(source, value):
    with pytest.raises(CitationError):
        validate_literal_identifier(
            source, value, [eid("F-0332-2023")], **context("F-0332-2023")
        )


def test_group_b_rejects_invented_cross_context_and_altered_source(source):
    recall = GROUP_B[0]
    citation = source.resolve(eid(recall), **context(recall))
    with pytest.raises(CitationError):
        validate_citation(source, replace(citation, evidence_id="EV-INVENTED-CODE_INFO"), **context(recall))
    with pytest.raises(CitationError):
        validate_citation(source, replace(citation, original_text="altered"), **context(recall))
    with pytest.raises(SourceError, match="Cross-recall"):
        source.resolve(eid(GROUP_B[1]), **context(recall))
    with pytest.raises(SourceError, match="mismatch"):
        source.resolve(eid(recall), **(context(recall) | {"event_id": EVENTS[GROUP_B[1]]}))
    with pytest.raises(SourceError, match="mismatch"):
        source.resolve(eid(recall), **(context(recall) | {"snapshot_id": "OTHER"}))


@pytest.mark.parametrize("alter", ["identifier", "reason", "passage", "recall"])
def test_group_b_contract_rejects_unsupported_or_mismatched_claims(source, alter):
    recall = GROUP_B[0]
    payload = deepcopy(expected_result(source, recall))
    if alter == "identifier":
        payload["facts"]["identifiers"][1]["value"] = "US3-13"
    elif alter == "reason":
        payload["facts"]["recall_reason"] = "invented reason"
    elif alter == "passage":
        payload["source_fields"]["code_info"]["original_text"] = "altered source"
    else:
        payload["facts"]["recall_number"] = GROUP_B[1]
    with pytest.raises(ContractError):
        validate_result(payload, source, **context(recall))


def client_for(output, seen):
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=dict(
            id="resp_group_b_test", object="response", created_at=1,
            model="gpt-6-luna", status="completed",
            output=[dict(
                type="message", id="msg_group_b_test", role="assistant", status="completed",
                content=[dict(type="output_text", text=json.dumps(output), annotations=[])],
            )],
            usage=dict(
                input_tokens=4000, output_tokens=2000, total_tokens=6000,
                input_tokens_details=dict(cached_tokens=0),
                output_tokens_details=dict(reasoning_tokens=1500),
            ),
        ))
    return OpenAI(
        api_key="offline-test-key", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )


@pytest.mark.parametrize("recall", GROUP_B)
def test_six_group_b_offline_sdk_flows(source, tmp_path, recall):
    expected = expected_result(source, recall)
    proposal = dict(
        identifiers=[
            {key: item[key] for key in ("kind", "value", "evidence_ids")}
            for item in expected["facts"]["identifiers"]
        ],
        uncertainties=expected["facts"]["uncertainties"],
    )
    seen = []
    with client_for(proposal, seen) as client:
        actual = interpret(
            source, client, Budget(tmp_path / f"{recall}.sqlite"),
            recall_number=recall, snapshot_id=SNAPSHOT,
        )
    assert actual.model_dump() == expected
    assert len(seen) == 1
    assert len(json.loads(seen[0]["input"])) == 4


def test_cli_accepts_group_b_before_paid_precondition():
    with pytest.raises(SystemExit) as exc:
        main(["--recall", GROUP_B[0]])
    assert exc.value.code == 2


def test_group_b_source_phrases_are_preserved(source):
    assert source.lookup(**context("F-0011-2024"))["code_info"] == (
        "Lot number 23194, expiration date 13/JAN/2025, UPC 858788004495"
    )
    assert source.lookup(**context("F-0332-2023"))["code_info"] == (
        "Lot # 022422SRB, Expiration date: 2/24/2024"
    )
    assert source.lookup(**context("H-1273-2026"))["code_info"] == (
        "Lot: LB028ACP04 exp. date: January 28, 2027"
    )
