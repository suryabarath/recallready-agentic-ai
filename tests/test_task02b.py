"""Offline approved-contract checks; examples are development, not gold labels."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from models import A1Result
from source import DEFAULT_ARCHIVE, FIELDS, GROUP_A, Source, SourceError
from validation import ContractError, HumanLotApproval, validate_result


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "docs/task02b_group_a_review_examples.json").read_text())
PREFIX = "RecallReady_Agent1_FDA_18_Starter/"


@pytest.fixture(scope="module")
def source():
    return Source()


def ctx(example):
    return dict(recall_number=example["facts"]["recall_number"],
                event_id=example["event_id"], snapshot_id=example["snapshot_id"])


def change(example, path, value):
    target = example
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("index", range(6), ids=GROUP_A)
def test_six_examples_and_json_roundtrip(source, index):
    payload = deepcopy(EXAMPLES[index])
    result = validate_result(payload, source, **ctx(payload))
    assert result.model_dump() == payload
    assert A1Result.model_validate_json(result.model_dump_json()).model_dump() == payload
    assert validate_result(result, source, **ctx(payload)).model_dump() == payload


REQUIRED = (
    [(k,) for k in EXAMPLES[0]]
    + [("facts", k) for k in EXAMPLES[0]["facts"]]
    + [("source_fields", k) for k in EXAMPLES[0]["source_fields"]]
    + [("facts", "identifiers", 0, k) for k in EXAMPLES[0]["facts"]["identifiers"][0]]
    + [("source_fields", "code_info", k) for k in EXAMPLES[0]["source_fields"]["code_info"]]
)


@pytest.mark.parametrize("path", REQUIRED)
def test_all_fields_required(source, path):
    payload = deepcopy(EXAMPLES[0])
    target = payload
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValidationError):
        validate_result(payload, source, **ctx(EXAMPLES[0]))


@pytest.mark.parametrize("path", [(), ("facts",), ("source_fields",),
                                  ("source_fields", "code_info"), ("facts", "identifiers", 0)])
def test_no_extra_fields_at_any_level(source, path):
    payload = deepcopy(EXAMPLES[0])
    target = payload
    for key in path:
        target = target[key]
    target["inventory_action"] = "remove stock"
    with pytest.raises(ValidationError):
        validate_result(payload, source, **ctx(EXAMPLES[0]))


@pytest.mark.parametrize("path,value", [
    (("contract_version",), "0.2"),
    (("event_id",), 99686),
    (("snapshot_id",), " "),
    (("facts", "recall_number"), 11),
    (("facts", "product_name"), 123),
    (("facts", "uncertainties"), [""]),
    (("facts", "identifiers"), ()),
    (("facts", "identifiers", 0, "value"), 26078),
    (("facts", "identifiers", 0, "value"), " "),
    (("facts", "identifiers", 0, "kind"), "sell_by_date"),
    (("facts", "identifiers", 0, "scope_note"), 123),
    (("facts", "identifiers", 0, "evidence_ids"), []),
    (("source_fields", "code_info", "original_text"), 26078),
    (("source_fields", "code_info", "point_id"), "not-a-uuid"),
    (("source_fields", "code_info", "point_id"), None),
    (("source_fields", "code_info", "original_text"), None),
])
def test_strict_types_and_structure(source, path, value):
    payload = deepcopy(EXAMPLES[0])
    change(payload, path, value)
    with pytest.raises(ValidationError):
        validate_result(payload, source, **ctx(EXAMPLES[0]))


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("key,value", [
    ("original_text", "altered FDA text"),
    ("evidence_id", "EV-INVENTED-CODE_INFO"),
    ("point_id", "00000000-0000-0000-0000-000000000000"),
])
def test_all_24_passages_reject_altered_provenance(source, index, field, key, value):
    payload = deepcopy(EXAMPLES[index])
    payload["source_fields"][field][key] = value
    with pytest.raises(ContractError):
        validate_result(payload, source, **ctx(EXAMPLES[index]))


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("field", ["recalling_firm", "classification"])
@pytest.mark.parametrize("alter", ["fact", "source", "invented_passage"])
def test_all_12_metadata_fields_checked(source, index, field, alter):
    payload = deepcopy(EXAMPLES[index])
    if alter == "fact":
        payload["facts"][field] = "invented metadata"
    elif alter == "source":
        payload["source_fields"][field]["original_text"] = "invented metadata"
    else:
        payload["source_fields"][field].update(
            evidence_id="EV-INVENTED-METADATA",
            point_id="00000000-0000-0000-0000-000000000000",
        )
    with pytest.raises(ContractError):
        validate_result(payload, source, **ctx(EXAMPLES[index]))


@pytest.mark.parametrize("key,value", [
    ("event_id", "92944"), ("snapshot_id", "OTHER-SNAPSHOT"),
    ("recall_number", "F-1542-2023"),
])
def test_result_cannot_change_caller_selection(source, key, value):
    payload = deepcopy(EXAMPLES[0])
    if key == "recall_number":
        payload["facts"][key] = value
    else:
        payload[key] = value
    with pytest.raises(ContractError):
        validate_result(payload, source, **ctx(EXAMPLES[0]))


def test_fully_valid_other_recall_cannot_replace_selected_recall(source):
    with pytest.raises(ContractError):
        validate_result(EXAMPLES[1], source, **ctx(EXAMPLES[0]))


@pytest.mark.parametrize("updates", [
    {"event_id": "92944"}, {"event_id": None},
    {"snapshot_id": "OTHER-SNAPSHOT"}, {"recall_number": "F-0000-9999"},
])
def test_untrusted_selection_rejected_even_when_echoed_in_payload(source, updates):
    payload = deepcopy(EXAMPLES[0])
    selected = ctx(payload) | updates
    payload["facts"]["recall_number"] = selected["recall_number"]
    payload["event_id"] = selected["event_id"]
    payload["snapshot_id"] = selected["snapshot_id"]
    with pytest.raises((ContractError, ValidationError)):
        validate_result(payload, source, **selected)


@pytest.mark.parametrize("index,position,key,value", [
    (1, 0, "value", "60723"),
    (4, 0, "value", "4162026"),
    (5, 2, "value", "1744230012"),
    (0, 1, "value", "2026-09-15"),
    (0, 0, "value", "26078X"),
    (0, 0, "scope_note", "Lot applies everywhere"),
    (0, 0, "scope_note", None),
    (2, 0, "kind", "expiry_date"),
    (4, 0, "kind", "upc"),
    (5, 1, "kind", "use_by_date"),
    (5, 1, "kind", "expiry_date"),
    (3, 2, "kind", "lot"),
])
def test_literal_scope_and_kind_failures(source, index, position, key, value):
    payload = deepcopy(EXAMPLES[index])
    payload["facts"]["identifiers"][position][key] = value
    with pytest.raises(ContractError):
        validate_result(payload, source, **ctx(EXAMPLES[index]))


@pytest.mark.parametrize("index", [2, 3, 4, 5])
def test_other_requires_explicit_uncertainty(source, index):
    payload = deepcopy(EXAMPLES[index])
    payload["facts"]["uncertainties"] = []
    with pytest.raises(ContractError, match="uncertainty"):
        validate_result(payload, source, **ctx(payload))


@pytest.mark.parametrize("index,value", [
    (2, "06-04-24 08/04/2024"),
    (2, "06-04-24"),
    (4, "04162026 BC 6937218914734"),
    (4, "04162026"),
])
def test_ambiguous_code_cannot_be_confirmed_lot(source, index, value):
    payload = deepcopy(EXAMPLES[index])
    payload["facts"]["identifiers"][0]["kind"] = "lot"
    payload["facts"]["identifiers"][0]["value"] = value
    with pytest.raises(ContractError, match="Ambiguous combined code"):
        validate_result(payload, source, **ctx(payload))


def test_unclear_bc_suffix_cannot_be_upc(source):
    payload = deepcopy(EXAMPLES[4])
    payload["facts"]["identifiers"][0]["kind"] = "upc"
    payload["facts"]["identifiers"][0]["value"] = "6937218914734"
    with pytest.raises(ContractError, match="source-label support"):
        validate_result(payload, source, **ctx(payload))


def test_explicit_human_lot_approval_is_exactly_scoped(source):
    payload = deepcopy(EXAMPLES[4])
    payload["facts"]["identifiers"][0].update(
        kind="lot", value="04162026 BC 6937218914734"
    )
    context = ctx(payload)
    approval = HumanLotApproval(
        **context,
        evidence_id=payload["source_fields"]["code_info"]["evidence_id"],
        original_text=payload["source_fields"]["code_info"]["original_text"],
        value="04162026 BC 6937218914734", reviewer="Member 1",
    )
    assert validate_result(payload, source, approved_lots=(approval,), **context).facts.identifiers[0].kind == "lot"
    with pytest.raises(ContractError, match="Ambiguous combined code"):
        validate_result(payload, source, **context)
    for altered in (
        {"event_id": "OTHER"}, {"snapshot_id": "OTHER"},
        {"evidence_id": "EV-INVENTED"}, {"original_text": "altered"},
        {"value": "04162026"}, {"reviewer": " "},
    ):
        wrong = HumanLotApproval(**(approval.__dict__ | altered))
        with pytest.raises(ContractError, match="Ambiguous combined code"):
            validate_result(payload, source, approved_lots=(wrong,), **context)
    partial = deepcopy(payload)
    partial["facts"]["identifiers"][0]["value"] = "04162026"
    with pytest.raises(ContractError, match="Ambiguous combined code"):
        validate_result(partial, source, approved_lots=(approval,), **context)


@pytest.mark.parametrize("index,value", [
    (2, "06-04-24"), (2, "08/04/2024"),
    (4, "04162026"), (4, "6937218914734"),
])
def test_unresolved_other_keeps_entire_ambiguous_span(source, index, value):
    payload = deepcopy(EXAMPLES[index])
    payload["facts"]["identifiers"][0]["value"] = value
    with pytest.raises(ContractError, match="complete literal span"):
        validate_result(payload, source, **ctx(payload))


@pytest.mark.parametrize("code_info,value,should_pass", [
    ("Lot A1 08/01/2026", "A1", False),
    ("Lot A1 BC 123456", "A1", False),
    ("Lot A1 EXP 08/01/2026 LOT B2 EXP 09/01/2026", "A1", True),
    ("Lot 06-04-24", "06-04-24", True),
])
def test_lot_boundaries_generalize_beyond_development_examples(
    tmp_path, code_info, value, should_pass
):
    source, snapshot = synthetic_source(tmp_path, "code_info", code_info)
    payload = deepcopy(EXAMPLES[0])
    payload["snapshot_id"] = snapshot
    payload["source_fields"]["code_info"]["original_text"] = code_info
    payload["facts"]["identifiers"] = [dict(
        kind="lot", value=value, scope_note=code_info,
        evidence_ids=[payload["source_fields"]["code_info"]["evidence_id"]],
    )]
    payload["facts"]["identifiers"].append(dict(
        kind="upc", value="850041392103",
        scope_note=payload["source_fields"]["product_description"]["original_text"],
        evidence_ids=[payload["source_fields"]["product_description"]["evidence_id"]],
    ))
    if should_pass and "LOT B2" in code_info:
        payload["facts"]["identifiers"].append(dict(
            kind="lot", value="B2", scope_note=code_info,
            evidence_ids=[payload["source_fields"]["code_info"]["evidence_id"]],
        ))
    if should_pass:
        assert validate_result(payload, source, **ctx(payload)).facts.identifiers[0].value == value
    else:
        with pytest.raises(ContractError, match="Ambiguous combined code"):
            validate_result(payload, source, **ctx(payload))


@pytest.mark.parametrize("alter", ["missing", "extra", "duplicate", "unrelated", "cross_recall"])
def test_evidence_list_consistency(source, alter):
    payload = deepcopy(EXAMPLES[0])
    facts = payload["facts"]
    if alter == "missing":
        facts["evidence_ids"].remove(facts["identifiers"][0]["evidence_ids"][0])
    elif alter == "extra":
        facts["evidence_ids"].append("EV-INVENTED-CODE_INFO")
    elif alter == "duplicate":
        facts["evidence_ids"].append(facts["evidence_ids"][0])
    elif alter == "unrelated":
        facts["identifiers"][0]["evidence_ids"].append(facts["evidence_ids"][2])
    else:
        facts["identifiers"][0]["evidence_ids"] = EXAMPLES[1]["facts"]["identifiers"][0]["evidence_ids"]
    with pytest.raises((ContractError, ValidationError)):
        validate_result(payload, source, **ctx(payload))


def test_model_instances_do_not_bypass_nested_type_checks(source):
    model = A1Result.model_validate(EXAMPLES[0])
    model.facts.identifiers[0].value = 26078
    with pytest.raises(ValidationError):
        validate_result(model, source, **ctx(EXAMPLES[0]))


def test_matching_forged_metadata_still_fails_against_canonical_source(source):
    payload = deepcopy(EXAMPLES[0])
    payload["facts"]["classification"] = "Class IV"
    payload["source_fields"]["classification"]["original_text"] = "Class IV"
    with pytest.raises(ContractError, match="Source text mismatch"):
        validate_result(payload, source, **ctx(payload))


def test_starter_facts_fields_and_identifier_enum_preserved():
    with ZipFile(DEFAULT_ARCHIVE) as z:
        schema = json.loads(z.read(PREFIX + "07_Agent1_Output_Contract_PROPOSED.json"))
    exported = A1Result.model_json_schema()
    assert set(exported["$defs"]["Facts"]["properties"]) == set(schema["properties"])
    identifier = schema["properties"]["identifiers"]["items"]
    assert set(exported["$defs"]["Identifier"]["properties"]) == set(identifier["properties"])
    assert exported["$defs"]["Identifier"]["properties"]["kind"]["enum"] == identifier["properties"]["kind"]["enum"]


def synthetic_source(tmp_path, field, text):
    """Write a synthetic ZIP fixture, never extract or mutate the starter ZIP.

    Only four A1 source members are copied; no inventory/reference/label input.
    The fixture has its own explicit synthetic snapshot identity.
    """
    names = ["01_FDA_Original_Source_18.json", "03_Agent1_Evidence_Passages_72.jsonl",
             "05_Agent1_Record_Selection.csv", "08_Agent1_Manifest.json"]
    with ZipFile(DEFAULT_ARCHIVE) as z:
        members = {n: z.read(PREFIX + n) for n in names}
    original = json.loads(members[names[0]])
    manifest = json.loads(members[names[3]])
    passages = [json.loads(line) for line in members[names[1]].splitlines()]
    snapshot = "SYNTHETIC-TASK02B-TEST"
    original["meta"]["snapshot_id"] = manifest["snapshot_id"] = snapshot
    record = next(r for r in original["results"] if r["recall_number"] == GROUP_A[0])
    if text is None:
        record.pop(field)
    else:
        record[field] = text
    for p in passages:
        p["snapshot_id"] = snapshot
        if p["recall_number"] == GROUP_A[0] and p["field_name"] == field:
            p["original_text"] = text if text is not None else ""
    members[names[0]] = json.dumps(original).encode()
    members[names[3]] = json.dumps(manifest).encode()
    members[names[1]] = "\n".join(json.dumps(p) for p in passages).encode()
    archive = tmp_path / "synthetic_task02b.zip"
    with ZipFile(archive, "w") as z:
        for name, content in members.items():
            z.writestr(PREFIX + name, content)
        sums = "\n".join(f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in members.items())
        z.writestr(PREFIX + "SHA256SUMS.txt", sums)
    return Source(archive), snapshot


@pytest.mark.parametrize("text", ["Unknown", "", "No codes"])
def test_unknown_and_empty_code_preserved_without_invention(tmp_path, text):
    source, snapshot = synthetic_source(tmp_path, "code_info", text)
    payload = deepcopy(EXAMPLES[0])
    payload["snapshot_id"] = snapshot
    payload["source_fields"]["code_info"]["original_text"] = text
    payload["facts"]["identifiers"] = [dict(
        kind="upc", value="850041392103",
        scope_note=payload["source_fields"]["product_description"]["original_text"],
        evidence_ids=[payload["source_fields"]["product_description"]["evidence_id"]],
    )]
    payload["facts"]["uncertainties"] = ["No supported lot is provided by the code field."]
    assert validate_result(payload, source, **ctx(payload)).source_fields.code_info.original_text == text
    payload["facts"]["uncertainties"] = []
    with pytest.raises(ContractError):
        validate_result(payload, source, **ctx(payload))
    if text:
        payload["facts"]["uncertainties"] = ["Source code meaning is unresolved."]
        payload["facts"]["identifiers"] = [dict(
            kind="other", value=text, scope_note=text,
            evidence_ids=[payload["source_fields"]["code_info"]["evidence_id"]],
        )]
        with pytest.raises(ContractError, match="Unknown/empty"):
            validate_result(payload, source, **ctx(payload))


def test_labeled_product_upc_cannot_be_omitted(source):
    payload = deepcopy(EXAMPLES[0])
    payload["facts"]["identifiers"] = [
        item for item in payload["facts"]["identifiers"]
        if item["kind"] != "upc"
    ]
    with pytest.raises(ContractError, match="Explicit product upc"):
        validate_result(payload, source, **ctx(payload))


@pytest.mark.parametrize("field", ["recalling_firm", "classification"])
@pytest.mark.parametrize("text", [None, "", "Unknown"])
def test_missing_and_unknown_metadata(tmp_path, field, text):
    source, snapshot = synthetic_source(tmp_path, field, text)
    payload = deepcopy(EXAMPLES[0])
    payload["snapshot_id"] = snapshot
    payload["source_fields"][field]["original_text"] = text
    payload["facts"][field] = None
    payload["facts"]["uncertainties"] = [f"{field} is unavailable in the source."]
    assert validate_result(payload, source, **ctx(payload)).model_dump() == payload
    payload["facts"]["uncertainties"] = []
    with pytest.raises(ContractError, match="uncertainty"):
        validate_result(payload, source, **ctx(payload))


def test_missing_source_for_existing_passage_is_integrity_error(tmp_path):
    with pytest.raises(SourceError, match="Source/passage mismatch"):
        synthetic_source(tmp_path, "code_info", None)
