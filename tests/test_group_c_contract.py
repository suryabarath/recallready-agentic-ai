"""Source-bound relationship contract examples, not independent gold labels."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from group_c_contract import ContractError, validate_group_c_result
from interpreter import InterpretationError, interpret, main
from source import FIELDS, GROUP_C, Source
from validation import _PRODUCT_ITEM, _PRODUCT_UPC


EXAMPLES = {
    "H-1388-2026": ("lot_date", "LOT 00000ZRAA1  EXP 08/15/2026",
                    (("lot", "00000ZRAA1"), ("date", "08/15/2026"))),
    "H-1361-2026": ("state_code_date", "Illinois: TFIC207, 8/7/2026",
                    (("state", "Illinois"), ("code", "TFIC207"), ("date", "8/7/2026"))),
    "H-1396-2026": ("code_date", "L6080C SEP 20 2027",
                    (("code", "L6080C"), ("date", "SEP 20 2027"))),
    "F-0536-2021": ("date_range", "04/20/2021 thru Use By:  05/04/2021",
                    (("range_start", "04/20/2021"), ("range_end", "05/04/2021"))),
    "F-2413-2017": ("lot_date", "3516 / 1/3/2018",
                    (("lot", "3516"), ("date", "1/3/2018"))),
}
ADDITIONAL_PAIRS = {
    "H-1361-2026": [
        ("Illinois", "TFIC209", "8/9/2026"),
        ("Illinois", "TFIC211", "8/11/2026"),
        ("Texas", "TFTX209", "8/9/2026"),
        ("Texas", "TFTX211", "8/11/2026"),
        ("Texas", "TFTX213U11", "8/13/2026"),
        ("Texas", "TFTX216", "8/16/2026"),
    ],
    "H-1396-2026": [("L6079C", "SEP 19 2027")],
    "F-2413-2017": [
        ("3525", "1/10/2 018"), ("3536", "1/16/2018"),
        ("3553", "1/26/2018"), ("3571", "2/6/2018"),
        ("3537", "1/16/2018"), ("3570", "2/6/2018"),
    ],
}


def example(source, recall):
    record = source.lookup(recall, snapshot_id=source.snapshot_id)
    context = dict(recall_number=recall, event_id=record["event_id"], snapshot_id=source.snapshot_id)
    fields = {}
    for field in FIELDS:
        evidence = source.resolve(f"EV-{recall}-{field.upper()}", **context)
        fields[field] = dict(original_text=evidence.original_text,
                             evidence_id=evidence.evidence_id, point_id=evidence.point_id)
    for field in ("recalling_firm", "classification"):
        fields[field] = dict(original_text=record.get(field), evidence_id=None, point_id=None)
    base = dict(contract_version="0.1-proposed", snapshot_id=source.snapshot_id,
                event_id=record["event_id"], source_fields=fields,
                facts=dict(recall_number=recall, product_name=record["product_description"],
                           recalling_firm=record["recalling_firm"],
                           recall_reason=record["reason_for_recall"],
                           classification=record["classification"], identifiers=[],
                           uncertainties=["Group C relationships require human review."],
                           evidence_ids=[fields[f]["evidence_id"] for f in FIELDS]))
    product = record["product_description"]
    for kind, pattern in (("upc", _PRODUCT_UPC), ("other", _PRODUCT_ITEM)):
        for match in pattern.finditer(product):
            base["facts"]["identifiers"].append(dict(
                kind=kind, value=match.group(1), scope_note=product,
                evidence_ids=[fields["product_description"]["evidence_id"]],
            ))
    relations = []
    if recall in EXAMPLES:
        kind, span, parts = EXAMPLES[recall]
        if recall == "H-1361-2026":
            span = "TFIC207, 8/7/2026"
        start = record["code_info"].index(span)
        relations.append(dict(kind=kind, evidence_id=fields["code_info"]["evidence_id"],
                              start=start, end=start + len(span), source_span=span,
                              parts=[dict(role=role, value=value) for role, value in parts]))
    if recall == "H-1388-2026":
        span = "LOT 00000ZUAD2  EXP 08/18/2026"
        start = record["code_info"].index(span)
        relations.append(dict(kind="lot_date", evidence_id=fields["code_info"]["evidence_id"],
                              start=start, end=start + len(span), source_span=span,
                              parts=[dict(role="lot", value="00000ZUAD2"),
                                     dict(role="date", value="08/18/2026")]))
    for values in ADDITIONAL_PAIRS.get(recall, []):
        if recall == "H-1361-2026":
            state, code, date = values
            span = code + ", " + date
            start = record["code_info"].index(span)
            end = start + len(span)
            kind = "state_code_date"
            parts = (("state", state), ("code", code), ("date", date))
        else:
            code, date = values
            span = (code + " " + date) if recall == "H-1396-2026" else (code + " / " + date)
            start = record["code_info"].index(span)
            end = start + len(span)
            kind = "code_date" if recall == "H-1396-2026" else "lot_date"
            parts = ((("code", code), ("date", date)) if recall == "H-1396-2026"
                     else (("lot", code), ("date", date)))
        relations.append(dict(kind=kind, evidence_id=fields["code_info"]["evidence_id"],
                              start=start, end=end, source_span=record["code_info"][start:end],
                              parts=[dict(role=role, value=value) for role, value in parts]))
    return dict(contract_version="0.2-group-c-provisional", base=base,
                relations=relations), context


@pytest.mark.parametrize("recall", GROUP_C)
def test_six_group_c_relation_envelopes(recall):
    source = Source()
    payload, ctx = example(source, recall)
    assert validate_group_c_result(payload, source, **ctx).model_dump() == payload


@pytest.mark.parametrize("change", ["span", "offset", "value", "evidence", "role", "context"])
def test_reject_forged_relation(change):
    source = Source()
    payload, ctx = example(source, "H-1388-2026")
    payload = deepcopy(payload)
    relation = payload["relations"][0]
    if change == "span":
        relation["source_span"] = "LOT 00000ZRAA1  EXP 08/18/2026"
    elif change == "offset":
        relation["start"] += 1
    elif change == "value":
        relation["parts"][0]["value"] = "00000ZRAA3"
    elif change == "evidence":
        relation["evidence_id"] = "EV-H-1361-2026-CODE_INFO"
    elif change == "role":
        relation["parts"][0]["role"] = "state"
    else:
        ctx["snapshot_id"] = "OTHER"
    with pytest.raises((ContractError, ValidationError)):
        validate_group_c_result(payload, source, **ctx)


def test_unknown_cannot_be_asserted_as_relationship():
    source = Source()
    payload, ctx = example(source, "F-1420-2012")
    payload["relations"] = [dict(kind="code_date", evidence_id="EV-F-1420-2012-CODE_INFO",
                                 start=0, end=7, source_span="Unknown",
                                 parts=[dict(role="code", value="Unknown"),
                                        dict(role="date", value="2026")])]
    with pytest.raises(ContractError):
        validate_group_c_result(payload, source, **ctx)


def test_second_lot_date_pair_cannot_be_omitted_or_swapped():
    source = Source()
    payload, ctx = example(source, "H-1388-2026")
    payload["relations"].pop()
    with pytest.raises(ContractError, match="pair is missing"):
        validate_group_c_result(payload, source, **ctx)
    payload, ctx = example(source, "H-1388-2026")
    payload["relations"][0]["parts"][1]["value"] = "08/18/2026"
    with pytest.raises(ContractError):
        validate_group_c_result(payload, source, **ctx)


@pytest.mark.parametrize("recall,expected_count", [
    ("H-1388-2026", 2), ("H-1361-2026", 7),
    ("H-1396-2026", 2), ("F-1420-2012", 0),
    ("F-0536-2021", 1), ("F-2413-2017", 7),
])
def test_all_explicit_challenge_pairs_are_required(recall, expected_count):
    source = Source()
    payload, ctx = example(source, recall)
    assert len(payload["relations"]) == expected_count
    if expected_count:
        payload["relations"].pop()
        with pytest.raises(ContractError):
            validate_group_c_result(payload, source, **ctx)


def test_wrong_state_or_split_year_rejected():
    source = Source()
    payload, ctx = example(source, "H-1361-2026")
    payload["relations"][3]["parts"][0]["value"] = "Illinois"
    with pytest.raises(ContractError):
        validate_group_c_result(payload, source, **ctx)


def test_state_codes_cannot_be_promoted_to_lots():
    source = Source()
    payload, ctx = example(source, "H-1361-2026")
    payload["base"]["facts"]["identifiers"] = [dict(
        kind="lot", value="TFIC207", scope_note=source.lookup(**ctx)["code_info"],
        evidence_ids=["EV-H-1361-2026-CODE_INFO"],
    )]
    with pytest.raises(ContractError, match="not explicitly labeled lots"):
        validate_group_c_result(payload, source, **ctx)


def test_second_unlabeled_code_date_cannot_be_called_best_by():
    source = Source()
    payload, ctx = example(source, "H-1396-2026")
    payload["base"]["facts"]["identifiers"] = [dict(
        kind="best_by_date", value="SEP 19 2027",
        scope_note=source.lookup(**ctx)["code_info"],
        evidence_ids=["EV-H-1396-2026-CODE_INFO"],
    )]
    with pytest.raises(ContractError, match="Best-by date lacks"):
        validate_group_c_result(payload, source, **ctx)


def test_extra_swapped_code_date_pair_rejected():
    source = Source()
    payload, ctx = example(source, "H-1396-2026")
    original = source.lookup(**ctx)["code_info"]
    payload["relations"].append(dict(
        kind="code_date", evidence_id="EV-H-1396-2026-CODE_INFO",
        start=0, end=len(original), source_span=original,
        parts=[dict(role="code", value="L6080C"),
               dict(role="date", value="SEP 19 2027")],
    ))
    with pytest.raises(ContractError, match="omit or alter"):
        validate_group_c_result(payload, source, **ctx)
    payload, ctx = example(source, "F-2413-2017")
    payload["relations"][1]["parts"][1]["value"] = "1/10/2018"
    with pytest.raises(ContractError):
        validate_group_c_result(payload, source, **ctx)


def test_explicit_f2413_lot_codes_cannot_be_recast_as_unlabeled_codes():
    source = Source()
    payload, ctx = example(source, "F-2413-2017")
    payload["relations"][0]["kind"] = "code_date"
    payload["relations"][0]["parts"][0]["role"] = "code"
    with pytest.raises(ContractError, match="omit or alter"):
        validate_group_c_result(payload, source, **ctx)


@pytest.mark.parametrize("kind,value", [("other", "81068"), ("upc", "7 95631 81068 4")])
def test_f0536_labeled_product_identifiers_cannot_be_omitted(kind, value):
    source = Source()
    payload, ctx = example(source, "F-0536-2021")
    payload["base"]["facts"]["identifiers"] = [
        item for item in payload["base"]["facts"]["identifiers"]
        if (item["kind"], item["value"]) != (kind, value)
    ]
    with pytest.raises(ContractError, match="Explicit product"):
        validate_group_c_result(payload, source, **ctx)


def test_group_c_cannot_enter_legacy_paid_interpreter():
    source = Source()
    class OfflineClient:
        max_retries = 0
    with pytest.raises(InterpretationError, match="relationship interpreter"):
        interpret(source, OfflineClient(), None, recall_number=GROUP_C[0],
                  snapshot_id=source.snapshot_id)
    with pytest.raises(SystemExit) as exc:
        main(["--recall", GROUP_C[0], "--allow-paid-call"])
    assert exc.value.code == 2
