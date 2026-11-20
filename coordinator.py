"""Bounded A1-only LangGraph coordinator; no downstream agents or stock decisions."""

from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from openai import OpenAI

from a1_run import RunError, run_a1_with_trace
from case_state import CaseEvent, CaseRequest, CaseState
from fda_store import FDAStore
from group_c_contract import GroupCResult
from interpreter import Budget
from qdrant_a1 import QdrantA1
from validation import HumanLotApproval


def _event(name: str) -> CaseEvent:
    return CaseEvent(event=name, timestamp_utc=datetime.now(timezone.utc).isoformat())


class A1Coordinator:
    """Owns a compiled graph, while its caller owns clients, store and budget.

    Each run accepts a fresh CaseRequest, never injected prior outcomes. No
    checkpointer, graph retry policy, remote tracing or human approval is enabled.
    """

    def __init__(self, store: FDAStore, retriever: QdrantA1, client: OpenAI, budget: Budget, *,
                 approved_lots: tuple[HumanLotApproval, ...] = (), max_output_tokens: int = 4000):
        self.store, self.retriever, self.client, self.budget = store, retriever, client, budget
        self.approved_lots = approved_lots
        self.max_output_tokens = max_output_tokens
        graph = StateGraph(CaseState, input_schema=CaseRequest, output_schema=CaseState)
        graph.add_node("begin", self._begin)
        graph.add_node("interpret_a1", self._interpret)
        graph.add_node("complete", self._complete)
        graph.add_node("review", self._review)
        graph.add_node("stop", self._stop)
        graph.add_edge(START, "begin")
        graph.add_edge("begin", "interpret_a1")
        graph.add_conditional_edges("interpret_a1", self._route,
                                     {"complete": "complete", "review": "review", "stop": "stop"})
        for terminal in ("complete", "review", "stop"):
            graph.add_edge(terminal, END)
        self._graph = graph.compile()

    def run(self, request: CaseRequest | dict) -> CaseState:
        selected = CaseRequest.model_validate(request)
        # Do not export source-bearing graph state through ambient LangSmith settings.
        with tracing_context(enabled=False):
            output = self._graph.invoke(selected.model_dump(), config={"recursion_limit": 8})
        return CaseState.model_validate(output)

    @staticmethod
    def _begin(state: CaseState) -> dict:
        return {"status": "running", "events": [_event("started")]}

    def _interpret(self, state: CaseState) -> dict:
        try:
            envelope = run_a1_with_trace(
                self.store, self.retriever, self.client, self.budget,
                run_id=state.run_id, recall_number=state.recall_number,
                snapshot_id=state.snapshot_id, event_id=state.event_id,
                approved_lots=self.approved_lots, max_output_tokens=self.max_output_tokens)
        except Exception:
            # A crash may follow a chargeable call. Never fabricate a trace or retry it.
            error = RunError(stage="interpretation", code="coordinator_internal_failure",
                             message="A1 execution failed unexpectedly; request/accounting outcome requires review.",
                             request_state="outcome_unknown")
            return {"errors": [error], "events": state.events + [_event("a1_unexpected_failure")]}
        return {"a1": envelope, "errors": [envelope.error] if envelope.error else [],
                "events": state.events + [_event("a1_validated" if envelope.status == "validated" else "a1_unresolved")]}

    @staticmethod
    def _route(state: CaseState) -> str:
        if state.a1 is None or state.a1.status == "unresolved":
            return "stop"
        result = state.a1.result
        if isinstance(result, GroupCResult) or result.facts.uncertainties:
            return "review"
        return "complete"

    @staticmethod
    def _complete(state: CaseState) -> dict:
        return {"status": "a1_completed", "events": state.events + [_event("a1_completed")]}

    @staticmethod
    def _review(state: CaseState) -> dict:
        return {"status": "human_review", "review_reason": "A1 relationships or uncertainties require human review.",
                "events": state.events + [_event("human_review")]}

    @staticmethod
    def _stop(state: CaseState) -> dict:
        return {"status": "unresolved", "events": state.events + [_event("stopped")]}
