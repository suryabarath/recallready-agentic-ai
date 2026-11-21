"""Run-local operational metadata; no prompts, credentials or source text."""

from contextvars import ContextVar
from typing import Literal

from pydantic import Field

from models import StrictModel


RequestState = Literal["not_sent", "outcome_unknown", "response_received"]


class ModelCallTrace(StrictModel):
    ledger_call_id: int
    reserved_microdollars: int
    request_state: RequestState = "not_sent"
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    accounting_state: Literal["reserved", "settled"] = "reserved"
    settled_microdollars: int | None = None


class RetrievedReference(StrictModel):
    evidence_id: str
    point_id: str
    similarity_score: float


class RunTrace(StrictModel):
    recall_number: str
    snapshot_id: str
    event_id: str | None = None
    archive_sha256: str | None = None
    collection: str
    embedding_model: str
    interpretation_model: str = "gpt-6-luna"
    sdk_retries: Literal[0] = 0
    max_output_tokens: int
    started_utc: str
    completed_utc: str | None = None
    elapsed_seconds: float = 0.0
    retrieval_seconds: float | None = None
    retrieved: list[RetrievedReference] = Field(default_factory=list)
    calls: list[ModelCallTrace] = Field(default_factory=list)
    accounting_available: bool = True
    model_attempts: int = 0
    repair_count: int = 0
    estimated_cost_usd: float | None = 0.0
    rate_basis: str = "Historical pilot estimate: USD 0.10/M input, 0.50/M output; not an invoice"

    def summarize(self) -> None:
        self.model_attempts = sum(call.request_state != "not_sent" for call in self.calls)
        self.repair_count = max(0, self.model_attempts - 1)
        if not self.accounting_available or any(call.accounting_state != "settled" for call in self.calls):
            self.estimated_cost_usd = None
        else:
            self.estimated_cost_usd = sum(call.settled_microdollars or 0 for call in self.calls) / 1_000_000


class RunRecorder:
    def __init__(self, run_id: str, trace: RunTrace):
        self.run_id = run_id
        self.trace = trace

    def reserved(self, call_id: int, amount: int):
        self.trace.calls.append(ModelCallTrace(ledger_call_id=call_id,
                                               reserved_microdollars=amount))

    def call(self, call_id: int) -> ModelCallTrace:
        return next(call for call in self.trace.calls if call.ledger_call_id == call_id)


active_run: ContextVar[RunRecorder | None] = ContextVar("a1_active_run", default=None)


def request_started(call_id: int):
    if recorder := active_run.get():
        # Before transport: a timeout or unexpected interruption has unknown outcome.
        recorder.call(call_id).request_state = "outcome_unknown"


def response_received(call_id: int, response):
    if recorder := active_run.get():
        call = recorder.call(call_id)
        call.request_state = "response_received"
        call.response_id = response.id
        if response.usage is not None:
            call.input_tokens = response.usage.input_tokens
            call.output_tokens = response.usage.output_tokens
            call.reasoning_tokens = getattr(response.usage.output_tokens_details, "reasoning_tokens", None)
