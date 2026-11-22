"""Acceptance tests for inventory_loader.py (Items 22, 23, 30)."""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from inventory_loader import (
    DEFAULT_INVENTORY_JSON,
    INVENTORY_COLUMNS,
    InventoryLoadError,
    build_inventory_store,
)


class TestInventoryLoader(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_loads_exact_48_sets_and_96_rows_with_a_and_b_pairs(self) -> None:
        """Items 22, 23, 30: Attached JSON loader creates 48 sets and 96 rows; 1 *-A and 1 *-B per set."""
        db_path = self.tmp_dir / "retailer_inventory.sqlite"
        build_inventory_store(db_path, json_path=DEFAULT_INVENTORY_JSON)
        self.assertTrue(db_path.exists())

        from contextlib import closing

        with closing(sqlite3.connect(db_path)) as db:
            db.row_factory = sqlite3.Row
            manifest = db.execute("SELECT * FROM manifest").fetchone()
            self.assertEqual(manifest["synthetic"], 1)
            self.assertEqual(manifest["reference_snapshot_id"], "FDA-FOOD-2026-10-23-USER-SNAPSHOT")
            self.assertEqual(manifest["set_count"], 48)
            self.assertEqual(manifest["record_count"], 96)

            rows = db.execute("SELECT * FROM inventory ORDER BY item_id").fetchall()
            self.assertEqual(len(rows), 96)

            sets: dict[str, list[str]] = {}
            for r in rows:
                self.assertEqual(tuple(r.keys()), INVENTORY_COLUMNS)
                self.assertEqual(r["source_type"], "SYNTHETIC")
                self.assertGreaterEqual(r["simulated_quantity"], 0)
                sets.setdefault(r["inventory_set_id"], []).append(r["item_id"])

            self.assertEqual(len(sets), 48)
            for set_id, items in sets.items():
                self.assertEqual(len(items), 2, f"Set {set_id} should have 2 items")
                self.assertEqual(sum(1 for i in items if i.endswith("-A")), 1)
                self.assertEqual(sum(1 for i in items if i.endswith("-B")), 1)

            # Item 24: Leading-zero lot 060723 preserved unchanged in SQLite
            inv_003_a = db.execute(
                "SELECT * FROM inventory WHERE item_id = 'INV-003-A'"
            ).fetchone()
            self.assertEqual(inv_003_a["lot_code"], "060723")
            self.assertEqual(inv_003_a["simulated_quantity"], 65)
            self.assertEqual(inv_003_a["store_id"], "SIM-STORE-04")
            self.assertEqual(inv_003_a["inventory_reference_date"], "2023-08-25")

    def test_refuses_to_overwrite_existing_database(self) -> None:
        db_path = self.tmp_dir / "existing.sqlite"
        db_path.write_text("placeholder", encoding="utf-8")
        with self.assertRaises(InventoryLoadError):
            build_inventory_store(db_path, json_path=DEFAULT_INVENTORY_JSON)

    def test_rejects_invalid_set_pair_or_count(self) -> None:
        raw = json.loads(DEFAULT_INVENTORY_JSON.read_text(encoding="utf-8"))
        bad = deepcopy(raw)
        # Replace INV-001-B with another -A suffix
        bad["records"][1]["item_id"] = "INV-001-A2"
        bad_json = self.tmp_dir / "bad.json"
        bad_json.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(InventoryLoadError):
            build_inventory_store(self.tmp_dir / "bad.sqlite", json_path=bad_json)


if __name__ == "__main__":
    unittest.main()
