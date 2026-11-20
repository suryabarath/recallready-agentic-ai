"""Coordinator-facing A1 envelope; the inner facts contracts are unchanged."""

from datetime import datetime, timezone
import time
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from a1_service import A1RunError, run_a1
from a1_trace import RequestState, RunRecorder, RunTrace, active_run
from fda_store import FDAStore
from group_c_contract import GroupCResult
from interpreter import Budget
from models import A1Result, Nonblank, StrictModel
from openai import OpenAI
from qdrant_a1 import COLLECTION, MODEL, QdrantA1
from validation import HumanLotApproval


class RunError(StrictModel):
    stage: Literal["preflight", "retrieval", "interpretation", "validation", "accounting"]
    code: Nonblank
    message: Nonblank
    request_state: RequestState
    automatic_retry_allowed: Literal[False] = False


class A1RunEnvelope(StrictModel):
    run_id: Nonblank
    status: Literal["validated", "unresolved"]
    result: Annotated[A1Result | GroupCResult, Field(discriminator="contract_version")] | None
    error: RunError | None
    trace: RunTrace

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if self.status == "validated":
            if self.result is None or self.error is not None:
                raise ValueError("Validated run requires a result and no error")
        elif self.result is not None or self.error is None:
            raise ValueError("Unresolved run requires an error and no result")
        return self


def run_a1_with_trace(store: FDAStore, retriever: QdrantA1, client: OpenAI, budget: Budget, *,
                      run_id: str, recall_number: str, snapshot_id: str,
                      event_id: str | None = None,
                      approved_lots: tuple[HumanLotApproval, ...] = (),
                      max_output_tokens: int = 4000) -> A1RunEnvelope:
    """Capture one run without reading global ledger differences or closing caller resources.

    Callers provide a unique run_id. Invalid envelope argument types raise
    validation errors before execution. Each reservation links its call ID to
    this run in the ledger transaction; no full trace or source text is logged.
    """
    run_id = TypeAdapter(Nonblank).validate_python(run_id)
    trace = RunTrace(recall_number=recall_number, snapshot_id=snapshot_id,
                     collection=COLLECTION, embedding_model=MODEL,
                     max_output_tokens=max_output_tokens,
                     started_utc=datetime.now(timezone.utc).isoformat())
    token = active_run.set(RunRecorder(run_id, trace))
    started = time.perf_counter()
    result = None
    error = None
    try:
        result = run_a1(store, retriever, client, budget, recall_number=recall_number,
                        snapshot_id=snapshot_id, event_id=event_id,
                        approved_lots=approved_lots, max_output_tokens=max_output_tokens)
    except A1RunError as exc:
        # Safe category messages: do not copy model text or low-level diagnostics into traces.
        message = ("Request may already be charged; reservation retained; no automatic retry."
                   if exc.code == "usage_settlement_failed" else
                   "A1 could not return validated facts; review the failure code before retrying.")
        state = trace.calls[-1].request_state if trace.calls else "not_sent"
        error = RunError(stage=exc.stage or "interpretation", code=exc.code,
                         message=message, request_state=state)
        if exc.code in {"usage_ledger_unavailable", "usage_reservation_failed",
                        "usage_settlement_failed", "usage_missing"}:
            trace.accounting_available = False
    finally:
        trace.elapsed_seconds = time.perf_counter() - started
        trace.completed_utc = datetime.now(timezone.utc).isoformat()
        active_run.reset(token)
    trace.summarize()
    return A1RunEnvelope(run_id=run_id, status="validated" if error is None else "unresolved",
                         result=result, error=error, trace=trace)
