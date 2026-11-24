"""Selection/export guards using generated fixtures, not evaluation data."""

from copy import deepcopy
import csv
import hashlib
import io
import json

import pytest

from development_inventory import (CASES, CATALOG_COLUMNS, INVENTORY, MANIFEST,
                                   load_development_package, prepare_development_inventory)
from source import DEVELOPMENT_RECORDS, Source
from test_inventory_match import _make_row


@pytest.fixture
def generated():
    source = Source()
    cases, rows = [], []
    for i, recall in enumerate(DEVELOPMENT_RECORDS):
        set_id = f"GENERATED-{i:03d}"
        cases.append(dict(case_id=f"CASE-GEN-{i:03d}", inventory_set_id=set_id,
                          recall_number=recall, dataset_split="development",
                          inventory_reference_date="2026-01-01", case_type="Synthetic historical case",
                          source_system="openFDA_food_enforcement", snapshot_id=source.snapshot_id))
        for suffix in ("A", "B"):
            rows.append(_make_row(inventory_set_id=set_id, item_id=f"GEN-{i:03d}-{suffix}",
                                  lot_code=f"000{i}", upc="001234567890",
                                  synthetic_generation_note='Preserve { } and "quotes" and café').model_dump())
    return source, cases, rows


def write_package(directory, cases, rows, snapshot):
    directory.mkdir()
    raw = (json.dumps({"synthetic": True, "reference_snapshot_id": snapshot, "records": rows}) + "\n").encode()
    text = io.StringIO(newline="")
    columns = list(CATALOG_COLUMNS)
    if cases and "proposed_label" in cases[0]:
        columns.append("proposed_label")
    writer = csv.DictWriter(text, fieldnames=columns)
    writer.writeheader()
    writer.writerows(cases)
    catalog = text.getvalue().encode()
    for name, content in (("02_retailer_inventory_SYNTHETIC.json", raw), ("03_case_catalog.csv", catalog)):
        (directory / name).write_bytes(content)
    (directory / "SHA256SUMS.txt").write_text(
        hashlib.sha256(raw).hexdigest() + "  02_retailer_inventory_SYNTHETIC.json\n"
        + hashlib.sha256(catalog).hexdigest() + "  03_case_catalog.csv\n")


def test_select_exact_rows_preserve_strings_and_source(tmp_path, generated):
    source, cases, rows = generated
    outside = _make_row(inventory_set_id="UNSELECTED", item_id="UNSELECTED-A").model_dump()
    package, output = tmp_path / "input", tmp_path / "output"
    write_package(package, list(reversed(cases)), rows + [outside], source.snapshot_id)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in package.iterdir()}
    manifest = prepare_development_inventory(package, output, source)
    actual, selected, loaded = load_development_package(output, source)
    assert actual["records"] == rows
    assert [c["recall_number"] for c in selected] == list(DEVELOPMENT_RECORDS)
    assert loaded == manifest
    assert manifest["counts"] == {"recalls": 18, "inventory_sets": 18, "inventory_rows": 36}
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in package.iterdir()} == hashes
    assert {p.name for p in output.iterdir()} == {INVENTORY, CASES, MANIFEST}
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir())


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_split", "wrong_snapshot", "label_column"])
def test_reject_invalid_catalog_before_export(tmp_path, generated, change):
    source, cases, rows = generated
    cases = deepcopy(cases)
    if change == "missing": cases.pop()
    elif change == "duplicate": cases.append(cases[0].copy())
    elif change == "wrong_split": cases[0]["dataset_split"] = "holdout"
    elif change == "wrong_snapshot": cases[0]["snapshot_id"] = "OTHER"
    else:
        for case in cases: case["proposed_label"] = "do-not-ingest"
    package, output = tmp_path / "input", tmp_path / "output"
    write_package(package, cases, rows, source.snapshot_id)
    with pytest.raises(ValueError):
        prepare_development_inventory(package, output, source)
    assert not output.exists()


@pytest.mark.parametrize("change", ["missing_row", "duplicate_item", "wrong_suffix", "bad_type", "wrong_snapshot"])
def test_reject_invalid_selected_inventory(tmp_path, generated, change):
    source, cases, rows = generated
    rows = deepcopy(rows)
    snapshot = source.snapshot_id
    if change == "missing_row": rows.pop()
    elif change == "duplicate_item": rows[1]["item_id"] = rows[0]["item_id"]
    elif change == "wrong_suffix": rows[1]["item_id"] = "wrong-C"
    elif change == "bad_type": rows[0]["lot_code"] = 123
    else: snapshot = "OTHER"
    package, output = tmp_path / "input", tmp_path / "output"
    write_package(package, cases, rows, snapshot)
    with pytest.raises(ValueError):
        prepare_development_inventory(package, output, source)
    assert not output.exists()


def test_reject_tampered_source_checksum(tmp_path, generated):
    source, cases, rows = generated
    package = tmp_path / "input"
    write_package(package, cases, rows, source.snapshot_id)
    with (package / "02_retailer_inventory_SYNTHETIC.json").open("a") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        prepare_development_inventory(package, tmp_path / "output", source)


def test_refuse_overwrite_and_reject_tampered_export(tmp_path, generated):
    source, cases, rows = generated
    package, output = tmp_path / "input", tmp_path / "output"
    write_package(package, cases, rows, source.snapshot_id)
    prepare_development_inventory(package, output, source)
    before = (output / MANIFEST).read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        prepare_development_inventory(package, output, source)
    assert (output / MANIFEST).read_bytes() == before
    with (output / INVENTORY).open("a") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_development_package(output, source)
