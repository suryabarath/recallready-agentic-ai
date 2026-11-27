"""Record one live execution of each approved development case; never replay failures."""

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from a2_agent import run_a2
from a1_diagnostics import capture_validation_failures
from a3_agent import validate_plan_against_a2
from case_state import CaseState
from coordinator import A1Coordinator
from development_inventory import load_development_package
from fda_store import FDAStore
from group_c_contract import GroupCResult, validate_group_c_result
from interpreter import Budget
from inventory_loader import build_inventory_store
from inventory_store import InventoryStore
from qdrant_a1 import COLLECTION, MODEL, QdrantA1
from source import DEFAULT_ARCHIVE, DEVELOPMENT_RECORDS, FIELDS, GROUP_A, GROUP_B, Source
from validation import validate_result

LEDGER = ROOT / "runtime/a1_usage.sqlite"
PACKAGE = ROOT / "runtime/a2_development_18_v1"
FDA = ROOT / "runtime/fda_a1.sqlite"
ADDITIONAL_MICRODOLLARS = 50_000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_private(path, value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(raw)


def verify(state, source, inventory):
    """Revalidate saved contracts against ZIP authority and the same original inventory pair."""
    ctx = dict(recall_number=state.recall_number, event_id=state.event_id,
               snapshot_id=state.snapshot_id)
    envelopes = [e for e in (state.prior_a1, state.a1) if e is not None]
    retrieved = 0
    for envelope in envelopes:
        for ref in envelope.trace.retrieved:
            evidence = source.resolve(ref.evidence_id, **ctx)
            if evidence.point_id != ref.point_id:
                raise ValueError("Retrieved point differs from original ZIP")
        retrieved += len(envelope.trace.retrieved)
        if envelope.status == "validated":
            validator = validate_group_c_result if isinstance(envelope.result, GroupCResult) else validate_result
            validator(envelope.result.model_dump(), source, **ctx)
            if len(envelope.trace.retrieved) != 4:
                raise ValueError("Validated A1 lacks four retrieved passages")
    for a1, a2, a3 in ((state.a1, state.a2, state.a3),
                       (state.prior_a1 or state.a1, state.prior_a2, state.prior_a3)):
        if a2 is not None:
            replay = run_a2(inventory, a1, case_id=state.case_id, run_id=state.run_id, **ctx)
            if replay != a2:
                raise ValueError("A2 differs from fresh SQLite replay")
        if a3 is not None:
            validate_plan_against_a2(a3, a2 or state.a2)
    if state.a3 is not None and state.status == "human_review" and not state.a3.requires_human_review:
        raise ValueError("Human review boundary missing")
    return retrieved


def case_calls(state, budget):
    traces = [e.trace for e in (state.prior_a1, state.a1, state.prior_a4, state.a4) if e is not None]
    calls = [call for trace in traces for call in trace.calls]
    ids = [call.ledger_call_id for call in calls]
    with sqlite3.connect(LEDGER.as_uri() + "?mode=ro", uri=True) as db:
        linked = [r[0] for r in db.execute("SELECT call_id FROM run_calls WHERE run_id=?", (state.run_id,))]
    if sorted(ids) != sorted(linked) or len(ids) != len(set(ids)):
        raise ValueError("Trace/ledger identity mismatch")
    by_id = {row["call_id"]: row for row in budget.summary()}
    for call in calls:
        row = by_id[call.ledger_call_id]
        if call.accounting_state == "settled":
            for field in ("response_id", "input_tokens", "output_tokens", "reasoning_tokens"):
                if getattr(call, field) != row[field]:
                    raise ValueError("Trace/ledger usage mismatch")
    return [by_id[i] for i in ids]


def make_report(summary):
    rows = summary["cases"]
    lines = ["# RecallReady — Live End-to-End Development Verification", "",
        "## 1. Executive assessment", "",
        f"Run: `{summary['batch_id']}`. Completed: {summary['completed_utc']} (UTC).",
        f"Executed **{len(rows)} of {summary['selected_record_count']}** selected development recalls against live Qdrant and OpenAI.",
        f"Final statuses: **{dict(Counter(r['status'] for r in rows))}**.",
        "A human-review outcome is an intentional workflow boundary, not stock clearance.", "",
        "## 2. Reproducibility and scope", "",
        f"Application base commit: `{summary['git_commit']}` on `{summary['git_branch']}`.",
        "Local working changes, when present, are fingerprinted in summary.json; the base commit alone does not identify them.",
        f"Runner SHA-256: `{summary['runner_sha256']}`.",
        f"Start: {summary['started_utc']}; elapsed: {summary['elapsed_seconds']:.2f} seconds.",
        "Selected cases use the original FDA 18-record ZIP and the approved 18-set/36-row synthetic inventory subset.",
        "Each execution receives only its original two-row inventory set. All four stages, the live A4 semantic critic,",
        "and bounded targeted corrections are enabled. Existing A1/A2 review gates determine downstream execution.",
        "No prior case-specific human lot approvals are injected; the default conservative ambiguity policy applies.",
        "A2 and A3 execute locally. A1 interpretation and eligible A4 semantic audits use live OpenAI requests.",
        f"Model: `gpt-6-luna`; SDK retries: 0; request timeout: 60 seconds. Collection: `{COLLECTION}`.",
        f"Embedding model: `{MODEL}`. No fixture model or vector responses are used.", "",
        "## 3. Method and verification", "",
        "1. Verify source/package checksums, development membership, FDA store identity and all 72 exact passages.",
        "2. Run each selected case once through the compiled A1–A4 coordinator, preserving ordinary errors and review stops.",
        "3. Save each complete state immediately; reload through CaseState validation.",
        "4. Revalidate accepted A1 facts against the ZIP, retrieved evidence/point IDs, A2 against SQLite replay, and A3 against A2.",
        "5. Match every model trace to run-linked ledger entries, response IDs and token usage.",
        "6. Verify unchanged FDA/source/inventory bytes and create a SHA-256 artifact manifest.", "",
        "## 4. Per-record results", "",
        "| Group | Recall | Final status | A1 | A2 | A3 | A4 | Semantic requests | Revisions | Errors |",
        "|---|---|---|---|---|---|---|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r['group']} | {r['recall_number']} | {r['status']} | {r['a1_status']} | {r['a2_status']} | {r['a3_status']} | {r['a4_verdict']} | {r['a4_requests']} | {r['revision_count']} | {r['errors'] or 'none'} |")
    lines += ["", "## 5. Coverage and accounting", "",
        f"A1 validated: {sum(r['a1_status']=='validated' for r in rows)}/{len(rows)}.",
        f"A2 reached: {sum(r['a2_status']!='not_run' for r in rows)}; A3 reached: {sum(r['a3_status']!='not_run' for r in rows)}; A4 reached: {sum(r['a4_verdict']!='not_run' for r in rows)}.",
        f"Model requests recorded: {summary['new_ledger_calls']}; input tokens: {summary['input_tokens']}; output tokens: {summary['output_tokens']}.",
        f"Reasoning tokens (already included in output): {summary['reasoning_tokens']}.",
        f"Estimated OpenAI usage for this batch: **USD {summary['new_estimated_usd']:.6f}**.",
        f"Cumulative ledger: USD {summary['cumulative_estimated_usd']:.6f}; local ceiling: USD {summary['cumulative_limit_usd']:.6f}.",
        "Estimates use USD 0.10/million input and USD 0.50/million output, rounded up per request.",
        "These are local accounting estimates, not invoices or provider spending limits. Qdrant fees and taxes are excluded.", "",
        "## 6. Interpretation and limitations", "",
        "This is development-set execution and contract/source verification, not an independent accuracy benchmark.",
        "Review-gated cases are intentionally not forced through A2–A4. No-match does not mean stock is safe.",
        "Source-valid outputs can still contain semantic omissions or interpretation errors; source checks do not prove completeness.",
        "Unresolved cases, if any, remain failures requiring investigation; they are not counted as successful interpretations.",
        f"Total workflow corrections observed: {sum(r['revision_count'] for r in rows)}. Correction flags alone do not establish correction-path coverage.",
        "No stock action, durable human approval/resumption, independent held-out evaluation or production deployment is verified.",
        "The previously recorded 1,159 regression tests and 75 development checks are separate offline evidence, not this live run's accuracy score.",
        f"Stop reason: {summary['stop_reason'] or 'none; all selected records attempted'}.", "",
        "## 7. Evaluator artifact guide", "",
        "- `cases/<recall>.json`: complete typed state, facts, identifiers, relationships, findings, plans, audits, errors and event trace.",
        "- `results.csv`: sortable per-record stage, timing, usage and error outcomes.",
        "- `summary.json`: batch settings, input hashes, usage and results.",
        "- `ledger_calls.json`: this batch's run-linked response IDs and token accounting.",
        "- `manifest.json`: checksums for the evidence files and this report.",
        "- `run_live_development_18.py`: exact runner copy used for this execution.",
        "Credentials and the private usage-ledger database are excluded. The artifact directory is private and Git-ignored.",
        "For reproduction, provision the source ZIP, selected inventory, FDA store, existing ledger and private environment variables;",
        "then run `python -B scripts/run_live_development_18.py --output runtime/<new-directory>` from the repository root.",
        "Rerunning makes new paid requests. The runner refuses to overwrite an existing output directory.", "",
        "## 8. Input provenance", ""]
    lines += [f"- `{name}` — SHA-256 `{value}`" for name, value in summary['input_sha256'].items()]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--recall", choices=DEVELOPMENT_RECORDS, help="Execute only this development record")
    parser.add_argument("--capture-validation-failures", action="store_true", help="Save rejected A1 proposals privately")
    args = parser.parse_args()
    os.chdir(ROOT)
    for name in ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY"):
        if not os.environ.get(name):
            raise RuntimeError("Missing private environment variable: " + name)
    if args.output.exists():
        raise ValueError("Refusing to overwrite output directory")
    source = Source()
    payload, cases, _ = load_development_package(PACKAGE, source)
    if args.recall:
        cases = [case for case in cases if case["recall_number"] == args.recall]
    inputs = [DEFAULT_ARCHIVE, FDA, PACKAGE / "inventory_development.json",
              PACKAGE / "cases_development.json", PACKAGE / "manifest.json"]
    hashes = {str(p.relative_to(ROOT.parent)): digest(p) for p in inputs}
    budget = Budget(LEDGER, 1_000_000)
    before = budget.summary()
    if any(row.get("state") == "reserved" for row in before):
        raise RuntimeError("Unsettled reservation; do not send new requests")
    starting_charge = sum(round(row["accounted_usd"] * 1_000_000) for row in before)
    additional = 5_000 if args.recall else ADDITIONAL_MICRODOLLARS
    budget = Budget(LEDGER, starting_charge + additional)
    with FDAStore(FDA) as store:
        if store.snapshot_id != source.snapshot_id or store.archive_sha256 != digest(DEFAULT_ARCHIVE):
            raise ValueError("FDA source identity differs")
        for recall in DEVELOPMENT_RECORDS:
            ctx = dict(recall_number=recall, snapshot_id=source.snapshot_id)
            record = source.lookup(**ctx)
            if store.lookup(**ctx) != record:
                raise ValueError("FDA record differs from ZIP")
            for field in FIELDS:
                evidence_id = f"EV-{recall}-{field.upper()}"
                if store.resolve(evidence_id, event_id=record["event_id"], **ctx) != source.resolve(evidence_id, event_id=record["event_id"], **ctx):
                    raise ValueError("FDA passage differs from ZIP")
        print(json.dumps({"preflight": "passed", "records": 18, "passages": 72,
                          "selected_records": len(cases), "ledger_calls_before": len(before),
                          "additional_estimated_usd": additional / 1_000_000}), flush=True)
        if args.preflight_only:
            return
        args.output.mkdir(mode=0o700, parents=True)
        (args.output / "cases").mkdir(mode=0o700)
        write_private(args.output / "run_live_development_18.py", Path(__file__).read_text())
        (args.output / "application_sources").mkdir(mode=0o700)
        for name in ("a1_diagnostics.py", "interpreter.py", "validation.py"):
            write_private(args.output / "application_sources" / name, (ROOT / name).read_text())
        started = datetime.now(timezone.utc).isoformat()
        clock = time.perf_counter()
        batch_id = "live18-" + str(uuid4())
        results, all_calls, stop = [], [], None
        with OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="https://api.openai.com/v1", max_retries=0, timeout=60) as client:
            for case in cases:
                recall = case["recall_number"]
                run_id = batch_id + "-" + recall
                print("START " + recall, flush=True)
                elapsed = time.perf_counter()
                rows = [r for r in payload["records"] if r["inventory_set_id"] == case["inventory_set_id"]]
                with TemporaryDirectory(prefix="recallready-live18-", dir=ROOT / "runtime") as tmp, ExitStack() as stack:
                    failures = stack.enter_context(capture_validation_failures()) if args.capture_validation_failures else []
                    selected = Path(tmp) / "inventory.json"
                    write_private(selected, dict(payload, records=rows))
                    db = Path(tmp) / "inventory.sqlite"
                    build_inventory_store(db, json_path=selected, expected_set_count=1, expected_record_count=2)
                    original_db = digest(db)
                    inventory = stack.enter_context(InventoryStore(db))
                    state = A1Coordinator(store, QdrantA1(os.environ["QDRANT_URL"], os.environ["QDRANT_API_KEY"], store),
                        client, budget, inventory_store=inventory, enable_a3=True, enable_a4=True,
                        enable_a4_llm=True, enable_targeted_corrections=True).run({
                            "case_id": case["case_id"], "run_id": run_id, "recall_number": recall,
                            "event_id": case["event_id"], "snapshot_id": case["snapshot_id"]})
                    write_private(args.output / "cases" / (recall + ".json"), state.model_dump(mode="json"))
                    if args.capture_validation_failures:
                        write_private(args.output / "cases" / (recall + ".diagnostics.json"), failures)
                    state = CaseState.model_validate_json((args.output / "cases" / (recall + ".json")).read_text())
                    retrieved = verify(state, source, inventory)
                    if digest(db) != original_db:
                        raise ValueError("Inventory database changed")
                calls = case_calls(state, budget)
                all_calls.extend(dict(run_id=run_id, **r) for r in calls)
                a4s = [e for e in (state.prior_a4, state.a4) if e is not None]
                item = dict(group="A" if recall in GROUP_A else "B" if recall in GROUP_B else "C",
                    recall_number=recall, case_id=case["case_id"], inventory_set_id=case["inventory_set_id"],
                    run_id=run_id, status=state.status, a1_status=state.a1.status if state.a1 else "not_run",
                    a2_status=state.a2.status if state.a2 else "not_run", a3_status=state.a3.status if state.a3 else "not_run",
                    a4_verdict=state.a4.verdict if state.a4 else "not_run", a4_requests=sum(e.trace.model_attempts for e in a4s),
                    revision_count=state.revision_count, errors=",".join(e.code for e in state.errors),
                    elapsed_seconds=round(time.perf_counter()-elapsed, 3), retrieved_references=retrieved,
                    model_requests=len(calls), input_tokens=sum(r.get("input_tokens", 0) for r in calls),
                    output_tokens=sum(r.get("output_tokens", 0) for r in calls),
                    estimated_usd=sum(r["accounted_usd"] for r in calls), verification="passed")
                results.append(item)
                write_private(args.output / "cases" / (recall + ".result.json"), item)
                print(json.dumps(item), flush=True)
                if any(r.get("state") == "reserved" for r in calls) or "budget_exhausted" in item["errors"]:
                    stop = "Unsettled reservation or budget exhausted; further requests stopped"
                    break
        for path in inputs:
            if digest(path) != hashes[str(path.relative_to(ROOT.parent))]:
                raise ValueError("Immutable input changed")
        after = budget.summary()
        new = after[len(before):]
        if {r["call_id"] for r in new} != {r["call_id"] for r in all_calls}:
            raise ValueError("Concurrent or unattributed ledger calls detected")
        summary = dict(batch_id=batch_id, started_utc=started, completed_utc=datetime.now(timezone.utc).isoformat(),
            selected_record_count=len(cases), validation_diagnostics_enabled=args.capture_validation_failures,
            elapsed_seconds=time.perf_counter()-clock,
            git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            git_branch=subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
            runner_sha256=digest(__file__), input_sha256=hashes, cases=results, stop_reason=stop,
            application_sha256={p.name: digest(p) for p in sorted(ROOT.glob("*.py"))},
            local_tracked_changes=subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines(),
            new_ledger_calls=len(new), new_estimated_usd=sum(r["accounted_usd"] for r in new),
            cumulative_estimated_usd=sum(r["accounted_usd"] for r in after), cumulative_limit_usd=budget.limit/1_000_000,
            input_tokens=sum(r.get("input_tokens", 0) for r in new), output_tokens=sum(r.get("output_tokens", 0) for r in new),
            reasoning_tokens=sum(r.get("reasoning_tokens") or 0 for r in new))
        write_private(args.output / "summary.json", summary)
        write_private(args.output / "ledger_calls.json", all_calls)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
        write_private(args.output / "results.csv", buffer.getvalue())
        write_private(args.output / "REPORT.md", make_report(summary))
        manifest = {str(p.relative_to(args.output)): digest(p) for p in sorted(args.output.rglob("*")) if p.is_file()}
        write_private(args.output / "manifest.json", manifest)
        print(json.dumps({"output": str(args.output), "attempted": len(results), "estimated_usd": summary["new_estimated_usd"], "stop_reason": stop}), flush=True)


if __name__ == "__main__":
    main()
