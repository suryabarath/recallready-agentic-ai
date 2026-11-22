"""Group C source and citation gates; no semantic reference labels or model calls."""

from dataclasses import replace
import json
from zipfile import ZipFile

import pytest

from citations import CitationError, validate_citation, validate_literal_identifier
from source import DEFAULT_ARCHIVE, Evidence, FIELDS, GROUP_C, Source, SourceError


EVENTS = dict(zip(GROUP_C, ("99841", "99611", "99853", "57449", "87836", "77557")))
PREFIX = "RecallReady_Agent1_FDA_18_Starter/"


def context(source, recall):
    return dict(recall_number=recall, event_id=EVENTS[recall], snapshot_id=source.snapshot_id)


def eid(recall, field="code_info"):
    return f"EV-{recall}-{field.upper()}"


@pytest.fixture(scope="module")
def source():
    return Source()


@pytest.fixture(scope="module")
def raw():
    with ZipFile(DEFAULT_ARCHIVE) as archive:
        records = json.loads(archive.read(PREFIX + "01_FDA_Original_Source_18.json"))["results"]
        passages = [json.loads(line) for line in archive.read(
            PREFIX + "03_Agent1_Evidence_Passages_72.jsonl").splitlines()]
    return ({r["recall_number"]: r for r in records if r["recall_number"] in GROUP_C},
            {p["evidence_id"]: p for p in passages if p["recall_number"] in GROUP_C})


@pytest.mark.parametrize("recall", GROUP_C)
def test_six_group_c_exact_lookups(source, raw, recall):
    record = source.lookup(recall, snapshot_id=source.snapshot_id)
    assert record == raw[0][recall]
    assert record["event_id"] == EVENTS[recall]
    record["code_info"] = "altered"
    assert source.lookup(**context(source, recall)) == raw[0][recall]


@pytest.mark.parametrize("recall", GROUP_C)
@pytest.mark.parametrize("field", FIELDS)
def test_all_24_group_c_passages(source, raw, recall, field):
    passage = raw[1][eid(recall, field)]
    citation = Evidence(**{key: passage[key] for key in Evidence.__dataclass_fields__})
    resolved = validate_citation(source, citation, **context(source, recall))
    assert vars(resolved) == {key: passage[key] for key in Evidence.__dataclass_fields__}
    assert resolved.original_text == raw[0][recall][field]


@pytest.mark.parametrize("recall", GROUP_C)
def test_group_c_rejects_cross_recall_event_snapshot_and_text(source, recall):
    ctx = context(source, recall)
    citation = source.resolve(eid(recall), **ctx)
    other = GROUP_C[(GROUP_C.index(recall) + 1) % len(GROUP_C)]
    with pytest.raises(SourceError):
        source.resolve(eid(other), **ctx)
    with pytest.raises(SourceError):
        source.resolve(eid(recall), **(ctx | {"event_id": EVENTS[other]}))
    with pytest.raises(SourceError):
        source.resolve(eid(recall), **(ctx | {"snapshot_id": "OTHER"}))
    for altered in (replace(citation, original_text="altered"),
                    replace(citation, evidence_id="EV-INVENTED-CODE_INFO")):
        with pytest.raises(CitationError):
            validate_citation(source, altered, **ctx)


@pytest.mark.parametrize("recall,value,field", [
    ("H-1388-2026", "00000ZRAA1", "code_info"),
    ("H-1388-2026", "00000ZUAD2", "code_info"),
    ("H-1361-2026", "TFIC207", "code_info"),
    ("H-1361-2026", "TFTX213U11", "code_info"),
    ("H-1396-2026", "L6080C", "code_info"),
    ("H-1396-2026", "L6079C", "code_info"),
    ("F-0536-2021", "04/20/2021", "code_info"),
    ("F-0536-2021", "05/04/2021", "code_info"),
    ("F-2413-2017", "3516", "code_info"),
    ("F-2413-2017", "3537", "code_info"),
])
def test_literal_occurs_only_with_selected_evidence(source, recall, value, field):
    assert validate_literal_identifier(source, value, [eid(recall, field)],
                                       **context(source, recall))[0].field_name == field


@pytest.mark.parametrize("recall,value", [
    ("H-1388-2026", "ZRAA1"),
    ("H-1388-2026", "00000ZRAA3"),
    ("H-1361-2026", "TFIC213U11"),
    ("H-1396-2026", "L6081C"),
    ("F-0536-2021", "04/21/2021"),
    ("F-2413-2017", "3517"),
])
def test_no_invented_truncated_or_unknown_identifier(source, recall, value):
    with pytest.raises(CitationError):
        validate_literal_identifier(source, value, [eid(recall)], **context(source, recall))


def test_unknown_code_is_preserved_as_source_text(source):
    assert source.lookup(**context(source, "F-1420-2012"))["code_info"] == "Unknown"


def test_preserve_group_c_relationship_text_without_normalization(source):
    assert source.lookup(**context(source, "H-1388-2026"))["code_info"] == (
        "LOT 00000ZRAA1  EXP 08/15/2026 LOT 00000ZUAD2  EXP 08/18/2026")
    assert source.lookup(**context(source, "H-1361-2026"))["code_info"].startswith(
        "Illinois: TFIC207, 8/7/2026; TFIC209, 8/9/2026")
    assert source.lookup(**context(source, "H-1396-2026"))["code_info"] == (
        "L6080C SEP 20 2027 L6079C SEP 19 2027")
    assert source.lookup(**context(source, "F-0536-2021"))["code_info"] == (
        "Use By: 04/20/2021 thru Use By:  05/04/2021")
    assert "1/10/2 018" in source.lookup(**context(source, "F-2413-2017"))["code_info"]
