"""Local exact FDA store for A1; Qdrant hits must resolve through this store."""

import hashlib
import json
import argparse
from pathlib import Path
import sqlite3
from uuid import UUID

from source import DEFAULT_ARCHIVE, DEVELOPMENT_RECORDS, FIELDS, Evidence, Source, SourceError


class StoreError(SourceError):
    """The selected FDA record or evidence cannot be trusted."""


def build_fda_store(path: Path, *, archive: Path = DEFAULT_ARCHIVE) -> None:
    """Create a new, FDA-only database from the verified immutable starter ZIP.

    Existing files are never overwritten. The ZIP remains the ingest authority;
    runtime reads use SQLite. Inventory and labels are not loaded.
    """
    path = Path(path)
    if path.exists():
        raise StoreError(f"Refusing to overwrite existing database: {path}")
    source = Source(archive)
    archive_sha256 = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE manifest (
                snapshot_id TEXT PRIMARY KEY,
                archive_sha256 TEXT NOT NULL,
                record_count INTEGER NOT NULL CHECK(record_count = 18),
                passage_count INTEGER NOT NULL CHECK(passage_count = 72)
            );
            CREATE TABLE records (
                recall_number TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                snapshot_id TEXT NOT NULL REFERENCES manifest(snapshot_id),
                original_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL
            );
            CREATE TABLE passages (
                evidence_id TEXT PRIMARY KEY,
                point_id TEXT NOT NULL UNIQUE,
                recall_number TEXT NOT NULL REFERENCES records(recall_number),
                event_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL REFERENCES manifest(snapshot_id),
                field_name TEXT NOT NULL,
                original_text TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                UNIQUE(recall_number, field_name)
            );
        """)
        db.execute("INSERT INTO manifest VALUES (?, ?, 18, 72)",
                   (source.snapshot_id, archive_sha256))
        for recall in DEVELOPMENT_RECORDS:
            record = source.lookup(recall, snapshot_id=source.snapshot_id)
            payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)",
                       (recall, record["event_id"], source.snapshot_id, payload,
                        hashlib.sha256(payload.encode()).hexdigest()))
            context = dict(recall_number=recall, event_id=record["event_id"],
                           snapshot_id=source.snapshot_id)
            for field in FIELDS:
                evidence = source.resolve(f"EV-{recall}-{field.upper()}", **context)
                db.execute("INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (evidence.evidence_id, evidence.point_id, recall,
                            evidence.event_id, evidence.snapshot_id, field,
                            evidence.original_text,
                            hashlib.sha256(evidence.original_text.encode()).hexdigest()))


class FDAStore:
    """Read-only exact resolver; no nearest-neighbor search or inventory access."""

    def __init__(self, path: Path) -> None:
        path = Path(path).resolve(strict=True)
        self._db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            self._db.row_factory = sqlite3.Row
            rows = self._db.execute("SELECT * FROM manifest").fetchall()
            if len(rows) != 1 or rows[0]["record_count"] != 18 or rows[0]["passage_count"] != 72:
                raise StoreError("Invalid FDA store manifest")
            self.snapshot_id = rows[0]["snapshot_id"]
            self.archive_sha256 = rows[0]["archive_sha256"]
            counts = (self._db.execute("SELECT count(*) FROM records").fetchone()[0],
                      self._db.execute("SELECT count(*) FROM passages").fetchone()[0])
            if counts != (18, 72):
                raise StoreError("FDA store counts differ from manifest")
        except Exception:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def lookup(self, recall_number: str, *, snapshot_id: str,
               event_id: str | None = None) -> dict:
        if snapshot_id != self.snapshot_id or not isinstance(recall_number, str):
            raise StoreError("Recall/snapshot mismatch")
        row = self._db.execute("SELECT * FROM records WHERE recall_number = ?",
                               (recall_number,)).fetchone()
        if row is None or (event_id is not None and event_id != row["event_id"]):
            raise StoreError("Unknown recall or event mismatch")
        if hashlib.sha256(row["original_json"].encode()).hexdigest() != row["content_sha256"]:
            raise StoreError("FDA record content hash mismatch")
        record = json.loads(row["original_json"])
        if (record["recall_number"], record["event_id"], row["snapshot_id"]) != (
            recall_number, row["event_id"], snapshot_id
        ):
            raise StoreError("FDA record identity mismatch")
        return record

    def resolve(self, evidence_id: str, *, recall_number: str,
                event_id: str, snapshot_id: str) -> Evidence:
        record = self.lookup(recall_number, event_id=event_id, snapshot_id=snapshot_id)
        row = self._db.execute("SELECT * FROM passages WHERE evidence_id = ?",
                               (evidence_id,)).fetchone() if isinstance(evidence_id, str) else None
        if row is None or (row["recall_number"], row["event_id"], row["snapshot_id"]) != (
            recall_number, event_id, snapshot_id
        ):
            raise StoreError("Unknown or cross-context evidence")
        field = row["field_name"]
        if (field not in FIELDS or evidence_id != f"EV-{recall_number}-{field.upper()}"
                or row["original_text"] != record.get(field)
                or hashlib.sha256(row["original_text"].encode()).hexdigest() != row["content_sha256"]):
            raise StoreError("FDA passage differs from exact source field")
        try:
            UUID(row["point_id"])
        except ValueError as exc:
            raise StoreError("Invalid point ID") from exc
        return Evidence(evidence_id=evidence_id, point_id=row["point_id"],
                        recall_number=recall_number, event_id=event_id,
                        snapshot_id=snapshot_id, field_name=field,
                        original_text=row["original_text"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a new exact FDA A1 SQLite store")
    parser.add_argument("path", type=Path, help="New database path; existing files are refused")
    args = parser.parse_args()
    build_fda_store(args.path)
    with FDAStore(args.path) as store:
        print(f"Created {args.path}: snapshot={store.snapshot_id}, archive_sha256={store.archive_sha256}")
