"""Tests use actual Group A source bytes, with no model or retrieval stubs."""

from dataclasses import replace
import hashlib
import json
from zipfile import ZipFile

import pytest

from citations import CitationError, validate_citation, validate_literal_identifier
from source import DEFAULT_ARCHIVE, Evidence, FIELDS, GROUP_A, Source, SourceError


SNAPSHOT = "FDA-FOOD-2026-10-23-USER-SNAPSHOT"
EVENTS = dict(zip(GROUP_A, ("99686", "92944", "94806", "97487", "96464", "91439")))
PREFIX = "RecallReady_Agent1_FDA_18_Starter/"
CASES = [(r, f) for r in GROUP_A for f in FIELDS]


def context(recall):
    return dict(recall_number=recall, snapshot_id=SNAPSHOT, event_id=EVENTS[recall])


def eid(recall, field="code_info"):
    return f"EV-{recall}-{field.upper()}"


@pytest.fixture(scope="module")
def source():
    return Source()


@pytest.fixture(scope="module")
def raw():
    with ZipFile(DEFAULT_ARCHIVE) as z:
        records = json.loads(z.read(PREFIX + "01_FDA_Original_Source_18.json"))["results"]
        passages = [json.loads(line) for line in z.read(PREFIX + "03_Agent1_Evidence_Passages_72.jsonl").splitlines()]
    return ({r["recall_number"]: r for r in records if r["recall_number"] in GROUP_A},
            {p["evidence_id"]: p for p in passages if p["recall_number"] in GROUP_A})


def test_starter_unchanged():
    assert hashlib.sha256(DEFAULT_ARCHIVE.read_bytes()).hexdigest() == (
        "b1f55e7cc2b0ec37c29b87af31478230766b3ba9b45bd0db03c8c38c1bfe2f0e"
    )


@pytest.mark.parametrize("recall", GROUP_A)
def test_six_exact_lookups(source, raw, recall):
    # Exact lookup discovers event metadata without requiring it in advance.
    actual = source.lookup(recall, snapshot_id=SNAPSHOT)
    assert actual == raw[0][recall]
    assert actual["event_id"] == EVENTS[recall]
    # Callers cannot change authoritative fields, including nested metadata.
    actual["code_info"] = "invented"
    actual["openfda"]["invented"] = True
    assert source.lookup(**context(recall)) == raw[0][recall]


@pytest.mark.parametrize("recall,field", CASES)
def test_all_24_passages(source, raw, recall, field):
    p = raw[1][eid(recall, field)]
    citation = Evidence(**{key: p[key] for key in Evidence.__dataclass_fields__})
    actual = validate_citation(source, citation, **context(recall))
    assert vars(actual) == {key: p[key] for key in vars(actual)}
    assert actual.original_text == raw[0][recall][field]
    assert actual is source.resolve(citation.evidence_id, **context(recall))


@pytest.mark.parametrize("recall,field", CASES)
@pytest.mark.parametrize("change", [
    {"evidence_id": "EV-INVENTED-CODE_INFO"},
    {"point_id": "00000000-0000-0000-0000-000000000000"},
    {"recall_number": "F-1542-2023"},
    {"event_id": "999999"},
    {"snapshot_id": "FDA-FOOD-OTHER-SNAPSHOT"},
    {"field_name": "classification"},
    {"original_text": "invented source text"},
])
def test_reject_altered_citations(source, recall, field, change):
    e = source.resolve(eid(recall, field), **context(recall))
    if change == {"recall_number": "F-1542-2023"} and recall == "F-1542-2023":
        change = {"recall_number": "H-0011-2027"}
    with pytest.raises(CitationError):
        validate_citation(source, replace(e, **change), **context(recall))


@pytest.mark.parametrize("recall", GROUP_A)
def test_reject_other_recalls_evidence(source, recall):
    other = GROUP_A[(GROUP_A.index(recall) + 1) % 6]
    with pytest.raises(SourceError):
        source.resolve(eid(other), **context(recall))
    other_evidence = source.resolve(eid(other), **context(other))
    with pytest.raises(CitationError):
        validate_citation(source, other_evidence, **context(recall))


