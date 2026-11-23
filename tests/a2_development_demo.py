"""Create inspectable offline A1-to-A2 demonstration artifacts.

This is a development demonstration, not a production or accuracy runner.
Qdrant and OpenAI responses come from reviewed test fixtures; all local source,
citation, coordinator, SQLite inventory, A2 matching and state validation code
executes normally.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from case_state import CaseState
from coordinator import A1Coordinator
from development_inventory import load_development_package
from fda_store import FDAStore, build_fda_store
from interpreter import Budget
from inventory_loader import build_inventory_store
from inventory_store import InventoryStore
from test_a1_service import fixture_output, points_for, retriever_for
from test_interpreter import client_for


DEMO_CASES = {
    "matched": "H-0011-2027",
    "no_match": "F-0818-2023",
    "human_review": "H-1388-2026",
}


def _write_private(path: Path, value: object) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


def create_demo(package_dir: Path, output_dir: Path, *, enable_a3: bool = False) -> dict:
    """Run three offline routes and save their complete validated states."""
    package_dir, output_dir = Path(package_dir), Path(output_dir)
    if output_dir.exists():
        raise ValueError("Refusing to overwrite an existing demonstration directory")
    payload, cases, package_manifest = load_development_package(package_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    files: dict[str, str] = {}
    summaries = []
    with TemporaryDirectory(prefix="recallready-a1-a2-demo-") as temporary:
        temporary = Path(temporary)
        fda_db = temporary / "fda.sqlite"
        build_fda_store(fda_db)
        with FDAStore(fda_db) as source_store:
            for route, recall in DEMO_CASES.items():
                case = next(item for item in cases if item["recall_number"] == recall)
                rows = [row for row in payload["records"]
                        if row["inventory_set_id"] == case["inventory_set_id"]]
                inventory_json = temporary / f"{route}-inventory.json"
                inventory_json.write_text(
                    json.dumps(dict(payload, records=rows)), encoding="utf-8")
                inventory_db = temporary / f"{route}-inventory.sqlite"
                build_inventory_store(inventory_db, json_path=inventory_json,
                                      expected_set_count=1, expected_record_count=2)
                proposal, _ = fixture_output(source_store, recall)
                qdrant_calls, model_calls = [], []
                retriever = retriever_for(
                    source_store, points_for(source_store, recall), qdrant_calls)
                with InventoryStore(inventory_db) as inventory:
                    with client_for([(json.dumps(proposal), "completed")], model_calls) as client:
                        state = A1Coordinator(
                            source_store, retriever, client,
                            Budget(temporary / f"{route}-usage.sqlite"),
                            inventory_store=inventory, enable_a3=enable_a3,
                        ).run({
                            "case_id": case["case_id"],
                            "run_id": f"offline-demo-{recall}",
                            "recall_number": recall,
                            "snapshot_id": case["snapshot_id"],
                            "event_id": case["event_id"],
                        })
                state = CaseState.model_validate_json(state.model_dump_json())
                filename = f"{route}_{recall}.json"
                files[filename] = _write_private(output_dir / filename, state.model_dump(mode="json"))
                summaries.append({
                    "route": route,
                    "recall_number": recall,
                    "case_id": case["case_id"],
                    "inventory_set_id": case["inventory_set_id"],
                    "inventory_rows_supplied": len(rows),
                    "case_status": state.status,
                    "a1_status": state.a1.status if state.a1 else None,
                    "a2_status": state.a2.status if state.a2 else "not_run_requires_A1_review",
                    "a3_status": state.a3.status if state.a3 else "not_run",
                    "finding_count": len(state.a2.findings) if state.a2 else 0,
                    "simulated_qdrant_requests": len(qdrant_calls),
                    "simulated_openai_requests": len(model_calls),
                    "state_file": filename,
                })
    summary = {
        "demonstration": "RecallReady offline A1-to-A2 representative routes",
        "network_mode": "simulated Qdrant and OpenAI fixture responses",
        "a3_enabled": enable_a3,
        "local_components_executed": [
            "FDA source and citation validation", "coordinator routing",
            "case-scoped SQLite inventory", "A2 matching", "CaseState validation",
        ],
        "development_package_sha256": package_manifest["files"],
        "cases": summaries,
    }
    files["summary.json"] = _write_private(output_dir / "summary.json", summary)
    manifest = {
        "version": "1.0.0",
        "network_mode": "offline fixtures; no external requests",
        "case_count": len(summaries),
        "files": files,
    }
    _write_private(output_dir / "manifest.json", manifest)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--development-package", type=Path,
        default=ROOT / "runtime" / "a2_development_18_v1",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enable-a3", action="store_true", help="Include deterministic A3 review planning")
    args = parser.parse_args(argv)
    summary = create_demo(args.development_package, args.output, enable_a3=args.enable_a3)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
