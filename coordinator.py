"""Bounded A1-A4 workflow; all proposed actions retain human review."""

from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from openai import OpenAI

from a1_run import RunError, run_a1_with_trace
from a2_agent import A2Error, run_a2
from a3_agent import A3Error, plan_response, validate_plan_against_a2
from a4_agent import A4RunEnvelope, run_a4
from a4_checks import A4Error
from case_state import CaseEvent, CaseRequest, CaseState
from corrections import build_correction
from fda_store import FDAStore
from group_c_contract import GroupCResult
from interpreter import Budget
from inventory_store import InventoryStore
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
                 approved_lots: tuple[HumanLotApproval, ...] = (), max_output_tokens: int = 4000,
                 inventory_store: InventoryStore | None = None, enable_a3: bool = False,
                 enable_a4: bool = False, enable_a4_llm: bool = False,
                 enable_targeted_corrections: bool = False):
        if type(enable_a3) is not bool or (enable_a3 and inventory_store is None):
            raise ValueError("A3 requires an inventory store and a boolean enable_a3 flag")
        self.enable_a3 = enable_a3
        if type(enable_a4) is not bool or type(enable_a4_llm) is not bool:
            raise ValueError("A4 flags must be boolean")
        if (enable_a4 and not enable_a3) or (enable_a4_llm and not enable_a4):
            raise ValueError("A4 requires A3; its model flag requires A4")
        self.enable_a4_llm = enable_a4_llm
        if type(enable_targeted_corrections) is not bool or (enable_targeted_corrections and not enable_a4):
            raise ValueError("Targeted corrections require A4 and a boolean flag")
        self.enable_targeted_corrections = enable_targeted_corrections
        self.store, self.retriever, self.client, self.budget = store, retriever, client, budget
        self.approved_lots = approved_lots
        self.max_output_tokens = max_output_tokens
        self.inventory_store = inventory_store
        graph = StateGraph(CaseState, input_schema=CaseRequest, output_schema=CaseState)
        graph.add_node("begin", self._begin)
        graph.add_node("interpret_a1", self._interpret)
        graph.add_node("complete", self._complete)
        graph.add_node("review", self._review)
        graph.add_node("stop", self._stop)
        graph.add_edge(START, "begin")
        graph.add_edge("begin", "interpret_a1")
        routes = {"complete": "complete", "review": "review", "stop": "stop"}
        terminals = ["complete", "review", "stop"]
        if inventory_store is not None:
            if enable_a3:
                if enable_a4:
                    graph.add_node("audit_a4", self._audit_a4)
                    graph.add_conditional_edges("audit_a4", lambda state: "stop" if state.errors else "review",
                                                {"stop": "stop", "review": "review"})
                graph.add_node("plan_a3", self._plan_a3)
                graph.add_conditional_edges("plan_a3", lambda state: "review" if state.a3 else "stop",
                                            {"review": "audit_a4" if enable_a4 else "review", "stop": "stop"})
            graph.add_node("investigate_a2", self._investigate_a2)
            graph.add_node("a2_complete", self._a2_complete)
            graph.add_conditional_edges("investigate_a2", self._after_a2,
                                        {"complete": "plan_a3" if enable_a3 else "a2_complete",
                                         "review": "review", "stop": "stop"})
            routes["investigate_a2"] = "investigate_a2"
            terminals.append("a2_complete")
        graph.add_conditional_edges("interpret_a1", self._route, routes)
        for terminal in terminals:
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
        return self._interpret_a1(state)

    def _interpret_a1(self, state: CaseState, *, original_result=None,
                      correction_evidence_ids=()) -> dict:
        try:
            envelope = run_a1_with_trace(
                self.store, self.retriever, self.client, self.budget,
                run_id=state.run_id, recall_number=state.recall_number,
                snapshot_id=state.snapshot_id, event_id=state.event_id,
                approved_lots=self.approved_lots, max_output_tokens=self.max_output_tokens,
                original_result=original_result, correction_evidence_ids=correction_evidence_ids)
            # Reject a malformed handoff inside this failure boundary. Returning
            # it would make graph-state coercion raise before the saved audit
            # and conservative failure outcome could reach the caller.
            CaseState.model_validate(state.model_dump() | {
                "a1": envelope, "errors": [envelope.error] if envelope.error else []})
        except Exception:
            # A crash may follow a chargeable call. Never fabricate a trace or retry it.
            error = RunError(stage="interpretation", code="coordinator_internal_failure",
                             message="A1 execution failed unexpectedly; request/accounting outcome requires review.",
                             request_state="outcome_unknown")
            return {"errors": [error], "events": state.events + [_event("a1_unexpected_failure")]}
        return {"a1": envelope, "errors": [envelope.error] if envelope.error else [],
                "events": state.events + [_event("a1_validated" if envelope.status == "validated" else "a1_unresolved")]}

    def _route(self, state: CaseState) -> str:
        if state.a1 is None or state.a1.status == "unresolved":
            return "stop"
        result = state.a1.result
        if isinstance(result, GroupCResult) or result.facts.uncertainties:
            return "review"
        return "investigate_a2" if self.inventory_store is not None else "complete"

    def _investigate_a2(self, state: CaseState) -> dict:
        try:
            result = run_a2(
                self.inventory_store, state.a1, case_id=state.case_id,
                run_id=state.run_id, recall_number=state.recall_number,
                snapshot_id=state.snapshot_id, event_id=state.event_id)
            CaseState.model_validate(state.model_dump() | {
                "a2": result, "errors": [result.error] if result.error else []})
        except Exception:
            error = A2Error(code="inventory_match_failed",
                            message="A2 failed unexpectedly; review required before rerunning.")
            return {"errors": [error],
                    "events": state.events + [_event("a2_unexpected_failure")]}
        return {"a2": result, "errors": [result.error] if result.error else [],
                "events": state.events + [_event("a2_" + result.status)]}

    @staticmethod
    def _after_a2(state: CaseState) -> str:
        if state.a2 is None or state.a2.status == "unresolved":
            return "stop"
        return "review" if state.a2.requires_human_review else "complete"

    def _plan_a3(self, state: CaseState) -> dict:
        try:
            plan = plan_response(state.a2)
            validate_plan_against_a2(plan, state.a2)
            CaseState.model_validate(state.model_dump() | {"a3": plan})
        except Exception:
            error = A3Error(message="A3 planning failed; inspect the case before rerunning.")
            return {"errors": [error], "events": state.events + [_event("a3_unexpected_failure")]}
        return {"a3": plan, "events": state.events + [_event("a3_planned")]}

    @staticmethod
    def _a2_complete(state: CaseState) -> dict:
        return {"status": "a2_completed", "events": state.events + [_event("a2_completed")]}

    def _audit_a4(self, state: CaseState) -> dict:
        updates = {}
        events = list(state.events)
        try:
            def snapshot(**changes):
                return CaseState.model_validate(state.model_dump() | updates | changes)

            def audit(plan, revision_round):
                current = snapshot(a3=plan)
                result = run_a4(
                    self.store, self.inventory_store, current.a1, current.a2, plan,
                    case_id=state.case_id, run_id=state.run_id, recall_number=state.recall_number,
                    snapshot_id=state.snapshot_id, event_id=current.a2.event_id,
                    revision_round=revision_round, client=self.client, budget=self.budget,
                    enable_llm_critic=self.enable_a4_llm, approved_lots=self.approved_lots,
                    enable_upstream_corrections=self.enable_targeted_corrections)
                result = A4RunEnvelope.model_validate(result.model_dump())
                snapshot(a3=plan, a4=result, errors=[result.error] if result.error else [])
                return result

            critic = audit(state.a3, 0)
            updates["a4"] = critic
            events.append(_event("a4_" + critic.verdict))
            correction = build_correction(critic, state.a1, case_id=state.case_id,
                run_id=state.run_id, recall_number=state.recall_number,
                snapshot_id=state.snapshot_id, enable_upstream=self.enable_targeted_corrections)
            if correction is not None:
                # Preserve the completed audit and consume the single replay
                # attempt before planning; a failed replay must retain both.
                updates = {"a4": None, "prior_a4": critic, "prior_a3": state.a3,
                           "revision_count": 1, "correction": correction}
                events.append(_event("revision_replay_started"))
                if correction.target_agent in ("a1", "a2"):
                    updates.update(prior_a1=state.a1, prior_a2=state.a2, a2=None, a3=None)
                    if correction.target_agent == "a1":
                        updates["a1"] = None
                        updates.update(self._interpret_a1(snapshot(events=events),
                            original_result=state.a1.result,
                            correction_evidence_ids=tuple(correction.evidence_ids)))
                        events = updates.pop("events")
                        if self._route(snapshot()) != "investigate_a2":
                            return updates | {"events": events}
                    updates.update(self._investigate_a2(snapshot(events=events)))
                    events = updates.pop("events")
                    if self._after_a2(snapshot()) != "complete":
                        return updates | {"events": events}
                    updates.update(self._plan_a3(snapshot(events=events)))
                    events = updates.pop("events")
                    if updates.get("a3") is None:
                        return updates | {"events": events}
                    plan = updates["a3"]
                else:
                    plan = plan_response(state.a2)
                    validate_plan_against_a2(plan, state.a2)
                    updates["a3"] = plan
                    events.append(_event("a3_replanned"))
                critic = audit(plan, 1)
                events.append(_event("a4_" + critic.verdict))
            updates.update(a4=critic, errors=[critic.error] if critic.error else [], events=events)
        except Exception:
            error = A4Error(stage="coordinator", code="critic_internal_failure",
                            message="A4 execution failed; inspect accounting before rerunning.",
                            request_state="outcome_unknown" if self.enable_a4_llm else "not_sent")
            updates.update(errors=[error], events=events + [_event("a4_unexpected_failure")])
        return updates

    @staticmethod
    def _complete(state: CaseState) -> dict:
        return {"status": "a1_completed", "events": state.events + [_event("a1_completed")]}

    @staticmethod
    def _review(state: CaseState) -> dict:
        reason = ("A4 audit requires human review; inspect findings and any revision request." if state.a4 is not None else
                  "A3 proposed actions require human review." if state.a3 is not None else
                  "A2 partial inventory findings require human review."
                  if state.a2 is not None else "A1 relationships or uncertainties require human review.")
        return {"status": "human_review", "review_reason": reason,
                "events": state.events + [_event("human_review")]}

    @staticmethod
    def _stop(state: CaseState) -> dict:
        return {"status": "unresolved", "events": state.events + [_event("stopped")]}
