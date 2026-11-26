"""One controlled live development case with targeted corrections enabled.

Run from code_workspace after privately loading .env. Writes only to ignored
runtime storage. Does not inject a fault or guarantee a correction occurs.
"""

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from case_state import CaseState
from coordinator import A1Coordinator
from development_inventory import load_development_package
from fda_store import FDAStore
from inventory_loader import build_inventory_store
from inventory_store import InventoryStore
from interpreter import Budget
from qdrant_a1 import QdrantA1
from source import Source


RECALL = "H-0011-2027"
LEDGER = Path("runtime/a1_usage.sqlite")
CAP_MICRODOLLARS = 20_000  # Existing cumulative ledger plus this run: $0.02.


def save_private(path: Path, value: object) -> None:
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)


def main() -> None:
    for name in ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"Missing {name}; load private environment before running")
    source = Source()
    package, cases, manifest = load_development_package(Path("runtime/a2_development_18_v1"), source)
    case = next(row for row in cases if row["recall_number"] == RECALL)
    rows = [row for row in package["records"] if row["inventory_set_id"] == case["inventory_set_id"]]
    if len(rows) != 2 or case["dataset_split"] != "development":
        raise RuntimeError("Selected development case must have its original inventory pair")
    if case["case_id"] != "CASE-001" or case["inventory_set_id"] != "SIMSET-001":
        raise RuntimeError("Selected case differs from approved pilot input")
    budget = Budget(LEDGER, CAP_MICRODOLLARS)
    before = budget.summary()
    if any(row.get("state") == "reserved" for row in before):
        raise RuntimeError("Existing unsettled reservation requires review before a live request")
    with ExitStack() as stack:
        store = stack.enter_context(FDAStore(Path("runtime/fda_a1.sqlite")))
        if store.snapshot_id != source.snapshot_id or store.archive_sha256 != hashlib.sha256(
                Path("../project_reference/RecallReady_Agent1_FDA_18_Starter.zip").read_bytes()).hexdigest():
            raise RuntimeError("FDA store/source identity differs")
        with tempfile.TemporaryDirectory(prefix="recallready-correction-live-", dir="runtime") as temporary, ExitStack() as run_stack:
            selected_json = Path(temporary) / "selected.json"
            save_private(selected_json, dict(package, records=rows))
            db = Path(temporary) / "selected.sqlite"
            build_inventory_store(db, json_path=selected_json, expected_set_count=1, expected_record_count=2)
            db_hash = hashlib.sha256(db.read_bytes()).hexdigest()
            inventory = run_stack.enter_context(InventoryStore(db))
            retriever = QdrantA1(os.environ["QDRANT_URL"], os.environ["QDRANT_API_KEY"], store)
            client = run_stack.enter_context(OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1", max_retries=0, timeout=60))
            run_id = "live-corrections-" + str(uuid4())
            state = A1Coordinator(store, retriever, client, budget,
                inventory_store=inventory, enable_a3=True, enable_a4=True,
                enable_a4_llm=True, enable_targeted_corrections=True).run({
                    "case_id": case["case_id"], "run_id": run_id,
                    "recall_number": RECALL, "snapshot_id": case["snapshot_id"],
                    "event_id": case["event_id"],
                })
            if hashlib.sha256(db.read_bytes()).hexdigest() != db_hash:
                raise RuntimeError("Inventory SQLite bytes changed during live run")
    state = CaseState.model_validate_json(state.model_dump_json())
    after = budget.summary()
    new_calls = after[len(before):]
    directory = Path("runtime") / ("a1_a4_corrections_live_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(mode=0o700)
    save_private(directory / "state.json", state.model_dump(mode="json"))
    save_private(directory / "summary.json", {
        "run_id": state.run_id, "case_id": state.case_id, "recall_number": state.recall_number,
        "status": state.status, "events": [event.event for event in state.events],
        "a1_status": state.a1.status if state.a1 else None,
        "a2_status": state.a2.status if state.a2 else None,
        "a3_status": state.a3.status if state.a3 else None,
        "a4_verdict": state.a4.verdict if state.a4 else None,
        "correction_count": state.revision_count,
        "semantic_critic_enabled": True, "targeted_corrections_enabled": True,
        "new_ledger_calls": len(new_calls),
        "new_estimated_usd": sum(item["accounted_usd"] for item in new_calls),
        "state_sha256": hashlib.sha256((directory / "state.json").read_bytes()).hexdigest(),
        "development_manifest_sha256": hashlib.sha256(Path("runtime/a2_development_18_v1/manifest.json").read_bytes()).hexdigest(),
    })
    print(json.dumps({"artifact_dir": str(directory), "status": state.status,
        "a2_status": state.a2.status if state.a2 else None,
        "a4_verdict": state.a4.verdict if state.a4 else None,
        "correction_count": state.revision_count, "new_ledger_calls": len(new_calls),
        "new_estimated_usd": sum(item["accounted_usd"] for item in new_calls)}))


if __name__ == "__main__":
    main()