@pytest.mark.parametrize("changes", [
    {"recall_number": "F-0000-9999"},
    {"recall_number": "H-11-2027"},
    {"recall_number": "h-0011-2027"},
    {"recall_number": " H-0011-2027"},
    {"recall_number": "H-1388-2027"},  # similar but nonexistent recall
    {"recall_number": None},
    {"event_id": "92944"},  # real event from another recall
    {"event_id": 99686},
    {"event_id": "099686"},
    {"snapshot_id": "FDA-FOOD-OTHER-SNAPSHOT"},
])
def test_reject_wrong_selection_context(source, changes):
    ctx = context(GROUP_A[0]) | changes
    with pytest.raises(SourceError):
        source.lookup(**ctx)
    with pytest.raises(SourceError):
        source.resolve(eid(GROUP_A[0]), **ctx)
    with pytest.raises(CitationError):
        validate_literal_identifier(source, "26078", [eid(GROUP_A[0])], **ctx)


@pytest.mark.parametrize("value,recall,field", [
    ("26078", "H-0011-2027", "code_info"),
    ("09/15/2026", "H-0011-2027", "code_info"),
    ("850041392103", "H-0011-2027", "product_description"),
    ("060723", "F-1542-2023", "code_info"),
    ("06-04-24", "F-1472-2024", "code_info"),
    ("08/04/2024", "F-1472-2024", "code_info"),
    ("25223M", "H-0579-2025", "code_info"),
    ("24682-05020", "H-0579-2025", "code_info"),
    ("499-6100", "H-0579-2025", "code_info"),
    ("04162026", "F-0705-2025", "code_info"),
    ("6937218914734", "F-0705-2025", "code_info"),
    ("336", "F-0324-2023", "code_info"),
    ("Jan 06 2023", "F-0324-2023", "code_info"),
    ("17442 30012", "F-0324-2023", "product_description"),
])
def test_supported_exact_literals(source, value, recall, field):
    result = validate_literal_identifier(source, value, [eid(recall, field)], **context(recall))
    assert result[0].original_text == source.lookup(**context(recall))[field]
    assert value in result[0].original_text


@pytest.mark.parametrize("value,recall", [
    ("60723", "F-1542-2023"),  # dropped leading zero
    ("4162026", "F-0705-2025"),
    (60723, "F-1542-2023"),
    ("060724", "F-1542-2023"),
    ("0607230", "F-1542-2023"),
    (" 060723", "F-1542-2023"),  # no trimming/normalization
    ("2607", "H-0011-2027"),
    ("15/2026", "H-0011-2027"),
    ("04-24", "F-1472-2024"),
    ("25223m", "H-0579-2025"),
    ("05020", "H-0579-2025"),
    ("25223M.*", "H-0579-2025"),  # literal, not a regex
    ("", "F-0324-2023"),
    (" ", "F-0324-2023"),
    ("Jan 6 2023", "F-0324-2023"),
    ("26078", "F-0324-2023"),  # value from another recall
])
def test_reject_unsupported_literals(source, value, recall):
    with pytest.raises(CitationError):
        validate_literal_identifier(source, value, [eid(recall)], **context(recall))


@pytest.mark.parametrize("evidence_ids", [
    [], ["EV-INVENTED-CODE_INFO"], [eid("F-1542-2023")],
    [eid("H-0011-2027", "reason_for_recall")],
    [eid("H-0011-2027"), eid("H-0011-2027", "distribution_pattern")],
])
def test_reject_missing_unrelated_or_extra_unsupported_citations(source, evidence_ids):
    with pytest.raises(CitationError):
        validate_literal_identifier(source, "26078", evidence_ids, **context("H-0011-2027"))


def test_citation_requires_explicit_correct_event(source):
    ctx = context("H-0011-2027") | {"event_id": None}
    with pytest.raises(SourceError):
        source.resolve(eid("H-0011-2027"), **ctx)


def test_preserve_ambiguous_and_multiple_code_text(source):
    # Preserve the unlabeled date-like suffix without assigning an expiry meaning.
    assert source.lookup(**context("F-1472-2024"))["code_info"] == "LOT # 06-04-24 08/04/2024"
    assert source.lookup(**context("H-0579-2025"))["code_info"] == (
        '" Lot Number: 25223M  " SKU: 24682-05020 " Consecutive Count: 499-6100'
    )
    assert source.lookup(**context("F-0705-2025"))["code_info"] == "Lot: 04162026 BC 6937218914734"
