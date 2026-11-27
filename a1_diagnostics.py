"""Opt-in, run-local A1 proposal diagnostics; callers own private persistence.

These records contain untrusted model text. Never forward them as instructions
or publish them automatically. The default path retains no proposal diagnostics.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone


_failures: ContextVar[list | None] = ContextVar("a1_validation_failures", default=None)


@contextmanager
def capture_validation_failures():
    records = []
    token = _failures.set(records)
    try:
        yield records
    finally:
        _failures.reset(token)


def record_validation_failure(proposal, *, rule, details, context, response_id, ledger_call_id):
    records = _failures.get()
    if records is not None:
        records.append({
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "stage": "validation", "public_error_code": "citation_source_failed",
            "validation_rule": rule, "details": deepcopy(details),
            "context": dict(context), "response_id": response_id,
            "ledger_call_id": ledger_call_id, "rejected_proposal": proposal.model_dump(),
            "trusted": False,
        })
