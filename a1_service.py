"""Standalone A1: exact selection, complete retrieval, bounded interpretation."""

import sqlite3
import time

from openai import OpenAI

from fda_store import FDAStore
from group_c_contract import GroupCResult
from group_c_interpreter import interpret_group_c
from interpreter import Budget, InterpretationError, interpret
from models import A1Result
from qdrant_a1 import EvidenceHit, QdrantA1
from reviews import check_reviews
from source import DEVELOPMENT_RECORDS, FIELDS, GROUP_C
from validation import HumanLotApproval
from a1_trace import active_run, RetrievedReference


# Recall selection is exact. This fixed query only ranks passages within it.
RETRIEVAL_QUERY = "Product description, lot batch codes and dates, recall reason and distribution"


class A1RunError(InterpretationError):
    """An A1 stage failed; no successful result is returned."""


def run_a1(store: FDAStore, retriever: QdrantA1, client: OpenAI, budget: Budget, *,
           recall_number: str, snapshot_id: str, event_id: str | None = None,
           approved_lots: tuple[HumanLotApproval, ...] = (),
           max_output_tokens: int = 4000) -> A1Result | GroupCResult:
    """Return the existing validated contract; never fall back after retrieval failure.

    The caller owns resources, credentials, budget and explicit human reviews.
    Qdrant must return all four canonical passages because both existing output
    contracts require complete source fields. The interpreters re-read those
    same evidence IDs from SQLite and validate their final output against it.
    Group C retains its provisional envelope and mandatory review uncertainty.
    No inventory, CaseState contract, or automatic semantic retry is introduced.
    """
    stage = "preflight"
    try:
        if recall_number not in DEVELOPMENT_RECORDS:
            raise A1RunError("Unknown development recall")
        if retriever.store is not store:
            raise A1RunError("Retriever must use the same exact FDA store")
        if client.max_retries != 0:
            raise A1RunError("SDK retries must be disabled")
        if type(max_output_tokens) is not int or not 256 <= max_output_tokens <= 8000:
            raise A1RunError("Output limit must be 256..8000 tokens")
        record = store.lookup(recall_number, snapshot_id=snapshot_id, event_id=event_id)
        ctx = dict(recall_number=recall_number, snapshot_id=snapshot_id,
                   event_id=record["event_id"])
        if recorder := active_run.get():
            recorder.trace.event_id = record["event_id"]
            recorder.trace.archive_sha256 = store.archive_sha256
        if recall_number in GROUP_C and approved_lots:
            raise A1RunError("Group C does not accept Group A/B lot approvals")
        try:
            check_reviews(approved_lots, store, **ctx)
        except (ValueError, TypeError) as exc:
            raise A1RunError(str(exc), stage="preflight", code="invalid_review") from exc

        stage = "retrieval"
        started = time.perf_counter()
        try:
            hits = retriever.query(RETRIEVAL_QUERY, recall_number=recall_number,
                                   snapshot_id=snapshot_id, top_k=8)
        finally:
            if recorder := active_run.get():
                recorder.trace.retrieval_seconds = time.perf_counter() - started
        required = {f"EV-{recall_number}-{field.upper()}" for field in FIELDS}
        if (len(hits) != len(required) or any(not isinstance(hit, EvidenceHit) for hit in hits)
                or {hit.evidence_id for hit in hits} != required):
            raise A1RunError("Retrieval must return all four distinct source passages",
                             stage="retrieval", code="incomplete_evidence")
        for hit in hits:
            exact = store.resolve(hit.evidence_id, **ctx)
            if any(getattr(hit, key) != getattr(exact, key) for key in vars(exact)):
                raise A1RunError("Retrieved evidence differs from exact SQLite source")
        if recorder := active_run.get():
            recorder.trace.retrieved = [RetrievedReference(
                evidence_id=hit.evidence_id, point_id=hit.point_id,
                similarity_score=hit.similarity_score) for hit in hits]

        stage = "interpretation"
        if recall_number in GROUP_C:
            return interpret_group_c(store, client, budget, recall_number=recall_number,
                                     snapshot_id=snapshot_id, max_output_tokens=max_output_tokens)
        return interpret(store, client, budget, recall_number=recall_number,
                         snapshot_id=snapshot_id, approved_lots=approved_lots,
                         max_output_tokens=max_output_tokens)
    except (sqlite3.Error, OSError):
        raise A1RunError(f"A1 {stage} failed: local storage unavailable; no automatic retry",
                         stage=stage, code="local_storage_unavailable") from None
    except (ValueError, TypeError) as exc:
        code = (exc.code if isinstance(exc, InterpretationError) and
                exc.code != "interpretation_failed" else
                "retrieval_failed" if stage == "retrieval" else
                "invalid_context" if stage == "preflight" else "interpretation_failed")
        raise A1RunError(f"A1 {stage} failed: {exc}",
                         stage=getattr(exc, "stage", None) or stage, code=code) from exc
