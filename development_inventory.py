"""Select the 18 A1 development inventory sets without decoding other bodies."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re

from inventory_loader import _validate_record_shape
from source import DEVELOPMENT_RECORDS, Source


INVENTORY = "inventory_development.json"
CASES = "cases_development.json"
MANIFEST = "manifest.json"
CATALOG_COLUMNS = {"case_id", "inventory_set_id", "recall_number", "dataset_split",
                   "inventory_reference_date", "case_type", "source_system", "snapshot_id"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _selected_records(text: str, allowed: set[str]) -> tuple[dict, list[dict]]:
    """Decode the header and selected objects; scan past other object bodies."""
    start = re.search(r'"records"\s*:\s*\[', text)
    if start is None:
        raise ValueError("Inventory records array is missing")
    header = json.loads(re.sub(r",\s*$", "", text[:start.start()]) + "}")
    position, selected = start.end(), []
    while True:
        while position < len(text) and text[position] in " \t\r\n,":
            position += 1
        if position >= len(text):
            raise ValueError("Unterminated inventory array")
        if text[position] == "]":
            return header, selected
        if text[position] != "{":
            raise ValueError("Inventory array contains a non-object")
        begin, depth, quoted, escaped = position, 0, False, False
        while position < len(text):
            char = text[position]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    position += 1
                    break
            position += 1
        if depth:
            raise ValueError("Unterminated inventory object")
        raw = text[begin:position]
        key = re.search(r'"inventory_set_id"\s*:\s*("(?:[^"\\]|\\.)*")', raw)
        if key is None:
            raise ValueError("Inventory object lacks inventory_set_id")
        if json.loads(key.group(1)) in allowed:
            selected.append(json.loads(raw))


def _validate(payload: dict, cases: list[dict], source: Source) -> None:
    if payload.get("synthetic") is not True or payload.get("reference_snapshot_id") != source.snapshot_id:
        raise ValueError("Inventory synthetic flag or snapshot differs from A1")
    if [c["recall_number"] for c in cases] != list(DEVELOPMENT_RECORDS):
        raise ValueError("Case selection differs from the ordered 18 A1 recalls")
    if len({c["case_id"] for c in cases}) != 18 or len({c["inventory_set_id"] for c in cases}) != 18:
        raise ValueError("Case or inventory-set identity is duplicated")
    for case in cases:
        record = source.lookup(case["recall_number"], snapshot_id=source.snapshot_id)
        if (case["dataset_split"], case["snapshot_id"], case["event_id"]) != (
                "development", source.snapshot_id, record["event_id"]):
            raise ValueError("Case split, snapshot or event is not the selected development context")
    rows = payload["records"]
    if len(rows) != 36 or len({r["item_id"] for r in rows}) != 36:
        raise ValueError("Development inventory requires 36 distinct items")
    for row in rows:
        _validate_record_shape(row)
    groups = Counter(row["inventory_set_id"] for row in rows)
    allowed = {c["inventory_set_id"] for c in cases}
    if set(groups) != allowed or any(count != 2 for count in groups.values()):
        raise ValueError("Inventory set selection or pair counts differ from cases")
    for set_id in allowed:
        suffixes = sorted(r["item_id"].rsplit("-", 1)[-1] for r in rows if r["inventory_set_id"] == set_id)
        if suffixes != ["A", "B"]:
            raise ValueError("Each development set requires its original A/B pair")


def load_development_package(directory: Path, source: Source | None = None) -> tuple[dict, list[dict], dict]:
    source = source or Source()
    directory = Path(directory)
    manifest = json.loads((directory / MANIFEST).read_text())
    if (manifest.get("package"), manifest.get("snapshot_id")) != (
            "RecallReady A2 development inventory", source.snapshot_id):
        raise ValueError("Development manifest differs from the package/snapshot contract")
    data = {}
    for name in (INVENTORY, CASES):
        raw = (directory / name).read_bytes()
        if _sha(raw) != manifest["files"][name]:
            raise ValueError("Development file checksum mismatch: " + name)
        data[name] = json.loads(raw)
    payload, cases = data[INVENTORY], data[CASES]
    _validate(payload, cases, source)
    if manifest.get("counts") != {"recalls": 18, "inventory_sets": 18, "inventory_rows": 36}:
        raise ValueError("Development manifest counts differ from validated contents")
    return payload, cases, manifest


def prepare_development_inventory(package_dir: Path, output_dir: Path, source: Source | None = None) -> dict:
    """Copy literal selected rows; leave source package and existing outputs intact."""
    source = source or Source()
    package_dir, output_dir = Path(package_dir), Path(output_dir)
    if output_dir.exists():
        raise ValueError("Refusing to overwrite existing output directory")
    sums = {}
    for line in (package_dir / "SHA256SUMS.txt").read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            sums[name.strip().lstrip("*")] = digest
    names = ("02_retailer_inventory_SYNTHETIC.json", "03_case_catalog.csv")
    source_hashes = {}
    for name in names:
        source_hashes[name] = _sha((package_dir / name).read_bytes())
        if source_hashes[name] != sums.get(name):
            raise ValueError("Source package checksum mismatch: " + name)
    selected = {}
    with (package_dir / names[1]).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != CATALOG_COLUMNS:
            raise ValueError("Unexpected case catalog columns; labels must not enter the selector")
        for row in reader:
            recall = row["recall_number"]
            if recall not in DEVELOPMENT_RECORDS:
                continue
            if recall in selected:
                raise ValueError("Duplicate selected recall in case catalog")
            if row["dataset_split"] != "development" or row["snapshot_id"] != source.snapshot_id:
                raise ValueError("Selected recall is not matching development data")
            selected[recall] = dict(row, event_id=source.lookup(recall, snapshot_id=source.snapshot_id)["event_id"])
    if set(selected) != set(DEVELOPMENT_RECORDS):
        raise ValueError("Case catalog does not cover all 18 A1 recalls")
    cases = [selected[recall] for recall in DEVELOPMENT_RECORDS]
    allowed = {c["inventory_set_id"] for c in cases}
    header, rows = _selected_records((package_dir / names[0]).read_text(encoding="utf-8-sig"), allowed)
    payload = {"synthetic": header.get("synthetic"),
               "reference_snapshot_id": header.get("reference_snapshot_id"), "records": rows}
    _validate(payload, cases, source)
    blobs = {INVENTORY: (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(),
             CASES: (json.dumps(cases, ensure_ascii=False, indent=2) + "\n").encode()}
    manifest = {"package": "RecallReady A2 development inventory", "version": "1.0.0",
                "snapshot_id": source.snapshot_id,
                "counts": {"recalls": 18, "inventory_sets": 18, "inventory_rows": 36},
                "source_sha256": source_hashes,
                "selection_basis": "A1 DEVELOPMENT_RECORDS joined to catalog rows marked development",
                "evaluation_labels_included": False,
                "files": {name: _sha(raw) for name, raw in blobs.items()}}
    blobs[MANIFEST] = (json.dumps(manifest, indent=2) + "\n").encode()
    output_dir.mkdir(parents=True, exist_ok=False)
    # Manifest is written last; an incomplete export cannot pass the loader.
    for name, raw in blobs.items():
        fd = os.open(output_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
    load_development_package(output_dir, source)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    manifest = prepare_development_inventory(args.package_dir, args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "counts": manifest["counts"],
                      "snapshot_id": manifest["snapshot_id"]}, indent=2))
