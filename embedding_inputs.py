"""Verify FDA-only embedding inputs before any MiniLM or Qdrant operation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

from fda_store import FDAStore
from source import DEFAULT_ARCHIVE, DEVELOPMENT_RECORDS, FIELDS


_PREFIX = "RecallReady_Agent1_FDA_18_Starter/"
_PASSAGES = "03_Agent1_Evidence_Passages_72.jsonl"
_STAGING = "04_Agent1_Qdrant_Staging_72_NO_VECTORS.jsonl"


class EmbeddingInputError(ValueError):
    """The staging data does not match exact FDA evidence."""


@dataclass(frozen=True)
class EmbeddingInput:
    point_id: str
    evidence_id: str
    recall_number: str
    event_id: str
    snapshot_id: str
    field_name: str
    text_for_embedding: str


def load_embedding_inputs(store: FDAStore, *, archive: Path = DEFAULT_ARCHIVE) -> tuple[EmbeddingInput, ...]:
    """Read 72 vector-free points and bind each to trusted SQLite evidence."""
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != store.archive_sha256:
        raise EmbeddingInputError("Embedding archive differs from FDA store manifest")
    with ZipFile(archive) as z:
        sums = {name: digest for digest, name in
                (line.split("  ", 1) for line in
                 z.read(_PREFIX + "SHA256SUMS.txt").decode().splitlines() if line.strip())}

        def verified(name: str) -> bytes:
            raw = z.read(_PREFIX + name)
            if hashlib.sha256(raw).hexdigest() != sums.get(name):
                raise EmbeddingInputError(f"Starter member checksum mismatch: {name}")
            return raw

        passages = [json.loads(line) for line in verified(_PASSAGES).splitlines() if line.strip()]
        points = [json.loads(line) for line in verified(_STAGING).splitlines() if line.strip()]
    if len(passages) != 72 or len(points) != 72:
        raise EmbeddingInputError("Expected exactly 72 passages and staging points")
    by_evidence = {p["evidence_id"]: p for p in passages}
    if len(by_evidence) != 72:
        raise EmbeddingInputError("Duplicate evidence ID in embedding input")
    expected_ids = {f"EV-{recall}-{field.upper()}" for recall in DEVELOPMENT_RECORDS for field in FIELDS}
    if set(by_evidence) != expected_ids:
        raise EmbeddingInputError("Embedding passages differ from selected FDA scope")
    result = []
    seen_points = set()
    for point in points:
        payload = point["payload"]
        evidence_id = payload["evidence_id"]
        if evidence_id not in by_evidence:
            raise EmbeddingInputError("Unknown staging evidence ID")
        passage = by_evidence[evidence_id]
        context = dict(recall_number=payload["recall_number"],
                       event_id=payload["event_id"], snapshot_id=payload["snapshot_id"])
        try:
            exact = store.resolve(evidence_id, **context)
            UUID(point["id"])
        except (ValueError, KeyError) as exc:
            raise EmbeddingInputError("Staging point cannot resolve to exact FDA evidence") from exc
        if (point["id"] != exact.point_id or point["id"] in seen_points
                or point["vector"] is not None
                or point["text_for_embedding"] != passage["embedding_text"]
                or any(passage[key] != getattr(exact, key) for key in
                       ("evidence_id", "point_id", "recall_number", "event_id",
                        "snapshot_id", "field_name", "original_text"))
                or payload["field_name"] != exact.field_name
                or payload["source_system"] != "openFDA_food_enforcement"):
            raise EmbeddingInputError("Staging metadata, text, or vector differs from FDA passage")
        seen_points.add(point["id"])
        result.append(EmbeddingInput(point_id=exact.point_id,
                                     evidence_id=evidence_id,
                                     recall_number=exact.recall_number,
                                     event_id=exact.event_id,
                                     snapshot_id=exact.snapshot_id,
                                     field_name=exact.field_name,
                                     text_for_embedding=passage["embedding_text"]))
    if {item.evidence_id for item in result} != expected_ids:
        raise EmbeddingInputError("Missing or duplicate staging evidence")
    return tuple(result)
