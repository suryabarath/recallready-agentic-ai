"""Offline Task 02A source access. Reads the immutable starter ZIP in place."""

from copy import deepcopy
from dataclasses import dataclass
import csv
import hashlib
import io
import json
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile


GROUP_A = (
    "H-0011-2027", "F-1542-2023", "F-1472-2024",
    "H-0579-2025", "F-0705-2025", "F-0324-2023",
)
GROUP_B = (
    "F-0818-2023", "F-0882-2023", "F-1025-2023",
    "F-0011-2024", "F-0332-2023", "H-1273-2026",
)
GROUP_C = (
    "H-1388-2026", "H-1361-2026", "H-1396-2026",
    "F-1420-2012", "F-0536-2021", "F-2413-2017",
)
DEVELOPMENT_RECORDS = GROUP_A + GROUP_B + GROUP_C
FIELDS = ("product_description", "code_info", "reason_for_recall", "distribution_pattern")
DEFAULT_ARCHIVE = (
    Path(__file__).resolve().parent.parent / "project_reference"
    / "RecallReady_Agent1_FDA_18_Starter.zip"
)
_PREFIX = "RecallReady_Agent1_FDA_18_Starter/"


class SourceError(ValueError):
    """An exact source reference cannot be resolved or verified."""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    point_id: str
    recall_number: str
    event_id: str
    snapshot_id: str
    field_name: str
    original_text: str


class Source:
    """Exact Group A+B+C records and passages; no derived fields or normalization.

    Local original JSON fields are authoritative. Packaged checksums detect
    accidental corruption, not malicious replacement of the entire archive.
    Returned records are copies and evidence objects are immutable.
    """

    def __init__(self, archive: Path = DEFAULT_ARCHIVE) -> None:
        with ZipFile(archive) as z:
            sums = dict(
                (name, digest)
                for digest, name in (
                    line.split("  ", 1)
                    for line in z.read(_PREFIX + "SHA256SUMS.txt").decode().splitlines()
                    if line.strip()
                )
            )

            def read(name: str) -> str:
                content = z.read(_PREFIX + name)
                if hashlib.sha256(content).hexdigest() != sums.get(name):
                    raise SourceError(f"Checksum mismatch: {name}")
                return content.decode("utf-8-sig")

            original = json.loads(read("01_FDA_Original_Source_18.json"))
            manifest = json.loads(read("08_Agent1_Manifest.json"))
            selection = list(csv.DictReader(io.StringIO(read("05_Agent1_Record_Selection.csv"))))
            passages = [json.loads(line) for line in read("03_Agent1_Evidence_Passages_72.jsonl").splitlines() if line.strip()]

        self._snapshot_id: str = manifest["snapshot_id"]
        if original["meta"]["snapshot_id"] != self.snapshot_id:
            raise SourceError("Source/manifest snapshot mismatch")
        selected_a = [r for r in selection if r["development_group"] == "A - Basics"]
        selected_b = [r for r in selection if r["development_group"] == "B - Intermediate"]
        selected_c = [r for r in selection if r["development_group"] == "C - Challenge"]
        if tuple(r["recall_number"] for r in selected_a) != GROUP_A:
            raise SourceError("Group A selection mismatch")
        if tuple(r["recall_number"] for r in selected_b) != GROUP_B:
            raise SourceError("Group B selection mismatch")
        if tuple(r["recall_number"] for r in selected_c) != GROUP_C:
            raise SourceError("Group C selection mismatch")
        selected = selected_a + selected_b + selected_c
        self._records: dict[str, dict] = {}
        for record in original["results"]:
            recall = record["recall_number"]
            if recall not in DEVELOPMENT_RECORDS:
                continue
            if recall in self._records or record["product_type"] != "Food":
                raise SourceError(f"Duplicate or non-food source: {recall}")
            if not isinstance(record["event_id"], str):
                raise SourceError(f"Non-string event ID: {recall}")
            self._records[recall] = record
        if set(self._records) != set(DEVELOPMENT_RECORDS):
            raise SourceError("Missing Group A, B, or C source")
        if len({r["event_id"] for r in self._records.values()}) != len(DEVELOPMENT_RECORDS):
            raise SourceError("Duplicate development events")
        for row in selected:
            if row["event_id"] != self._records[row["recall_number"]]["event_id"]:
                raise SourceError("Selection/source event mismatch")

        self._evidence: dict[str, Evidence] = {}
        points: set[str] = set()
        fields: set[tuple[str, str]] = set()
        for p in passages:
            if p["recall_number"] not in DEVELOPMENT_RECORDS:
                continue
            e = Evidence(**{k: p[k] for k in Evidence.__dataclass_fields__})
            if not all(isinstance(v, str) for v in vars(e).values()):
                raise SourceError("Non-string evidence field")
            record = self._records[e.recall_number]
            if (e.snapshot_id != self.snapshot_id or e.event_id != record["event_id"]
                    or e.field_name not in FIELDS
                    or e.original_text != record.get(e.field_name)):
                raise SourceError(f"Source/passage mismatch: {e.evidence_id}")
            if e.evidence_id != f"EV-{e.recall_number}-{e.field_name.upper()}":
                raise SourceError(f"Unexpected evidence ID: {e.evidence_id}")
            try:
                UUID(e.point_id)
            except ValueError as exc:
                raise SourceError(f"Invalid point ID: {e.point_id}") from exc
            pair = (e.recall_number, e.field_name)
            if e.evidence_id in self._evidence or e.point_id in points or pair in fields:
                raise SourceError("Duplicate evidence, point, or source field")
            self._evidence[e.evidence_id] = e
            points.add(e.point_id)
            fields.add(pair)
        if fields != {(r, f) for r in DEVELOPMENT_RECORDS for f in FIELDS}:
            raise SourceError("Expected exactly four passages for each development recall")

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id

    def lookup(self, recall_number: str, *, snapshot_id: str,
               event_id: str | None = None) -> dict:
        """Fetch by exact recall/snapshot; verify an event if supplied.

        The caller may discover the event from the record. Citation resolution
        always requires it explicitly.
        """
        if not isinstance(recall_number, str) or recall_number not in self._records:
            raise SourceError(f"Unknown or out-of-scope recall: {recall_number!r}")
        record = self._records[recall_number]
        if snapshot_id != self.snapshot_id or (event_id is not None and event_id != record["event_id"]):
            raise SourceError("Recall/event/snapshot mismatch")
        return deepcopy(record)

    def resolve(self, evidence_id: str, *, recall_number: str,
                snapshot_id: str, event_id: str) -> Evidence:
        self.lookup(recall_number, snapshot_id=snapshot_id, event_id=event_id)
        if not isinstance(evidence_id, str) or evidence_id not in self._evidence:
            raise SourceError(f"Unknown or out-of-scope evidence: {evidence_id!r}")
        e = self._evidence[evidence_id]
        if (e.recall_number, e.event_id, e.snapshot_id) != (recall_number, event_id, snapshot_id):
            raise SourceError("Cross-recall/event/snapshot evidence")
        return e
