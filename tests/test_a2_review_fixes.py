"""Regression tests for code-review fixes (batch, Group C relations, SQL lookup, reasons)."""

import ast
from pathlib import Path
import tempfile
import unittest

from a1_run import A1RunEnvelope
from a2_agent import _extract_a1_scope, run_a2
from group_c_contract import GroupCResult, RelationPart, SourceRelation
from inventory_loader import DEFAULT_INVENTORY_JSON, build_inventory_store
from inventory_match import RecallInventoryScope, compare_recall_to_inventory
from inventory_store import InventoryRow, InventoryStore
from models import Identifier
from test_a2_agent import _make_a1_envelope, _make_trace


def _batch_envelope(value: str) -> A1RunEnvelope:
    code = f"Batch #{value}"
    return _make_a1_envelope(
        recall_number="F-0882-2023", event_id="92215",
        product_name="Smoked Wahoo Dip, Net Wt. 8oz", code_info=code,
        identifiers=[Identifier(kind="batch", value=value, scope_note=code,
                                evidence_ids=["EV-F-0882-2023-CODE_INFO"])],
    )


class TestReviewFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.db = Path(cls._tmp.name) / "inv.sqlite"
        build_inventory_store(cls.db, json_path=DEFAULT_INVENTORY_JSON)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_batch_identifier_is_compared_to_lot_code(self) -> None:
        with InventoryStore(self.db) as store:
            # Real fixture: recall batch 2-401 vs inventory 2-402 -> explicit mismatch.
            self.assertEqual(run_a2(store, _batch_envelope("2-401")).status, "no_match")
            out = run_a2(store, _batch_envelope("2-402"))
        self.assertEqual(out.status, "matched")
        self.assertIn("lot_source:batch_identifier:2-402", out.findings[0].reason_codes)

    def test_group_c_lots_come_only_from_relations(self) -> None:
        base = _make_a1_envelope(
            recall_number="H-1361-2026", event_id="99611",
            product_name="Salsa Roja Medium. Net Wt: 12 oz.", code_info="Illinois: TFIC207, 8/7/2026",
            identifiers=[Identifier(kind="lot", value="IGNORED1", scope_note="x",
                                    evidence_ids=["EV-H-1361-2026-CODE_INFO"])],
            uncertainties=["review"],
        ).result

        def rel(kind, parts):
            return SourceRelation(kind=kind, evidence_id="EV-H-1361-2026-CODE_INFO", start=0, end=5,
                                  source_span="abcde", parts=[RelationPart(role=r, value=v) for r, v in parts])

        gc = GroupCResult(contract_version="0.2-group-c-provisional", base=base, relations=[
            rel("state_code_date", [("state", "Illinois"), ("code", "TFIC207"), ("date", "8/7/2026")]),
            rel("code_date", [("code", "TFIC209"), ("date", "8/9/2026")]),
            rel("date_range", [("range_start", "1/1/2026"), ("range_end", "2/1/2026")]),
        ])
        env = A1RunEnvelope(run_id="run-001", status="validated", result=gc, error=None,
                            trace=_make_trace("H-1361-2026", "99611"))
        scope, err, _ = _extract_a1_scope(env, case_id="c", run_id=None, recall_number=None,
                                          snapshot_id=None, event_id=None)
        self.assertIsNone(err)
        self.assertEqual(scope.lot_numbers, ("TFIC207", "TFIC209"))
        self.assertNotIn("IGNORED1", scope.lot_numbers)
        notes = dict(scope.source_notes)
        self.assertEqual(notes["TFIC207"], "lot_source:relation:state_code_date:Illinois:TFIC207|8/7/2026")
        self.assertEqual(notes["TFIC209"], "lot_source:relation:code_date:TFIC209|8/9/2026")

    def test_inventory_modules_import_no_llm_or_vector_clients(self) -> None:
        for name in ("inventory_match.py", "inventory_store.py", "inventory_loader.py"):
            tree = ast.parse((Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8"))
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            for mod in mods:
                self.assertFalse(mod.startswith(("openai", "qdrant", "a1_", "source")), (name, mod))

    def test_sql_lookup_filters_in_sqlite(self) -> None:
        with InventoryStore(self.db) as store:
            self.assertEqual([r.item_id for r in store.find_inventory_candidates(None, None, ("26078",), ())],
                             ["INV-001-A"])
            self.assertEqual([r.item_id for r in store.find_inventory_candidates(None, None, (), (), upcs=("8500 41392103",))],
                             ["INV-001-A"])
            self.assertEqual(store.find_inventory_candidates(None, None, ("26078",), (), candidate_item_ids=()), [])
            self.assertEqual(store.find_inventory_candidates(None, None, ("26078",), (), candidate_item_ids=("INV-003-A",)), [])
            self.assertEqual([r.item_id for r in store.find_inventory_candidates(None, None, ("060723",), ())],
                             ["INV-003-A"])
            self.assertEqual(store.find_inventory_candidates(None, None, ("60723",), ()), [])

    def test_blank_inventory_package_stays_partial_with_reason(self) -> None:
        scope = RecallInventoryScope(
            recall_number="H-0011-2027", snapshot_id="S", event_id="1",
            product_name="Donutful Chocolate Dipped Vanilla Cake Donuts 7.05oz",
            lot_numbers=("26078",), package_sizes=("7.05oz",))
        row = InventoryRow(inventory_set_id="S", item_id="X-A", retailer_id="r", store_id="s",
                           product_label="Donutful Chocolate Dipped Vanilla Cake Donuts", brand="", upc="",
                           lot_code="26078", package_size="", simulated_quantity=1, quantity_unit="packages",
                           inventory_reference_date="2026-01-01", source_type="SYNTHETIC",
                           synthetic_generation_note="")
        m = compare_recall_to_inventory(scope, row)
        self.assertEqual(m.match_status, "partial")
        self.assertIn("secondary_unknown:package_size", m.diagnostics.reason_codes)

    def test_duck_typed_store_and_missing_event(self) -> None:
        class Fake:
            snapshot_id = "FDA-FOOD-2026-10-23-USER-SNAPSHOT"

            def find_inventory_candidates(self, **_):
                return []

        self.assertEqual(run_a2(Fake(), _make_a1_envelope()).status, "no_match")
        self.assertEqual(run_a2(None, _make_a1_envelope()).error.code, "inventory_store_unavailable")


if __name__ == "__main__":
    unittest.main()
